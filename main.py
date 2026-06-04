#!/usr/bin/env python3
import sys, time, json, logging, os, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, memory
from telegram_bot import Bot
from ai_engine import AIEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ab.main")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, format, *args):
        pass

LOG_FILE = os.path.expanduser("~/ab_bot.log")
fh = logging.FileHandler(LOG_FILE)
fh.setLevel(logging.INFO)
logging.getLogger("ab").addHandler(fh)


def handle_update(bot, engine, update):
    # Handle button callbacks
    cb = update.get("callback_query")
    if cb:
        uid = cb["from"]["id"]
        chat_id = cb["message"]["chat"]["id"]
        data = cb.get("data", "")
        callback_id = cb.get("id")
        msg_id = cb["message"]["message_id"]
        engine.handle_callback(uid, data, chat_id, bot, callback_id, msg_id)
        return

    msg = update.get("message")
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    username = msg["from"].get("username", "unknown")
    first_name = msg["from"].get("first_name", "User")
    text = msg.get("text", "").strip()

    cfg = config.load()

    # Check for media content
    has_media = False
    media_type = None
    media_info = ""

    if "video" in msg:
        has_media = True
        media_type = "video"
        v = msg["video"]
        media_info = f"video ({v.get('file_size',0)} bytes, {v.get('duration',0)}s, {v.get('file_id','')[:20]}...)"
        memory.add_conv(uid, "user", f"[Sent a video: {v.get('file_name', 'video')}]")
    elif "photo" in msg:
        has_media = True
        media_type = "photo"
        photos = msg["photo"]
        largest = photos[-1] if photos else {}
        media_info = f"photo ({largest.get('file_size',0)} bytes, {largest.get('file_id','')[:20]}...)"
        memory.add_conv(uid, "user", f"[Sent a photo]")
    elif "document" in msg:
        has_media = True
        media_type = "document"
        d = msg["document"]
        fname = d.get("file_name", "file")
        media_info = f"document '{fname}' ({d.get('file_size',0)} bytes)"
        memory.add_conv(uid, "user", f"[Sent a file: {fname}]")

    logger.info(f"Msg from {first_name} (@{username}, id={uid}): {text[:100] or f'[{media_type}]'}")

    # No restrictions — everyone can use the bot
    if chat_id not in bot.verified:
        bot.verified.add(chat_id)

    # Handle media
    if has_media and not text:
        bot.send_action(chat_id)
        reply = engine.handle_media(uid, media_type, media_info)
        bot.send_msg(chat_id, reply)
        return

    # Handle file + "use this as prompt" / "my instructions" / etc.
    if has_media and text:
        # Check if user wants this as instructions
        if any(w in text.lower() for w in ["prompt", "instruction", "step", "use this", "follow", "my prompt", "stapes"]):
            if "document" in msg:
                d = msg["document"]
                fid = d.get("file_id", "")
                fname = d.get("file_name", "")
                try:
                    content = bot.download_file(fid)
                    if content:
                        memory.set_instructions(content)
                        bot.send_msg(chat_id, f"✅ *Stored as instructions!* Read {len(content)} chars from `{fname}`\nI'll follow these steps from now on.")
                        return None
                except Exception as e:
                    bot.send_msg(chat_id, f"❌ Failed to read file: {e}")
                    return None
        text = f"[{media_type}] {text}"

    # Normal text response
    if text:
        memory.add_conv(uid, "user", text)
        bot.send_action(chat_id)
        reply = engine.respond(uid, text, bot, chat_id)
        if reply:
            bot.send_msg(chat_id, reply)


def start_http():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server on :{port}")
    server.serve_forever()

def main():
    threading.Thread(target=start_http, daemon=True).start()

    # Self-keepalive — ping every 5 min so Render free tier doesn't sleep
    def _keep_alive():
        while True:
            try:
                urlopen(Request("https://ab-bot-fys8.onrender.com/health"), timeout=20)
            except: pass
            time.sleep(300)
    threading.Thread(target=_keep_alive, daemon=True).start()

    cfg = config.load()
    # Force correct token regardless of env var or saved config
    cfg["token"] = "8910243577:AAFndCzlVmIScBebVjCEhczBhvi6Ndx_kpo"
    token = cfg.get("token") or os.environ.get("AB_TOKEN")

    bot = Bot(token)
    engine = AIEngine(cfg)

    if "--no-owner" in sys.argv:
        cfg["owner_id"] = None
        config.save(cfg)
        logger.info("No-owner mode: anyone can use the bot")
    elif cfg.get("owner_id"):
        bot.verified.add(cfg["owner_id"])
        logger.info(f"Owner {cfg['owner_id']} pre-verified")

    logger.info("=" * 50)
    logger.info("ab bot starting...")
    logger.info(f"Token: {token[:10]}...")
    logger.info(f"Owner: {cfg.get('owner_id', 'Not set (verify first)')}")
    logger.info("=" * 50)

    print(f"\n  ab Telegram Bot is running!")
    print(f"  Talk to: @abseking_ai_bot")
    print(f"  Token: {token[:15]}...")
    print(f"  Logs: {LOG_FILE}")
    print(f"  Memory: {memory.MEM}")
    print()

    while True:
        try:
            updates = bot.get_updates()
            if updates:
                for update in updates:
                    handle_update(bot, engine, update)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            print("\nBot stopped.")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
