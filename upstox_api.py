"""Upstox API wrapper for option chain and market data.

Safety: All API calls have retries, timeouts, and error handling.
Never raises unhandled exceptions — returns safe defaults on failure.
"""

import json, urllib.request, urllib.parse, time, logging
from config import UPSTOX_TOKEN_FILE, USER_AGENT

log = logging.getLogger("upstox_api")

_token_cache = {"token": None, "loaded_at": 0}


def _load_token():
    """Load token with caching — re-reads file only every 5 min."""
    now = time.time()
    if _token_cache["token"] and now - _token_cache["loaded_at"] < 300:
        return _token_cache["token"]
    try:
        with open(UPSTOX_TOKEN_FILE) as f:
            _token_cache["token"] = json.load(f)["access_token"]
            _token_cache["loaded_at"] = now
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        log.error(f"Token load failed: {e}")
        raise RuntimeError(f"Cannot load Upstox token from {UPSTOX_TOKEN_FILE}. Run auth first.")
    return _token_cache["token"]


def api_get(url, retries=2, timeout=10):
    """API call with retry and error handling. Returns parsed JSON or raises."""
    token = _load_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read())

            # Upstox sometimes returns success with error in body
            if data.get("status") == "error":
                log.warning(f"API returned error: {data.get('message', '')}")

            return data

        except urllib.error.HTTPError as e:
            last_error = e
            body = ""
            try:
                body = e.read().decode()[:200]
            except:
                pass
            if e.code == 429:  # Rate limited
                wait = 2 ** attempt
                log.warning(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue
            elif e.code == 403:
                raise RuntimeError(f"Upstox 403: Token expired or invalid. Re-authenticate. {body}")
            else:
                log.error(f"HTTP {e.code}: {body}")
                if attempt < retries:
                    time.sleep(1)
                    continue
                raise

        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            log.warning(f"Network error (attempt {attempt+1}): {e}")
            if attempt < retries:
                time.sleep(1)
                continue
            raise RuntimeError(f"Upstox API unreachable after {retries+1} attempts: {e}")

    raise last_error


def get_nifty_ltp():
    """Current Nifty 50 spot price. Returns 0 on failure."""
    try:
        data = api_get("https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_INDEX%7CNifty%2050")
        price = data.get("data", {}).get("NSE_INDEX:Nifty 50", {}).get("last_price", 0)
        if price <= 0:
            log.warning("Nifty LTP returned 0 — market may be closed")
        return price
    except Exception as e:
        log.error(f"get_nifty_ltp failed: {e}")
        return 0


def get_nifty_quote():
    """Full Nifty 50 quote with OHLC."""
    data = api_get("https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_INDEX%7CNifty%2050")
    return data.get("data", {}).get("NSE_INDEX:Nifty 50", {})


def get_option_contracts():
    """Get all available Nifty option contracts with instrument keys."""
    data = api_get("https://api.upstox.com/v2/option/contract?instrument_key=NSE_INDEX%7CNifty%2050")
    return data.get("data", [])


def get_option_quote(instrument_key):
    """Get full quote for a specific option instrument. Returns {} on failure."""
    try:
        encoded = urllib.parse.quote(instrument_key, safe="")
        data = api_get(f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={encoded}")
        values = list(data.get("data", {}).values())
        return values[0] if values else {}
    except Exception as e:
        log.error(f"get_option_quote({instrument_key}) failed: {e}")
        return {}


def get_historical_candles(instrument_key, interval, from_date, to_date):
    """Get historical candles. Returns chronological list or [] on failure."""
    try:
        encoded = urllib.parse.quote(instrument_key, safe="")
        data = api_get(f"https://api.upstox.com/v2/historical-candle/{encoded}/{interval}/{to_date}/{from_date}")
        candles = data.get("data", {}).get("candles", [])
        return sorted(candles, key=lambda x: x[0])
    except Exception as e:
        log.error(f"get_historical_candles failed: {e}")
        return []


def find_itm_options(nifty_spot, expiry_date):
    """Find ITM CE and PE instrument keys closest to spot.

    CE ITM = highest strike BELOW spot (high delta, moves with Nifty)
    PE ITM = lowest strike ABOVE spot (high delta, moves inverse to Nifty)

    Returns: (ce_strike, ce_key, pe_strike, pe_key)
    Raises RuntimeError if no options found.
    """
    if nifty_spot <= 0:
        raise RuntimeError("Cannot find options: Nifty spot price is 0. Market may be closed.")

    contracts = get_option_contracts()
    expiry_contracts = [c for c in contracts if expiry_date in str(c.get("expiry", ""))]

    if not expiry_contracts:
        raise RuntimeError(f"No option contracts found for expiry {expiry_date}")

    atm = round(nifty_spot / 50) * 50

    ce_candidates = []
    pe_candidates = []

    for c in expiry_contracts:
        strike = c.get("strike_price", 0)
        opt_type = c.get("instrument_type", "")
        key = c.get("instrument_key", "")

        if not key or not strike:
            continue

        # ITM CE: strikes below ATM (within 200 pts)
        if opt_type == "CE" and atm - 200 <= strike <= atm:
            ce_candidates.append((strike, key))
        # ITM PE: strikes above ATM (within 200 pts)
        if opt_type == "PE" and atm <= strike <= atm + 200:
            pe_candidates.append((strike, key))

    if not ce_candidates:
        raise RuntimeError(f"No ITM CE options found near ATM {atm} for expiry {expiry_date}")
    if not pe_candidates:
        raise RuntimeError(f"No ITM PE options found near ATM {atm} for expiry {expiry_date}")

    # Closest ITM: CE = highest below ATM, PE = lowest above ATM
    ce_candidates.sort(key=lambda x: -x[0])
    pe_candidates.sort(key=lambda x: x[0])

    ce_strike, ce_key = ce_candidates[0]
    pe_strike, pe_key = pe_candidates[0]

    return ce_strike, ce_key, pe_strike, pe_key


def get_next_expiry():
    """Get the nearest expiry date string (YYYY-MM-DD). Raises if none found."""
    contracts = get_option_contracts()
    expiries = sorted(set(c.get("expiry", "")[:10] for c in contracts if c.get("expiry")))
    if not expiries:
        raise RuntimeError("No option expiries found. Upstox API may be down.")
    return expiries[0]
