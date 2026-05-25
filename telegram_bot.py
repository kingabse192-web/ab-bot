import json, random, time, logging, os, subprocess, tempfile, uuid

logger = logging.getLogger("ab.bot")
API = "https://api.telegram.org/bot"
OUTBOX = os.path.expanduser("~/.ab_outbox")


class Bot:
    def __init__(self, token):
        self.base = API + token
        self.offset = 0
        self.verified = set()
        self.pending_codes = {}

    def _enqueue(self, method, data=None, files=None):
        """Write API call to outbox for sender process to pick up"""
        os.makedirs(OUTBOX, exist_ok=True)
        fid = str(uuid.uuid4())[:8]
        entry = {"base": self.base, "method": method, "data": data, "files": files}
        path = os.path.join(OUTBOX, f"{fid}.json")
        with open(path, "w") as f:
            json.dump(entry, f)
        return {"ok": True, "queued": True}

    def _fire(self, method, data=None):
        """Fire-and-forget: no wait, no retry, no enqueue"""
        url = f"{self.base}/{method}"
        try:
            args = ["curl", "-s", "--max-time", "60", "--connect-timeout", "15", "-o", "/dev/null"]
            if data is not None:
                inp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
                json.dump(data, inp)
                inp.close()
                args.extend(["-X", "POST", "-H", "Content-Type: application/json", "-d", f"@{inp.name}"])
            args.append(url)
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass

    def _call(self, method, data=None, retries=2):
        """Run api call. Returns dict on success, None on fail (already logged)."""
        url = f"{self.base}/{method}"
        out = tempfile.mktemp(suffix=".json")
        for attempt in range(retries):
            try:
                inp = None
                args = ["curl", "-s", "--max-time", "60", "--connect-timeout", "15"]
                if data is not None:
                    inp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
                    json.dump(data, inp)
                    inp.close()
                    args.extend(["-X", "POST", "-H", "Content-Type: application/json", "-d", f"@{inp.name}"])
                args.extend(["-o", out, url])
                r = subprocess.run(args, capture_output=True, timeout=65)
                if r.returncode == 0:
                    with open(out) as f:
                        return json.load(f)
                if attempt == 0:
                    logger.warning(f"curl {method} code={r.returncode} stderr={r.stderr[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning(f"curl {method} timed out")
            except Exception as e:
                logger.warning(f"curl {method} exception: {e}")
            finally:
                if inp:
                    try: os.unlink(inp.name)
                    except: pass
                try: os.unlink(out)
                except: pass
        return None

    def _multipart(self, method, fields, files):
        url = f"{self.base}/{method}"
        try:
            args = ["curl", "-s", "--max-time", "120", "--connect-timeout", "15"]
            for k, v in fields.items():
                args.extend(["-F", f"{k}={v}"])
            for k, (fname, data, mime) in (files or {}).items():
                tmp = os.path.join(tempfile.mkdtemp(), fname)
                with open(tmp, "wb") as f:
                    f.write(data)
                args.extend(["-F", f"{k}=@{tmp};type={mime}"])
            args.append(url)
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Multipart upload failed: {e}")

    def send_msg(self, chat_id, text, parse_mode="Markdown"):
        self._fire("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    def send_plain(self, chat_id, text):
        self._fire("sendMessage", {"chat_id": chat_id, "text": text})

    def send_buttons(self, chat_id, text, buttons, parse_mode="Markdown"):
        kb = {"inline_keyboard": [[{"text": b, "callback_data": d}] for b, d in buttons]}
        self._fire("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "reply_markup": kb})

    def edit_buttons(self, chat_id, msg_id, text, buttons, parse_mode="Markdown"):
        kb = {"inline_keyboard": [[{"text": b, "callback_data": d}] for b, d in buttons]}
        self._fire("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode, "reply_markup": kb})

    def edit_text(self, chat_id, msg_id, text, parse_mode="Markdown"):
        self._fire("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode})

    def answer_callback(self, callback_id, text=""):
        self._fire("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def send_action(self, chat_id, action="typing"):
        self._fire("sendChatAction", {"chat_id": chat_id, "action": action})

    def send_file(self, chat_id, file_path, caption=""):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(file_path)
            mime = "application/octet-stream"
            self._multipart("sendDocument", {"chat_id": chat_id, "caption": caption}, {"document": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send file failed: {e}")

    def send_voice(self, chat_id, audio_path):
        try:
            with open(audio_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(audio_path)
            ext = os.path.splitext(fname)[1].lower()
            mime = "audio/mpeg" if ext == ".mp3" else "audio/ogg"
            self._multipart("sendVoice", {"chat_id": chat_id}, {"voice": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send voice failed: {e}")

    def send_photo(self, chat_id, photo_path, caption=""):
        try:
            with open(photo_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(photo_path)
            mime = "image/jpeg" if fname.endswith(".jpg") else "image/png"
            self._multipart("sendPhoto", {"chat_id": chat_id, "caption": caption}, {"photo": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send photo failed: {e}")

    def send_text_as_file(self, chat_id, content, filename="output.txt", caption=""):
        import tempfile
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "w") as f:
            f.write(content)
        self.send_file(chat_id, path, caption)
        try:
            os.remove(path)
        except:
            pass

    def get_updates(self):
        import urllib.request, urllib.error
        url = f"{self.base}/getUpdates"
        payload = json.dumps({"offset": self.offset, "timeout": 2, "allowed_updates": ["message", "callback_query"]}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            if result.get("ok"):
                for update in result.get("result", []):
                    self.offset = update["update_id"] + 1
                return result["result"]
        except Exception as e:
            logger.warning(f"getUpdates error: {e}")
        # Last resort: try curl directly
        try:
            import subprocess
            r = subprocess.run(
                ["curl", "-s", "--max-time", "15", "--connect-timeout", "10",
                 "-X", "POST", "-H", "Content-Type: application/json",
                 "-d", json.dumps({"offset": self.offset, "timeout": 2, "allowed_updates": ["message", "callback_query"]}),
                 url],
                capture_output=True, timeout=20
            )
            if r.returncode == 0:
                result = json.loads(r.stdout)
                if result.get("ok"):
                    for update in result.get("result", []):
                        self.offset = update["update_id"] + 1
                    return result["result"]
            logger.warning(f"getUpdates curl failed (code {r.returncode}): {r.stderr[:200]}")
        except Exception as e:
            logger.warning(f"getUpdates curl exception: {e}")
        return []

    def send_code(self, chat_id):
        code = f"{random.randint(0,9999):04d}"
        self.pending_codes[chat_id] = code
        self.send_plain(chat_id, f"*Verification*\nYour code: `{code}`\nReply with this code to activate.")
        return code

    def verify(self, chat_id, code):
        if chat_id in self.pending_codes and self.pending_codes[chat_id] == code:
            del self.pending_codes[chat_id]
            self.verified.add(chat_id)
            self.send_plain(chat_id, "Verified! Send `help` to see what I can do.")
            return True
        self.send_plain(chat_id, "Wrong code. Send `start` for a new one.")
        return False
