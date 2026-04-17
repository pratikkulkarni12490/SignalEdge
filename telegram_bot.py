"""Telegram Bot — Send trade alerts and receive confirmations."""

import json, urllib.request, urllib.parse, logging, time, threading

log = logging.getLogger("telegram")

TOKEN = "8683612225:AAHzpee3t-ZoPv-hqMbDRB-jDImgVihC3Iw"
CHAT_ID = 6278021193
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
UA = "Mozilla/5.0"


def _post(method, payload):
    """Send request to Telegram API."""
    url = f"{BASE_URL}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "User-Agent": UA
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        log.error(f"Telegram API error: {e}")
        return {"ok": False}


def send_message(text, parse_mode="Markdown"):
    """Send a text message."""
    return _post("sendMessage", {
        "chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode
    })


def send_signal_alert(direction, confidence, ce_strike, pe_strike, ce_premium, pe_premium, nifty, expiry, lots):
    """Send a trade signal with CONFIRM/SKIP buttons."""
    icon = "🟢" if direction == "BULL" else "🔴"
    label = "BULLISH" if direction == "BULL" else "BEARISH"
    conf_score, conf_tier = confidence[0], confidence[1]
    conf_bar = "█" * (conf_score // 10) + "░" * (10 - conf_score // 10)

    if direction == "BULL":
        entry_opt = f"{ce_strike}CE"
        entry_p = ce_premium
    else:
        entry_opt = f"{pe_strike}PE"
        entry_p = pe_premium

    sl = round(entry_p * 0.70, 1)
    tgt1 = round(entry_p * 1.30, 1)
    tgt2 = round(entry_p * 1.50, 1)
    risk = (entry_p - sl) * 75 * lots

    text = f"""{icon}{icon} *{label} SIGNAL DETECTED*

*Confidence:* {conf_bar} {conf_score}/100 ({conf_tier})
*Nifty:* {nifty:.1f} | *Expiry:* {expiry}

*BUY {entry_opt} @ ₹{entry_p:.1f}*
• SL: ₹{sl:.1f} (-30%)
• TGT1: ₹{tgt1:.1f} (+30%)
• TGT2: ₹{tgt2:.1f} (+50%)
• Size: {lots} lots ({lots * 75} qty)
• Max Risk: ₹{risk:,.0f}

_Waiting for your confirmation..._"""

    # Send with inline keyboard (callback_data max 64 bytes)
    return _post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": f"✅ CONFIRM ({lots} lots)", "callback_data": "confirm"},
                    {"text": "❌ SKIP", "callback_data": "skip"}
                ]
            ]
        }
    })


def send_pnl_update(direction, opt_name, entry, current, lots, pnl, pct):
    """Send P&L update."""
    emoji = "📈" if pnl > 0 else "📉"
    text = f"""{emoji} *P&L Update*
{opt_name} @ ₹{entry:.1f} → ₹{current:.1f}
*P&L: ₹{pnl:+,.0f} ({pct:+.1f}%)* × {lots} lots"""
    return send_message(text)


def send_exit_alert(reason, opt_name, entry, exit_price, lots, final_pnl):
    """Send exit notification."""
    emoji = "✅" if final_pnl > 0 else "❌"
    text = f"""{emoji} *POSITION CLOSED*
{opt_name}: ₹{entry:.1f} → ₹{exit_price:.1f}
*Final P&L: ₹{final_pnl:+,.0f}*
Lots: {lots} | Reason: {reason}"""
    return send_message(text)


def send_eod_summary(date, nifty_open, nifty_close, signal_dir, confidence, result, pnl):
    """Send end-of-day summary."""
    day_chg = nifty_close - nifty_open
    emoji = "✅" if result == "CORRECT" else "❌" if result == "WRONG" else "⚪"

    text = f"""📊 *EOD Summary — {date}*

Nifty: {nifty_open:.1f} → {nifty_close:.1f} ({day_chg:+.1f})
Signal: {signal_dir or 'NONE'} {emoji}
Confidence: {confidence or 'N/A'}
Result: *{result}*
P&L: *₹{pnl:+,.0f}*"""
    return send_message(text)


def wait_for_confirmation(timeout_sec=120):
    """Poll for user's button click response. Returns 'confirm' or 'skip'."""
    deadline = time.time() + timeout_sec
    last_update_id = 0

    while time.time() < deadline:
        try:
            result = _post("getUpdates", {"offset": last_update_id + 1, "timeout": 10})
            for update in result.get("result", []):
                last_update_id = update["update_id"]
                callback = update.get("callback_query", {})
                if callback:
                    data = callback.get("data", "")
                    # Acknowledge the button press
                    _post("answerCallbackQuery", {"callback_query_id": callback["id"]})

                    action = data.strip()

                    if action == "confirm":
                        send_message("✅ *Order confirmed!* Placing trade...")
                        return "confirm"
                    elif action == "skip":
                        send_message("❌ Signal skipped. No order placed.")
                        return "skip"
        except Exception as e:
            log.warning(f"Polling error: {e}")
            time.sleep(2)

    send_message("⏰ Confirmation timed out. Signal skipped.")
    return "timeout"
