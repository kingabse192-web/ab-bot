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

    def _curl(self, method, data=None):
        """Try curl first — returns None if it fails"""
        url = f"{self.base}/{method}"
        out = tempfile.mktemp(suffix=".json")
        try:
            args = ["curl", "-s", "--max-time", "20", "--connect-timeout", "10"]
            if data is not None:
                inp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
                json.dump(data, inp)
                inp.close()
                args.extend(["-X", "POST", "-H", "Content-Type: application/json", "-d", f"@{inp.name}"])
            else:
                inp = None
            args.extend(["-o", out, url])
            r = subprocess.run(args, capture_output=True, timeout=30)
            if inp:
                try: os.unlink(inp.name)
                except: pass
            if r.returncode == 0:
                with open(out) as f:
                    return json.load(f)
            return None
        except Exception as e:
            logger.warning(f"curl {method} exception: {e}")
            return None
        finally:
            try: os.unlink(out)
            except: pass

    def _call(self, method, data=None, retries=2):
        for attempt in range(retries):
            try:
                result = self._curl(method, data)
                if result:
                    return result
                time.sleep(1)
            except Exception as e:
                logger.warning(f"API call {method} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
        # Fallback: enqueue for sender
        logger.warning(f"Enqueuing {method} to outbox")
        return self._enqueue(method, data)

    def _multipart(self, method, fields, files):
        # Files is dict of {key: (filename, data_bytes, mime)}
        file_refs = {}
        tmp_files = []
        for k, (fname, data, mime) in (files or {}).items():
            tmp = os.path.join(tempfile.mkdtemp(), fname)
            with open(tmp, "wb") as f:
                f.write(data)
            file_refs[k] = {"path": tmp, "mime": mime}
            tmp_files.append(tmp)
        # Try curl first
        url = f"{self.base}/{method}"
        try:
            args = ["curl", "-s", "--max-time", "60"]
            for k, v in fields.items():
                args.extend(["-F", f"{k}={v}"])
            for k, ref in file_refs.items():
                args.extend(["-F", f"{k}=@{ref['path']};type={ref['mime']}"])
            args.append(url)
            r = subprocess.run(args, capture_output=True, timeout=70)
            if r.returncode == 0:
                return json.loads(r.stdout)
            logger.warning(f"curl multipart {method} failed: {r.stderr[:200]}")
        except Exception as e:
            logger.error(f"Multipart upload failed: {e}")
        # Fallback: enqueue
        file_data = {}
        for k, ref in file_refs.items():
            with open(ref["path"], "rb") as f:
                file_data[k] = [os.path.basename(ref["path"]), ref["mime"]]
        return self._enqueue(method, fields, file_data)

    def send_msg(self, chat_id, text, parse_mode="Markdown"):
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    def send_plain(self, chat_id, text):
        return self._call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_buttons(self, chat_id, text, buttons, parse_mode="Markdown"):
        kb = {"inline_keyboard": [[{"text": b, "callback_data": d}] for b, d in buttons]}
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "reply_markup": kb})

    def edit_buttons(self, chat_id, msg_id, text, buttons, parse_mode="Markdown"):
        kb = {"inline_keyboard": [[{"text": b, "callback_data": d}] for b, d in buttons]}
        return self._call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode, "reply_markup": kb})

    def edit_text(self, chat_id, msg_id, text, parse_mode="Markdown"):
        return self._call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode})

    def answer_callback(self, callback_id, text=""):
        return self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def send_action(self, chat_id, action="typing"):
        return self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    def send_file(self, chat_id, file_path, caption=""):
        """Send a file by its local path"""
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(file_path)
            mime = "application/octet-stream"
            return self._multipart("sendDocument", {"chat_id": chat_id, "caption": caption}, {"document": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send file failed: {e}")
            return None

    def send_voice(self, chat_id, audio_path):
        """Send an audio file as a voice message"""
        try:
            with open(audio_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(audio_path)
            ext = os.path.splitext(fname)[1].lower()
            mime = "audio/mpeg" if ext == ".mp3" else "audio/ogg"
            return self._multipart("sendVoice", {"chat_id": chat_id}, {"voice": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send voice failed: {e}")
            return None

    def send_photo(self, chat_id, photo_path, caption=""):
        """Send a photo by its local path"""
        try:
            with open(photo_path, "rb") as f:
                data = f.read()
            fname = os.path.basename(photo_path)
            mime = "image/jpeg" if fname.endswith(".jpg") else "image/png"
            return self._multipart("sendPhoto", {"chat_id": chat_id, "caption": caption}, {"photo": (fname, data, mime)})
        except Exception as e:
            logger.error(f"Send photo failed: {e}")
            return None

    def send_text_as_file(self, chat_id, content, filename="output.txt", caption=""):
        """Send text content as a file"""
        import tempfile
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "w") as f:
            f.write(content)
        result = self.send_file(chat_id, path, caption)
        try:
            os.remove(path)
        except:
            pass
        return result

    def get_updates(self):
        result = self._call("getUpdates", {
            "offset": self.offset,
            "timeout": 2,
            "allowed_updates": ["message"]
        })
        if result:
            for update in result.get("result", []):
                self.offset = update["update_id"] + 1
            return result["result"]
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
