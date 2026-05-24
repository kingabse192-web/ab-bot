#!/usr/bin/env python3
import sys, time, json, logging, os

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

LOG_FILE = os.path.expanduser("~/ab_bot.log")
fh = logging.FileHandler(LOG_FILE)
fh.setLevel(logging.INFO)
logging.getLogger("ab").addHandler(fh)


def handle_update(bot, engine, update):
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

    # If owner exists, ignore everyone else
    if cfg.get("owner_id") and str(uid) != str(cfg["owner_id"]):
        if text.lower() in ["/start", "start", "hi", "hello", "hey"]:
            bot.send_plain(chat_id, "This bot is private. Only the owner can use it.")
        return

    if chat_id not in bot.verified:
        is_start = text.lower() in ["/start", "start", "hi", "hello", "hey"]
        is_code = text.isdigit() and len(text) == 4

        if is_start:
            memory.add_conv(uid, "system", f"Verification requested by {username}")
            bot.send_code(chat_id)
            return
        elif is_code:
            if bot.verify(chat_id, text):
                cfg["owner_id"] = uid
                cfg["owner_username"] = username
                config.save(cfg)
                memory.add_conv(uid, "system", f"User verified: {username} ({first_name})")
                bot.send_plain(chat_id, (
                    f"Welcome *{first_name}*! I'm *ab*, fully yours.\n\n"
                    "Send `help` to see commands.\n"
                    "Tell me about yourself and I'll learn!\n"
                    "I can also learn from files, photos, and videos you send!"
                ))
            return
        else:
            bot.send_plain(chat_id, "Send `start` to begin verification.")
            return

    # Handle media
    if has_media and not text:
        bot.send_action(chat_id)
        reply = engine.handle_media(uid, media_type, media_info)
        bot.send_msg(chat_id, reply)
        return

    # Text + media
    if has_media and text:
        text = f"[{media_type}] {text}"

    # Normal text response
    if text:
        bot.send_action(chat_id)
        reply = engine.respond(uid, text, bot, chat_id)
        if reply:
            bot.send_msg(chat_id, reply)


def main():
    cfg = config.load()
    token = os.environ.get("AB_TOKEN") or cfg.get("token")

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
    print(f"  Talk to: @Absalew1234_bot")
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
