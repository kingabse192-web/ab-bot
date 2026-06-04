import sys, os, json, logging, traceback

sys.path.insert(0, '/home/Aiahent/ab-bot')
os.chdir('/home/Aiahent/ab-bot')

logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(message)s')
logger = logging.getLogger('pa.wsgi')

# Load config
config_path = os.path.expanduser('~/.ab_config.json')
default_cfg = {
    "token": "8910243577:AAFndCzlVmIScBebVjCEhczBhvi6Ndx_kpo",
    "owner_id": 7267489158,
    "owner_username": "kingabse192web",
}
if os.path.exists(config_path):
    with open(config_path) as f:
        cfg = {**default_cfg, **json.load(f)}
else:
    cfg = default_cfg

from telegram_bot import Bot
from ai_engine import AIEngine
import memory

bot = Bot(cfg['token'])
engine = AIEngine(cfg)

if cfg.get('owner_id'):
    bot.verified.add(int(cfg['owner_id']))
    logger.info(f'Owner pre-verified: {cfg["owner_id"]}')

def handle_update(update):
    cb = update.get('callback_query')
    if cb:
        uid = cb['from']['id']
        chat_id = cb['message']['chat']['id']
        data = cb.get('data', '')
        cid = cb.get('id')
        mid = cb['message']['message_id']
        engine.handle_callback(uid, data, chat_id, bot, cid, mid)
        return
    msg = update.get('message')
    if not msg:
        return
    chat_id = msg['chat']['id']
    uid = msg['from']['id']
    username = msg['from'].get('username', 'unknown')
    first_name = msg['from'].get('first_name', 'User')
    text = msg.get('text', '').strip()
    logger.info(f'Msg from @{username}: {text[:80]}')
    # No restrictions — everyone can use the bot
    if chat_id not in bot.verified:
        bot.verified.add(chat_id)
    if text:
        bot.send_action(chat_id)
        reply = engine.respond(uid, text, bot, chat_id)
        if reply:
            bot.send_msg(chat_id, reply)

def application(environ, start_response):
    try:
        if environ['REQUEST_METHOD'] == 'POST':
            length = int(environ.get('CONTENT_LENGTH', 0))
            if length > 0:
                body = environ['wsgi.input'].read(length).decode('utf-8')
                update = json.loads(body)
                handle_update(update)
                start_response('200 OK', [('Content-Type', 'application/json')])
                return [b'{"ok":true}']
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'Telegram bot webhook active']
    except Exception as e:
        logger.error(f'WSGI error: {e} {traceback.format_exc()}')
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [f'Error: {e}'.encode()]
