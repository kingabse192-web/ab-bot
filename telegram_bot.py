import json, random, time, logging, os, uuid
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlencode

logger = logging.getLogger("ab.bot")
API = "https://api.telegram.org/bot"


def _gen_boundary():
    return "----" + uuid.uuid4().hex


class Bot:
    def __init__(self, token):
        self.base = API + token
        self.offset = 0
        self.verified = set()
        self.pending_codes = {}

    def _call(self, method, data=None, retries=3):
        url = f"{self.base}/{method}"
        timeout = 10
        for attempt in range(retries):
            try:
                body = json.dumps(data).encode() if data else None
                req = Request(url, data=body, headers={"Content-Type": "application/json"})
                resp = urlopen(req, timeout=timeout)
                result = json.loads(resp.read())
                return result
            except URLError as e:
                if method == "getUpdates":
                    return {"ok": True, "result": []}
                logger.warning(f"API call {method} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2)
            except Exception as e:
                if method == "getUpdates":
                    return {"ok": True, "result": []}
                logger.error(f"Unexpected error in {method}: {e}")
                return None
        return None

    def _multipart(self, method, fields, files):
        boundary = _gen_boundary()
        body_bytes = b""
        for k, v in fields.items():
            body_bytes += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (filename, data, mime) in files.items():
            body_bytes += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
            body_bytes += data + b"\r\n"
        body_bytes += f"--{boundary}--\r\n".encode()

        url = f"{self.base}/{method}"
        try:
            req = Request(url, data=body_bytes, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            resp = urlopen(req, timeout=60)
            return json.loads(resp.read())
        except Exception as e:
            logger.error(f"Multipart upload failed: {e}")
            return None

    def send_msg(self, chat_id, text, parse_mode="Markdown"):
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    def send_plain(self, chat_id, text):
        return self._call("sendMessage", {"chat_id": chat_id, "text": text})

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
