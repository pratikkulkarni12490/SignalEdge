"""Upstox Token Refresh via Telegram.

Copy of ../token_refresh.py, kept here so this project doesn't depend on
reaching into the parent folder to re-auth. The token file itself is shared
with the parent SignalEdge engine (same Upstox account) — see TOKEN_FILE
below, which is pulled from config.py rather than re-hardcoded, so both
copies of this script always agree on where the token lives.

Flow:
1. Bot sends you the auth URL
2. You open it on phone, login to Upstox
3. Redirects to localhost (page won't load — that's OK)
4. Copy the 'code' from the URL bar (after ?code=)
5. Paste it back to the Telegram bot
6. Bot exchanges code for token and saves it

Requires these environment variables to be set (see ../.env.example):
  UPSTOX_API_KEY, UPSTOX_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json, os, sys, urllib.request, urllib.parse, time

from config import UPSTOX_TOKEN_FILE

def _require_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}. See ../.env.example.")
    return value

API_KEY = _require_env("UPSTOX_API_KEY")
API_SECRET = _require_env("UPSTOX_API_SECRET")
REDIRECT_URI = os.environ.get("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8501/")
TOKEN_FILE = UPSTOX_TOKEN_FILE
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

TG_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
TG_CHAT = int(_require_env("TELEGRAM_CHAT_ID"))

def tg_send(text):
    data = json.dumps({"chat_id": TG_CHAT, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=data, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=10)

def tg_get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={offset}&timeout=30"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    resp = urllib.request.urlopen(req, timeout=35)
    return json.loads(resp.read())

def exchange_code(code):
    data = urllib.parse.urlencode({
        "code": code, "client_id": API_KEY, "client_secret": API_SECRET,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"
    }).encode()
    req = urllib.request.Request("https://api.upstox.com/v2/login/authorization/token",
        data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": UA})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def main():
    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?client_id={API_KEY}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code"

    tg_send(f"🔑 *Token Refresh Required*\n\n1. Tap the link below\n2. Login to Upstox\n3. Page will fail to load (that's OK!)\n4. Copy the code from the URL bar\n   (after ?code=)\n5. Paste it here\n\n[Login to Upstox]({auth_url})")

    print("Auth URL sent to Telegram. Waiting for code...")

    # Poll for the code from Telegram
    last_update_id = 0
    deadline = time.time() + 300  # 5 min timeout

    while time.time() < deadline:
        try:
            updates = tg_get_updates(last_update_id + 1)
            for update in updates.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id", 0)

                if chat_id != TG_CHAT:
                    continue

                # Extract code from URL or plain text
                import urllib.parse as _up
                code = None
                if "code=" in text:
                    # Full URL pasted — extract code parameter
                    parsed = _up.urlparse(text)
                    params = _up.parse_qs(parsed.query)
                    code = params.get("code", [None])[0]
                elif len(text) >= 4 and len(text) <= 20 and text.replace("_","").replace("-","").isalnum():
                    # Just the code pasted
                    code = text

                if code:
                    text = code  # use extracted code
                    print(f"Got code: {text}")
                    try:
                        token_data = exchange_code(text)
                        with open(TOKEN_FILE, "w") as f:
                            json.dump(token_data, f, indent=2)

                        user = token_data.get("user_name", "?")
                        tg_send(f"✅ *Token Saved!*\n\nUser: {user}\nReady for trading.")
                        print(f"SUCCESS: Token saved for {user}")
                        return True
                    except Exception as e:
                        tg_send(f"❌ *Token exchange failed*\n\n{str(e)[:200]}\n\nTry again — paste the code.")
                        print(f"Exchange failed: {e}")

                elif text.startswith("/refresh"):
                    tg_send(f"🔑 *Token Refresh*\n\n[Login to Upstox]({auth_url})\n\nPaste the code after login.")
        except Exception as e:
            print(f"Poll error: {e}")
            time.sleep(5)

    tg_send("⏰ Token refresh timed out. Run /refresh to try again.")
    print("Timeout")
    return False

if __name__ == "__main__":
    main()
