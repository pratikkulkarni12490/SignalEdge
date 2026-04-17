"""Telegram Listener — always running, responds to commands.

Commands:
  /refresh  — trigger Upstox token refresh
  /status   — check if engine is running, token valid
  /pnl      — show current position P&L
"""
import json, urllib.request, time, subprocess, os, signal

TG_TOKEN = "8683612225:AAHzpee3t-ZoPv-hqMbDRB-jDImgVihC3Iw"
TG_CHAT = 6278021193
UA = "Mozilla/5.0"

def tg_send(text):
    data = json.dumps({"chat_id": TG_CHAT, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=data, headers={"Content-Type": "application/json", "User-Agent": UA})
    try: urllib.request.urlopen(req, timeout=10)
    except: pass

def tg_get_updates(offset):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={offset}&timeout=30"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    resp = urllib.request.urlopen(req, timeout=35)
    return json.loads(resp.read())

def handle_refresh():
    tg_send("🔑 Starting token refresh...\n\nWill send login link in a moment.")
    proc = subprocess.Popen(
        ["python3", "/home/ubuntu/signaledge/premium_divergence/token_refresh.py"],
        cwd="/home/ubuntu/signaledge/premium_divergence"
    )
    # Let it run (it handles its own Telegram interaction)

def handle_status():
    # Check token
    token_ok = False
    try:
        with open("/home/ubuntu/signaledge/data/.upstox_token.json") as f:
            t = json.load(f)
            token_ok = bool(t.get("access_token"))
        age = time.time() - os.path.getmtime("/home/ubuntu/signaledge/data/.upstox_token.json")
        token_age = f"{int(age//3600)}h {int((age%3600)//60)}m ago"
    except:
        token_age = "missing"
    
    # Check if engine is running
    engine_running = os.popen("pgrep -f run.py live | wc -l").read().strip() != "0"
    
    # Check if token_refresh is running
    refresh_running = os.popen("pgrep -f token_refresh.py | wc -l").read().strip() != "0"
    
    msg = f"📊 *System Status*\n\n"
    token_str = "Valid" if token_ok else "Missing"
    msg += "Token: " + token_str + " (" + token_age + ")\n"
    engine_str = "Running" if engine_running else "Stopped"
    msg += "Engine: " + engine_str + "\n"
    refresh_str = "In progress" if refresh_running else "Idle"
    msg += "Refresh: " + refresh_str + "\n"
    msg += f"\n_Commands: /refresh /status_"
    tg_send(msg)

def main():
    print("Telegram listener started. Waiting for commands...")
    tg_send("🤖 *SignalEdge Bot Online*\n\nCommands:\n/refresh — refresh Upstox token\n/status — check system status")
    
    last_update_id = 0
    
    while True:
        try:
            updates = tg_get_updates(last_update_id + 1)
            for update in updates.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id", 0)
                
                if chat_id != TG_CHAT:
                    continue
                
                if text == "/refresh":
                    handle_refresh()
                elif text == "/status":
                    handle_status()
                elif text == "/help":
                    tg_send("🤖 *Commands:*\n/refresh — refresh Upstox token\n/status — check engine & token status")
        
        except KeyboardInterrupt:
            print("Listener stopped")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
