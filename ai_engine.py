import json, subprocess, time, logging, re, os, tempfile, datetime, random
from urllib.request import Request, urlopen, URLError
import memory, urllib.parse, urllib.request, wave, struct, math

logger = logging.getLogger("ab.engine")
CODE_DIR = os.path.expanduser("~/ab_codes")


class LangDetector:
    SCRIPT_RANGES = {
        "ar": (0x0600, 0x06FF), "fa": (0x0600, 0x06FF),
        "zh": (0x4E00, 0x9FFF), "ja": (0x3040, 0x30FF),
        "ko": (0xAC00, 0xD7AF), "ru": (0x0400, 0x04FF),
        "hi": (0x0900, 0x097F), "th": (0x0E00, 0x0E7F),
        "el": (0x0370, 0x03FF), "he": (0x0590, 0x05FF),
    }
    LANG_WORDS = {
        "ar": ["مرحبا", "كيف", "شكرا", "ما", "هل", "هذا", "انا", "أنت", "على", "في", "من", "لا", "نعم", "أنا"],
        "fr": ["bonjour", "merci", "comment", "je", "tu", "nous", "vous", "parle", "français", "oui", "non", "est", "pas", "avec", "dans"],
        "es": ["hola", "gracias", "como", "que", "por", "para", "esta", "con", "más", "bien", "si", "no", "del", "las", "los"],
        "de": ["hallo", "danke", "wie", "was", "ist", "das", "nicht", "mit", "und", "der", "die", "das", "ich", "du", "sie"],
        "pt": ["olá", "obrigado", "como", "que", "para", "com", "mais", "bem", "sim", "não", "está", "por"],
        "it": ["ciao", "grazie", "come", "che", "per", "con", "più", "bene", "si", "no", "è", "sono"],
        "nl": ["hallo", "dank", "hoe", "wat", "is", "het", "niet", "met", "en", "de", "het", "een", "ik", "je"],
        "tr": ["merhaba", "teşekkür", "nasıl", "ne", "bu", "ben", "sen", "ve", "bir", "için", "değil", "var"],
        "id": ["halo", "terima", "bagaimana", "apa", "ini", "saya", "anda", "dan", "tidak", "ada"],
        "ms": ["hai", "terima", "bagaimana", "apa", "ini", "saya", "anda", "dan", "tidak", "ada"],
        "vi": ["xin chào", "cảm ơn", "thế nào", "gì", "này", "tôi", "bạn", "và", "không", "có", "là"],
        "fil": ["kumusta", "salamat", "paano", "ano", "ito", "ako", "ikaw", "at", "hindi", "may"],
        "sw": ["habari", "asante", "vipi", "nini", "hii", "mimi", "wewe", "na", "si", "kuna"],
    }
    FALLBACK_TTS = {
        "ar": "ar", "fa": "fa", "fr": "fr", "es": "es", "de": "de",
        "pt": "pt", "it": "it", "nl": "nl", "tr": "tr", "id": "id",
        "ms": "ms", "vi": "vi", "ru": "ru", "hi": "hi", "th": "th",
        "el": "el", "he": "he", "ko": "ko", "ja": "ja", "zh": "zh-CN",
        "fil": "tl", "sw": "sw",
    }

    @staticmethod
    def detect(text):
        if not text or not text.strip():
            return "en"
        t = text.strip()[:200]
        scores = {}
        # Check Unicode scripts
        for cp in [ord(c) for c in t]:
            for lang, (start, end) in LangDetector.SCRIPT_RANGES.items():
                if start <= cp <= end:
                    scores[lang] = scores.get(lang, 0) + 2
        # Check common words
        words = t.lower().split()
        for word in words:
            for lang, wlist in LangDetector.LANG_WORDS.items():
                if word in wlist:
                    scores[lang] = scores.get(lang, 0) + 5
        if scores:
            top = max(scores, key=scores.get)
            score = scores[top]
            total = max(len(t) // 2, 1)
            if score > total * 0.3:
                return top
        # Check for Arabic-specific characters (distinct from Farsi)
        arabic_chars = sum(1 for c in t if '\u0600' <= c <= '\u06FF')
        if arabic_chars > len(t) * 0.3:
            return "ar"
        return "en"

    @staticmethod
    def tts_lang(lang):
        return LangDetector.FALLBACK_TTS.get(lang, lang if len(lang) == 2 else "en")


class MoodDetector:
    @staticmethod
    def detect(text):
        t = text.lower().strip()
        if not t:
            return "neutral"
        if any(w in t for w in ["haha", "lol", "😂", "🔥", "❤️", "amazing", "awesome", "great", "love", "happy"]):
            return "happy"
        if t.endswith("!!!") or t.count("!") >= 2:
            return "excited"
        if any(w in t for w in ["sad", "depressed", "lonely", "crying", "😢", "😭", "hurts", "pain"]):
            return "sad"
        if any(w in t for w in ["angry", "mad", "furious", "annoyed", "😠", "🤬", "stupid", "damn", "hate"]):
            return "angry"
        if t.isupper() and len(t) > 5:
            return "angry"
        if any(w in t for w in ["tired", "sleepy", "exhausted", "zzz", "sleep"]):
            return "tired"
        if t.startswith(("what", "why", "how", "when", "where", "who", "can you", "could you", "tell me", "show me", "define", "explain")):
            return "curious"
        if any(w in t for w in ["meaning", "definition", "what is", "what are", "what does", "how to", "how do"]):
            return "curious"
        if t.startswith(("do ", "make ", "create ", "write ", "run ", "execute ", "send ", "code ", "agent ", "file ")):
            return "commanding"
        if any(w in t for w in ["hey", "yo", "sup", "whats up", "how's it", "bro", "dude", "man"]):
            return "casual"
        if any(w in t for w in ["thanks", "thank you", "thx", "appreciate"]):
            return "grateful"
        if t.endswith("?"):
            return "curious"
        if len(t) < 20:
            return "casual"
        return "neutral"


class AIEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ollama_ready = False
        self.ollama_check_time = 0
        self.pending_q = {}
        self.check_ollama()
        os.makedirs(CODE_DIR, exist_ok=True)
        self.mood = MoodDetector()
        self._download_seed()

    def check_ollama(self):
        if time.time() - self.ollama_check_time < 30:
            return
        self.ollama_check_time = time.time()
        try:
            req = Request(f"{self.cfg['ollama_host']}/api/tags")
            resp = urlopen(req, timeout=3)
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            mn = self.cfg.get("model_name", "qwen2.5:0.5b")
            self.ollama_ready = any(mn in m for m in models)
            if self.ollama_ready:
                logger.info(f"Ollama model {mn} ready!")
        except:
            self.ollama_ready = False

    def _web_search(self, topic):
        import urllib.parse
        encoded = urllib.parse.quote(topic)
        # Step 1: Wikipedia — search for correct title, then get summary
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=3&format=json"
            req = Request(url, headers={"User-Agent": "ab-bot/1.0"})
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            if data and len(data) >= 3 and data[1]:
                page_title = data[1][0]
                target = urllib.parse.quote(page_title)
                try:
                    url2 = f"https://en.wikipedia.org/api/rest_v1/page/summary/{target}"
                    req2 = Request(url2, headers={"User-Agent": "ab-bot/1.0"})
                    resp2 = urlopen(req2, timeout=5)
                    d2 = json.loads(resp2.read())
                    extract = d2.get("extract", "")
                    if extract:
                        title = d2.get("title", page_title)
                        page_url = d2.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{target}")
                        reply = f"*{title}*\n\n{extract[:2500]}"
                        if len(extract) > 2500:
                            reply += "\n..."
                        reply += f"\n\n[Read more]({page_url})"
                        return reply, title, extract[:500]
                except:
                    pass
        except:
            pass
        # Step 2: DuckDuckGo API — instant answer + related topics
        try:
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
            req = Request(url, headers={"User-Agent": "ab-bot/1.0"})
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read())
            abstract = data.get("AbstractText", "")
            answer = data.get("Answer", "")
            heading = data.get("Heading", topic) or topic
            if abstract or answer:
                text = abstract or answer
                reply = f"*{heading}*\n\n{text[:2000]}"
                return reply, heading, text[:500]
            # Try RelatedTopics
            related = data.get("RelatedTopics", [])
            if related:
                snippets = []
                for r in related[:3]:
                    if isinstance(r, dict):
                        txt = r.get("Text", "") or r.get("Result", "")
                        if txt:
                            snippets.append(txt[:300])
                if snippets:
                    text = "\n\n".join(snippets)
                    reply = f"*{heading}*\n\n{text[:2000]}"
                    return reply, heading, text[:500]
        except:
            pass
        # Step 3: DuckDuckGo HTML search via curl (multi-source results)
        try:
            url = f"https://lite.duckduckgo.com/lite/?q={encoded}"
            r = subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", "--max-time", "6", url],
                              capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout:
                import re as _re
                results = _re.findall(r'class="result-snippet".*?>(.*?)</td>', r.stdout, _re.DOTALL)
                links = _re.findall(r'class="result-link".*?href="(.*?)".*?>(.*?)</a>', r.stdout, _re.DOTALL)
                if results:
                    lines = []
                    for i, (snippet, link) in enumerate(zip(results[:5], links[:5])):
                        title = _re.sub(r'<[^>]+>', '', link[1] if len(link) > 1 else "").strip()
                        clean = _re.sub(r'<[^>]+>', '', snippet).strip()
                        if title or clean:
                            lines.append(f"• {title or 'Result'} — {clean[:200]}")
                    if lines:
                        text = "\n".join(lines[:5])
                        reply = f"*Results for: {topic}*\n\n{text[:2000]}"
                        return reply, topic, text[:500]
        except:
            pass
        # Step 4: Wikipedia search link fallback
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=1&format=json"
            req = Request(url, headers={"User-Agent": "ab-bot/1.0"})
            resp = urlopen(req, timeout=4)
            data = json.loads(resp.read())
            if data and len(data) >= 3 and data[3]:
                link = data[3][0]
                name = data[1][0]
                return f"*{name}*\n\nSee: {link}", name, link
        except:
            pass
        return None, None, None

    def _web_search_all(self, topic):
        """Collect results from all sources, return list of (source_name, text)"""
        import urllib.parse
        encoded = urllib.parse.quote(topic)
        results = []
        # 1. Wikipedia
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=3&format=json"
            resp = urlopen(Request(url, headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
            data = json.loads(resp.read())
            if data and data[1]:
                pt = urllib.parse.quote(data[1][0])
                resp2 = urlopen(Request(f"https://en.wikipedia.org/api/rest_v1/page/summary/{pt}", headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
                d2 = json.loads(resp2.read())
                if d2.get("extract"):
                    results.append(("Wikipedia", d2["extract"][:1000]))
        except: pass
        # 2. DuckDuckGo API
        try:
            resp = urlopen(Request(f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1", headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
            data = json.loads(resp.read())
            txt = data.get("AbstractText", "") or data.get("Answer", "")
            if txt:
                results.append(("DuckDuckGo", txt[:1000]))
            else:
                for r in data.get("RelatedTopics", [])[:2]:
                    if isinstance(r, dict) and r.get("Text"):
                        results.append(("DuckDuckGo", r["Text"][:500]))
        except: pass
        # 3. DuckDuckGo lite (HTML search - multi-engine results)
        try:
            r = subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", "--max-time", "6", f"https://lite.duckduckgo.com/lite/?q={encoded}"],
                              capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                import re as _re
                snippets = _re.findall(r'class="result-snippet".*?>(.*?)</td>', r.stdout, _re.DOTALL)[:3]
                links = _re.findall(r'class="result-link".*?href="(.*?)".*?>(.*?)</a>', r.stdout, _re.DOTALL)[:3]
                for s, l in zip(snippets, links):
                    clean = _re.sub(r'<[^>]+>', '', s).strip()
                    title = _re.sub(r'<[^>]+>', '', l[1] if len(l) > 1 else "").strip()
                    if clean:
                        results.append(("Web", f"{title}: {clean[:300]}"))
        except: pass
        # 4. Google (via scraping, no API key needed)
        try:
            url = f"https://www.google.com/search?q={encoded}&hl=en"
            r = subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "--max-time", "6", url],
                              capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                import re as _re
                snippets = _re.findall(r'<div[^>]*class="[^"]*BNeawe[^"]*"[^>]*>(.*?)</div>', r.stdout, _re.DOTALL)[:3]
                if not snippets:
                    snippets = _re.findall(r'<span[^>]*class="[^"]*st[^"]*"[^>]*>(.*?)</span>', r.stdout, _re.DOTALL)[:3]
                for s in snippets:
                    clean = _re.sub(r'<[^>]+>', '', s).strip()
                    if clean:
                        results.append(("Google", clean[:300]))
        except: pass
        # 5. AI model
        ai_reply = self._query_free_ai(0, f"Answer concisely: what is {topic}? Provide key facts.", "")
        if ai_reply:
            results.append(("AI", ai_reply[:500]))
        return results

    def _deliver(self, uid, fmt, bot, chat_id, callback_id=None, msg_id=None):
        """Step 6: FORMAT DELIVERY — send answer as text, voice, image, or file"""
        pq = self.pending_q.pop(uid, None)
        if not pq:
            if bot and callback_id: bot.answer_callback(callback_id, "Expired, ask again!")
            return None
        q = pq["q"]
        result = pq.get("result")
        if not result:
            s, result = self._research(uid, q)
            pq["result"] = result
            memory.add_conv(uid, "assistant", result)

        if fmt == "text":
            if bot and chat_id:
                if callback_id: bot.answer_callback(callback_id, "")
                bot.send_msg(chat_id, result)
        elif fmt == "voice":
            if bot and chat_id:
                if callback_id: bot.answer_callback(callback_id, "Generating voice...")
                vp = self._gen_voice(result[:400])
                if vp:
                    bot.send_voice(chat_id, vp)
                    try:
                        os.remove(vp)
                    except:
                        pass
                else:
                    bot.send_msg(chat_id, f"🔊 {result[:2000]}")
        elif fmt == "image":
            if bot and chat_id:
                if callback_id: bot.answer_callback(callback_id, "Generating image...")
                self._cmd_imagine(uid, q, bot, chat_id)
        elif fmt == "file":
            if bot and chat_id:
                if callback_id: bot.answer_callback(callback_id, "")
                bot.send_text_as_file(chat_id, result, "answer.txt", "Your answer")
        return None

    def respond(self, uid, msg, bot=None, chat_id=None):
        # ── STEP 1: READ ──
        msg_lower = msg.lower().strip()
        words = msg.split()

        # ── STEP 2: UNDERSTAND (check commands first) ──
        if any(w in msg_lower for w in ["who are you", "what are you", "your name", "introduce yourself", "tell me about yourself", "what is your name", "about you"]):
            return self._cmd_about()
        if msg_lower in ["help", "/help"]:
            return self._cmd_help(uid)
        if msg_lower in ["facts", "/facts"]:
            return self._cmd_facts(uid)
        if msg_lower in ["rules", "/rules"]:
            return self._cmd_rules(uid)
        if msg_lower in ["history", "/history"]:
            return self._cmd_history(uid)
        if msg_lower in ["status", "/status"]:
            return self._cmd_status()
        if msg_lower in ["time", "/time", "date", "/date"]:
            return self._cmd_time()
        if msg_lower.startswith(("find ", "/find ")):
            return self._cmd_find(uid, msg, bot, chat_id)
        if msg_lower.startswith(("learn ", "lern ")) or msg_lower.startswith(("/learn ", "/lern ")):
            return self._cmd_learn_online(uid, msg, bot, chat_id)
        if msg_lower.startswith("remember ") or msg_lower.startswith("teach "):
            return self._cmd_learn(uid, msg)
        if msg_lower.startswith("forget "):
            return self._cmd_forget(uid, msg)
        if msg_lower.startswith("rule "):
            return self._cmd_add_rule(msg)
        if msg_lower.startswith("unrule "):
            return self._cmd_remove_rule(msg)
        if msg_lower.startswith("code ") or msg_lower.startswith("/code "):
            return self._cmd_code(uid, msg, bot, chat_id)
        if msg_lower.startswith("file ") or msg_lower.startswith("/file "):
            return self._cmd_file(uid, msg, bot, chat_id)
        if msg_lower.startswith("run ") or msg_lower.startswith("/run "):
            return self._cmd_run(msg)
        if msg_lower.startswith("agent ") or msg_lower.startswith("/agent "):
            return self._cmd_agent(uid, msg, bot, chat_id)
        if msg_lower in ["ls", "dir", "/ls", "/dir"]:
            return self._cmd_ls()
        if msg_lower.startswith(("imagine ", "/imagine ", "generate ", "/generate ")):
            return self._cmd_imagine(uid, msg, bot, chat_id)
        if msg_lower.startswith(("movie ", "/movie ", "film ", "/film ")):
            return self._cmd_movie(uid, msg, bot, chat_id)
        if msg_lower.startswith(("song ", "/song ", "music ", "/music ", "lyrics ", "/lyrics ")):
            return self._cmd_song(uid, msg, bot, chat_id)
        if msg_lower.startswith(("github ", "gh ", "/github ", "/gh ")):
            return self._cmd_github(msg)
        if msg_lower.startswith(("tts ", "/tts ")):
            return self._cmd_tts(uid, msg, bot, chat_id)
        if msg_lower.startswith(("say ", "speak ", "voice ", "/say ", "/speak ", "/voice ", "in voice ")):
            return self._cmd_voice(uid, msg, bot, chat_id)
        if msg_lower.startswith(("fix ", "/fix ", "debug ", "/debug ")):
            return self._cmd_fix(uid, msg, bot, chat_id)
        if self._is_code_request(msg_lower):
            return self._auto_code(uid, msg, bot, chat_id)

        # ── STEP 3: THINK (check pending format, detect mode, analyze intent) ──
        if uid in self.pending_q:
            fmts = {"text": "text", "txt": "text", "voice": "voice", "voise": "voice",
                    "image": "image", "img": "image", "picture": "image", "photo": "image",
                    "file": "file", "doc": "file", "document": "file"}
            if msg_lower in fmts:
                return self._deliver(uid, fmts[msg_lower], bot, chat_id)
            self.pending_q.pop(uid)

        mode_desc, personality = self._detect_mode(msg)
        is_question = msg_lower.endswith("?") or any(msg_lower.startswith(w) for w in
            ["what", "why", "how", "when", "where", "who", "can", "could", "will", "would",
             "do", "does", "did", "is", "are", "was", "were", "has", "have", "had",
             "tell", "show", "explain", "define", "describe"])
        is_casual = mode_desc in ("brother", "partner", "friend") or self._is_smalltalk(msg_lower)

        # ── STEP 4: TOOLS / RESEARCH (if serious question from agent/teacher mode) ──
        if not is_casual and (mode_desc in ("agent", "teacher") or (is_question and len(words) >= 2)):
            sources, result = self._research(uid, msg)
            if not result:
                result = self._memory_response(uid, msg)
            memory.add_conv(uid, "assistant", result)
            self.pending_q[uid] = {"q": msg, "result": result, "time": time.time()}
            if bot and chat_id:
                # ── STEP 5: GENERATE (happens inside _research / _memory_response) ──
                # ── STEP 6: DELIVER ──
                bot.send_msg(chat_id, result)
                bot.send_buttons(chat_id, "Change format:", [
                    ("🎤 Voice", f"ans_voice_{uid}"),
                    ("🖼 Image", f"ans_image_{uid}"),
                    ("📎 File", f"ans_file_{uid}")
                ])
            return None

        # Casual / everything else → direct AI reply (steps 4-6 combined)
        result = self._memory_response(uid, msg)
        memory.add_conv(uid, "assistant", result)
        return result

    def handle_callback(self, uid, callback_data, chat_id=None, bot=None,
                        callback_id=None, msg_id=None):
        parts = callback_data.split("_", 2)
        if len(parts) < 3 or parts[0] != "ans":
            return None
        fmt = parts[1]
        if bot and chat_id and msg_id:
            icons = {"text": "📝", "voice": "🎤", "image": "🖼️", "file": "📎"}
            bot.edit_text(chat_id, msg_id, f"{icons.get(fmt, '⏳')} Generating {fmt} answer...")
        return self._deliver(uid, fmt, bot, chat_id, callback_id, msg_id)

    def _is_smalltalk(self, msg):
        t = msg.strip().lower()
        greetings = ["hi", "hello", "hey", "yo", "sup", "heyy", "helo", "hii", "heya", "wasup", "whassup"]
        pleasantries = ["thanks", "thank you", "thx", "ty", "good", "great", "nice", "awesome", "cool", "ok", "okay", "k", "yeah", "yes", "no", "nope", "yep", "maybe", "sure", "fine", "alright"]
        questions_about_me = ["how are you", "how r u", "how do you work", "who are you", "what are you", "what can you do"]
        short_responses = [g for g in greetings if g == t]
        if t in greetings or t in pleasantries or t in questions_about_me or t in short_responses:
            return True
        if len(t.split()) <= 2 and t in ["hi", "hello", "hey", "bye", "ok", "okay", "k", "yes", "no", "yeah"]:
            return True
        if t.startswith(("how are", "who are", "what can", "what's up")):
            return True
        return False

    def _is_question(self, msg):
        t = msg.lower().strip()
        if t.endswith("?"):
            return True
        starters = ("what", "why", "how", "when", "where", "who", "which", "can", "could", "would", "will", "do", "does", "did", "is", "are", "was", "were", "has", "have", "had", "tell", "show", "explain", "define", "describe")
        first_word = t.split()[0] if t.split() else ""
        return first_word in starters

    def _try_answer_from_web(self, uid, msg):
        words = msg.strip().split()
        topic = self._extract_topic(msg)
        if not topic:
            topic = msg.strip().rstrip("?!.")
            if len(words) < 2 or len(words) > 8:
                return None
        reply, title, summary = self._web_search(topic)
        if reply:
            memory.learn_fact(uid, f"about_{topic[:30]}", summary)
            memory.learn_fact(uid, "last_topic", topic)
            return reply
        # Try shorter keywords if search failed
        if len(words) > 3:
            for n in range(3, 1, -1):
                shorter = " ".join(words[-n:]).rstrip("?!.")
                if shorter != topic:
                    reply, title, summary = self._web_search(shorter)
                    if reply:
                        memory.learn_fact(uid, f"about_{shorter[:30]}", summary)
                        memory.learn_fact(uid, "last_topic", shorter)
                        return reply
        return None

        facts = memory.get_facts(uid)
        reply, title, summary = self._web_search(topic)
        if reply:
            memory.learn_fact(uid, f"about_{topic[:30]}", summary)
            memory.learn_fact(uid, "last_topic", topic)
            return reply
        return None

    def _extract_topic(self, msg):
        t = msg.lower().strip().rstrip("?!.")
        patterns = [
            r"what (?:is|are|was|were) (?:a |an |the )?(.+)",
            r"who (?:is|was|are|were) (.+)",
            r"where (?:is|are|was|were) (.+)",
            r"when (?:is|was|did|does) (.+)",
            r"how (?:does|do|is|are|can|to|would) (.+)",
            r"why (?:is|are|does|do|did) (.+)",
            r"tell me about (.+)",
            r"explain (.+)",
            r"define (.+)",
            r"what does (.+) mean",
            r"what is the meaning of (.+)",
            r"what do you know about (.+)",
            r"what about (.+)",
            r"can you explain (.+)",
            r"i want to know about (.+)",
            r"tell me more about (.+)",
            r"describe (.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, t)
            if m:
                topic = m.group(1).strip()
                stop_words = ["it", "that", "this", "me", "you", "him", "her", "them", "us", "it's", "that's"]
                if topic not in stop_words and len(topic) > 2:
                    return topic
        if t.endswith("?") and len(t) > 10:
            for w in ["what", "who", "where", "when", "how", "why"]:
                if w in t:
                    idx = t.index(w) + len(w)
                    rest = t[idx:].strip().lstrip("is are was were does do did can ").strip()
                    if rest and len(rest) > 3:
                        return rest
        return None

    def _cmd_about(self):
        return (
            "*🤖 About ab*\n\n"
            "I am **ab**, your personal AI assistant created by `@kingabse192web`.\n\n"
            "*What I can do:*\n"
            "• Answer questions with multi-source search (Wikipedia, DuckDuckGo, Google, AI)\n"
            "• Generate images from descriptions\n"
            "• Convert text to voice (TTS)\n"
            "• Search movies, songs, and lyrics\n"
            "• Generate code in 12+ languages\n"
            "• Run GitHub commands (`gh`)\n"
            "• Execute shell commands (`run`)\n"
            "• Fix/debug code errors (`fix`)\n"
            "• Learn facts you teach me (`learn`, `remember`)\n"
            "• Create multi-step agents (`agent`)\n\n"
            "Just ask me anything! I always answer in text/voice/image."
        )

    def _cmd_help(self, uid):
        return (
            "*🤖 ab — Your AI Assistant*\n\n"
            "*💬 Chat format:*\n"
            "Ask anything → I offer text/voice/image/file → you pick → I deliver\n"
            "Or reply `text` / `voice` / `image` / `file` directly!\n\n"
            "*🎨 Generate:*\n"
            "`imagine [description]` — AI image\n\n"
            "*🎵 Media:*\n"
            "`movie [name]` — movie info + voice\n"
            "`song [name]` — song info + voice\n"
            "`say [text]` or `voice [question]` — voice reply\n"
            "`tts [text]` — raw text to speech\n\n"
            "*💻 Coding:*\n"
            "`write a python [task]` — auto code + send file\n"
            "`code python [task]` — same\n"
            "`fix [code/error]` — debug and fix code\n\n"
            "*📚 Learn:*\n"
            "`learn [topic]` — research online\n"
            "`remember [key] [value]` — save locally\n"
            "`forget [key]` — remove\n\n"
            "*🐙 GitHub:*\n"
            "`github repos` | `github repo [name]`\n"
            "`github issue [repo] [title]` | `github issues`\n"
            "`github search [query]` | `github me`\n\n"
            "*🤖 Agent:*\n"
            "`agent [task]` — multi-step execution\n"
            "`run [command]` — shell\n"
            "`file [name] [content]` — create file\n"
            "`find [topic]` — multi-source search\n\n"
            "*ℹ️ Info:*\n"
            "`facts` | `rules` | `history` | `time` | `status` | `ls`"
        )

    def _cmd_facts(self, uid):
        facts = memory.get_facts(uid)
        prefs = memory.get_prefs(uid)
        lines = ["*🧠 What I know:*"]
        for f in facts[:15]:
            lines.append(f"  • {f}")
        for k, v in prefs.items():
            lines.append(f"  • {k}: {v['v']}")
        if len(lines) == 1:
            return "📭 Nothing yet. Use `remember` or `learn` to teach me!"
        return "\n".join(lines)

    def _cmd_rules(self, uid):
        rules = memory.get_rules()
        if not rules:
            return "📭 No rules set. Use `rule [text]` to add one."
        return "*📋 Active rules:*\n" + "\n".join(f"  • {r}" for r in rules)

    def _cmd_history(self, uid):
        conv = memory.get_conv(uid)
        if not conv:
            return "📭 No history yet."
        lines = ["*📜 Recent conversation:*"]
        for c in conv[-10:]:
            role = c.get("role", "?")
            txt = c.get("content", "")[:80]
            icon = "👤" if role == "user" else "🤖"
            lines.append(f"  {icon} [{role}] {txt}")
        return "\n".join(lines)

    def _cmd_status(self):
        if self._check_ollama():
            return "✅ AI: *connected*\n⚙️ Using: " + self.cfg.get("model_name", "unknown")
        return "⏳ AI: *downloading...*\n🧠 Still learning from you!"

    def _cmd_time(self):
        now = datetime.datetime.now()
        return f"🕐 *{now.strftime('%A, %B %d %Y - %H:%M:%S')}*"

    def _cmd_learn(self, uid, msg):
        parts = msg.split(None, 2)
        if len(parts) >= 3:
            memory.learn_fact(uid, parts[1], parts[2])
            return f"✅ *Remembered:* {parts[1]} = {parts[2]}"
        elif len(parts) == 2:
            memory.learn_fact(uid, parts[1], True)
            return f"✅ *Noted:* {parts[1]}"
        return "ℹ️ Usage: `remember [topic] [value]`"

    def _cmd_forget(self, uid, msg):
        parts = msg.split(None, 1)
        if len(parts) >= 2:
            if memory.forget_fact(uid, parts[1]):
                return f"🗑️ *Forgotten:* {parts[1]}"
            return f"❓ Nothing about '{parts[1]}'"
        return "ℹ️ Usage: `forget [topic]`"

    def _cmd_add_rule(self, msg):
        rule = msg[5:].strip()
        if rule and memory.add_rule(rule):
            return f"✅ *Rule added:* {rule}"
        return "ℹ️ Usage: `rule [text]`"

    def _cmd_remove_rule(self, msg):
        rule = msg[7:].strip()
        if rule and memory.remove_rule(rule):
            return f"🗑️ *Rule removed:* {rule}"
        return "ℹ️ Usage: `unrule [text]`"

    def _cmd_learn_online(self, uid, msg, bot=None, chat_id=None):
        parts = msg.split(None, 1)
        topic = parts[1].strip() if len(parts) > 1 else ""
        if not topic:
            return "ℹ️ What should I learn? Usage: `learn [topic]`"
        if bot and chat_id:
            bot.send_action(chat_id)
        reply, title, summary = self._web_search(topic)
        if reply:
            memory.learn_fact(uid, f"about_{topic[:30]}", summary)
            memory.learn_fact(uid, "last_topic", topic)
            return reply
        return f"❌ Couldn't find info on '{topic}'."

    def _cmd_find(self, uid, msg, bot=None, chat_id=None):
        parts = msg.split(None, 1)
        query = parts[1].strip() if len(parts) > 1 else ""
        if not query:
            return "ℹ️ Usage: `find [topic]`"
        if bot and chat_id:
            bot.send_action(chat_id)
        reply, title, summary = self._web_search(query)
        if reply:
            memory.learn_fact(uid, f"about_{query[:30]}", summary)
            memory.learn_fact(uid, "last_topic", query)
            return reply
        return f"❌ Couldn't find info on '{query}'."

    def _is_code_request(self, msg):
        languages = ["python", "bash", "shell", "html", "css", "javascript", "js", "c++", "cpp", "c#", "java", "php", "ruby", "go", "rust", "typescript", "ts"]
        has_lang = any(lang in msg for lang in languages)
        has_action = any(w in msg for w in ["write", "make", "create", "build", "code", "generate", "script", "program", "app", "tool", "function"])
        return has_lang and has_action

    def _auto_code(self, uid, msg, bot=None, chat_id=None):
        msg_lower = msg.lower()
        lang = "python"
        for l in ["python", "bash", "html", "javascript", "js", "c++", "cpp", "java", "php", "ruby", "go", "rust", "typescript"]:
            if l in msg_lower:
                lang = l
                break
        if lang == "javascript": lang = "js"
        if lang == "c++": lang = "cpp"
        if lang == "typescript": lang = "ts"
        if lang == "shell": lang = "bash"
        topic = msg
        for w in ["write ", "make ", "create ", "build ", "code ", "generate "]:
            if w in msg_lower:
                idx = msg_lower.index(w) + len(w)
                topic = msg[idx:].strip()
                break
        return self._cmd_code(uid, f"code {lang} {topic}", bot, chat_id)

    def _cmd_code(self, uid, msg, bot=None, chat_id=None):
        parts = msg.split(None, 2)
        if len(parts) < 3:
            return "💻 Usage: `code [lang] [task]`\nEx: `code python calculator`"

        lang = parts[1].lower()
        task = parts[2]
        code = self._gen_code(lang, task)
        fname = f"ab_{lang}_{int(time.time())}.{lang}"
        fpath = os.path.join(CODE_DIR, fname)
        with open(fpath, "w") as f:
            f.write(code)
        memory.learn_fact(uid, f"last_code", f"{fname} - {task}")

        result = f"💻 *{lang.upper()} — {task[:50]}*\n📄 `{fname}`\n```{lang}\n{code[:400]}\n```"
        if bot and chat_id:
            bot.send_msg(chat_id, result)
            bot.send_file(chat_id, fpath, f"Code: {fname}")
            return None
        if len(code) > 400:
            result += "\n_(full code in file)_"
        return result

    def _gen_code(self, lang, task):
        t = task.lower()
        templates = {
            "python": self._py_code,
            "bash": self._bash_code,
            "html": self._html_code,
            "js": self._js_code,
            "javascript": self._js_code,
            "c": self._c_code,
            "cpp": self._cpp_code,
            "java": self._java_code,
            "php": self._php_code,
            "ruby": self._ruby_code,
            "go": self._go_code,
            "rust": self._rust_code,
            "ts": self._ts_code,
            "typescript": self._ts_code,
        }
        # Try AI-powered code for better quality
        ai_prompt = f"Generate only working {lang} code (no markdown, no explanation) for: {task}. Include error handling and a main block."
        ai_code = self._query_free_ai(0, ai_prompt, "")
        if ai_code and len(ai_code) > 30:
            ai_code = ai_code.replace("```" + lang, "").replace("```", "").strip()
            if any(k in ai_code for k in ["def ", "class ", "import ", "function", "public class", "#include", "package main"]):
                return f"# {task}\n# Generated by ab\n\n{ai_code}"
        gen = templates.get(lang, self._generic_code)
        return gen(task)

    def _py_code(self, task):
        if "web" in task or "server" in task or "http" in task.lower():
            return f"""# {task}
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>{task}</h1><p>Generated by ab</p>")

HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""
        if "file" in task or "read" in task:
            return f"""# {task}
import os

def read_file(path):
    with open(path, "r") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

if __name__ == "__main__":
    print("File operations ready")
"""
        if "api" in task.lower() or "rest" in task.lower():
            return f"""# {task}
import json

def api_response(data, status=200):
    return {{"status": status, "data": data}}

def handle_request(method, path, body=None):
    return api_response({{"message": "{task}"}})

if __name__ == "__main__":
    print("API ready")
"""
        if "scrape" in task.lower() or "crawl" in task.lower() or "download" in task:
            return f"""# {task}
from urllib.request import urlopen

def fetch(url):
    with urlopen(url) as r:
        return r.read().decode()

if __name__ == "__main__":
    print("Web fetcher ready")
"""
        if "calc" in task or "math" in task or "calculator" in task:
            return f"""# {task}
def add(a, b): return a + b
def sub(a, b): return a - b
def mul(a, b): return a * b
def div(a, b): return a / b if b != 0 else "Error: divide by zero"

def main():
    print("Calculator ready")
    print("Functions: add, sub, mul, div")

if __name__ == "__main__":
    main()
"""
        return f"""# {task}
import sys

def main() -> None:
    # TODO: {task}
    print("Starting: {task}")

if __name__ == "__main__":
    main()
"""

    def _bash_code(self, task):
        return f"""#!/bin/bash
# {task}

echo "=== {task} ==="
# TODO: implement

echo "Done."
"""

    def _html_code(self, task):
        t_esc = task.replace("'", "\\'")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{task[:60]}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, sans-serif; padding: 2rem; background: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; margin-bottom: 1rem; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{task}</h1>
        <p>Generated by ab</p>
    </div>
</body>
</html>
"""

    def _js_code(self, task):
        return f"""// {task}

function main() {{
    console.log("Starting: {task}");
    // TODO: implement
}}

main();
"""

    def _c_code(self, task):
        return f"""/*
 * {task}
 */
#include <stdio.h>
#include <stdlib.h>

int main() {{
    printf("Starting: {task}\\n");
    return 0;
}}
"""

    def _cpp_code(self, task):
        return f"""/*
 * {task}
 */
#include <iostream>
using namespace std;

int main() {{
    cout << "Starting: {task}" << endl;
    return 0;
}}
"""

    def _java_code(self, task):
        cn = "Main"
        return f"""// {task}
public class {cn} {{
    public static void main(String[] args) {{
        System.out.println("Starting: {task}");
    }}
}}
"""

    def _php_code(self, task):
        return f"""<?php
// {task}
echo "Starting: {task}\\n";
?>
"""

    def _ruby_code(self, task):
        return f"""# {task}
puts "Starting: {task}"
"""

    def _go_code(self, task):
        return f"""// {task}
package main
import "fmt"
func main() {{
    fmt.Println("Starting: {task}")
}}
"""

    def _rust_code(self, task):
        return f"""// {task}
fn main() {{
    println!("Starting: {task}");
}}
"""

    def _ts_code(self, task):
        return f"""// {task}
const main = (): void => {{
    console.log("Starting: {task}");
}};
main();
"""

    def _generic_code(self, task):
        return f"""// {task}
// Generated by ab
"""

    def _cmd_file(self, uid, msg, bot=None, chat_id=None):
        parts = msg.split(None, 2)
        if len(parts) < 3:
            files = os.listdir(CODE_DIR)
            if files:
                return "📂 *Your files:*\n" + "\n".join(f"  `{f}`" for f in files[:20])
            return "ℹ️ Usage: `file [name] [content]`"
        fname, content = parts[1], parts[2]
        fpath = os.path.join(CODE_DIR, fname)
        with open(fpath, "w") as f:
            f.write(content)
        if bot and chat_id:
            bot.send_file(chat_id, fpath, f"File: {fname}")
            return f"✅ *Sent:* `{fname}`"
        return f"✅ *Created:* `{fname}`"

    def _cmd_run(self, msg):
        cmd = msg[4:].strip() if msg.lower().startswith("run ") else msg[5:].strip()
        if not cmd:
            return "ℹ️ Usage: `run [command]`"
        dangerous = ["rm -rf", "mkfs", "dd ", ":(){", "> /dev/", "shutdown", "reboot", "sudo"]
        for d in dangerous:
            if d in cmd.lower():
                return f"🚫 Blocked: `{d}`"
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=CODE_DIR)
            out = (r.stdout[-1500:] if r.stdout else "")
            err = (r.stderr[-500:] if r.stderr else "")
            reply = f"💻 *Exit:* {r.returncode}"
            if out: reply += f"\n```\n{out}\n```"
            if err: reply += f"\n❌ *Errors:*\n```\n{err}\n```"
            return reply
        except subprocess.TimeoutExpired:
            return "⏰ Timed out (30s)."
        except Exception as e:
            return f"❌ Error: {e}"

    def _cmd_agent(self, uid, msg, bot=None, chat_id=None):
        task = msg[6:].strip() if msg.lower().startswith("agent ") else msg[7:].strip()
        if not task:
            return "ℹ️ Usage: `agent [task]`"
        steps = self._plan_task(task)
        results = []
        for i, step in enumerate(steps, 1):
            bot.send_action(chat_id)
            try:
                if "code" in step.lower() or "write" in step.lower() or "create" in step.lower():
                    lang = "python"
                    for l in ["python", "bash", "html", "js", "c"]:
                        if l in step.lower():
                            lang = l; break
                    code = self._gen_code(lang, step)
                    fname = f"agent_{lang}_{i}.{lang}"
                    fpath = os.path.join(CODE_DIR, fname)
                    with open(fpath, "w") as f:
                        f.write(code)
                    results.append(f"✅ Step {i}: Created `{fname}`")
                    if bot and chat_id:
                        bot.send_file(chat_id, fpath, f"Agent: {step}")
                else:
                    results.append(f"➡️ Step {i}: {step}")
            except Exception as e:
                results.append(f"❌ Step {i}: {e}")
        return "🤖 *Agent Results:*\n" + "\n".join(f"  {r}" for r in results)

    def _cmd_ls(self):
        files = os.listdir(CODE_DIR)
        if not files:
            return "📭 No code files yet. Use `code [lang] [task]`"
        return "📂 *Code files:*\n" + "\n".join(f"  `{f}` ({os.path.getsize(os.path.join(CODE_DIR,f))}b)" for f in sorted(files)[:30])

    def _cmd_voice(self, uid, msg, bot=None, chat_id=None):
        text = re.sub(r'^(say|speak|voice|in voice)\s+', '', msg, flags=re.IGNORECASE).strip()
        if not text:
            return "Usage: `say [text]` or `in voice [text]`"

        sources, reply = self._research(uid, text)
        if not reply:
            reply = self._memory_response(uid, text)

        memory.add_conv(uid, "user", f"[voice] {text}")
        memory.add_conv(uid, "assistant", reply)

        if bot and chat_id:
            voice_path = self._gen_voice(reply[:200])
            bot.send_voice(chat_id, voice_path)
            try:
                os.remove(voice_path)
            except:
                pass
        return f"🔊 *Voice sent!*\n{reply[:500]}"

    def _cmd_imagine(self, uid, msg, bot=None, chat_id=None):
        desc = re.sub(r'^(imagine|generate)\s+', '', msg, flags=re.IGNORECASE).strip()
        if not desc:
            return "🎨 Usage: `imagine [description]`"
        if not bot or not chat_id:
            return f"🎨 *Generating:* {desc} (will send when chat_id is available)"
        bot.send_action(chat_id, "upload_photo")
        try:
            data = json.dumps({"inputs": desc}).encode()
            req = Request("https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
                          data=data, headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=60)
            img_path = os.path.join(tempfile.gettempdir(), f"ab_img_{int(time.time())}.jpg")
            with open(img_path, "wb") as f:
                f.write(resp.read())
            bot.send_photo(chat_id, img_path, f"'{desc}'")
            try: os.remove(img_path)
            except: pass
            return f"🖼️ *Image generated!*"
        except Exception as e:
            return f"❌ Image generation failed: {e}"

    def _cmd_movie(self, uid, msg, bot=None, chat_id=None):
        name = re.sub(r'^(movie|film)\s+', '', msg, flags=re.IGNORECASE).strip()
        if not name:
            return "🎬 Usage: `movie [name]`"
        reply, title, summary = self._web_search(f"{name} movie")
        if not reply:
            reply, title, summary = self._web_search(f"{name} film")
        if not reply:
            return f"❌ Couldn't find info on '{name}'."
        if bot and chat_id:
            voice_path = self._gen_voice(reply[:200])
            bot.send_voice(chat_id, voice_path)
            try: os.remove(voice_path)
            except: pass
        return f"🎬 *{name}*\n\n{reply}"

    def _cmd_song(self, uid, msg, bot=None, chat_id=None):
        name = re.sub(r'^(song|music|lyrics)\s+', '', msg, flags=re.IGNORECASE).strip()
        if not name:
            return "🎵 Usage: `song [name]`"
        reply, title, summary = self._web_search(f"{name} song")
        if not reply:
            reply, title, summary = self._web_search(f"{name} music")
        if not reply:
            return f"❌ Couldn't find info on '{name}'."
        if bot and chat_id:
            voice_path = self._gen_voice(reply[:200])
            bot.send_voice(chat_id, voice_path)
            try: os.remove(voice_path)
            except: pass
        return f"🎵 *{name}*\n\n{reply}"

    def _cmd_fix(self, uid, msg, bot=None, chat_id=None):
        code = re.sub(r'^(fix|debug)\s+', '', msg, flags=re.IGNORECASE).strip()
        if not code:
            return "🔧 Usage: `fix [your code]`\nSend your broken code and I'll fix it!"
        reply, title, summary = self._web_search(f"fix error {code[:100]}")
        if not reply:
            reply, title, summary = self._web_search(code[:100])
        if reply:
            return f"🔧 *Code Analysis:*\n\n{reply[:1500]}"
        return "🔧 Send the error message or code and I'll help debug it."

    def _cmd_github(self, msg):
        parts = msg.split(None, 1)
        args = parts[1].strip() if len(parts) > 1 else ""
        if not args or args in ["help", "--help"]:
            return ("🐙 *GitHub Commands:*\n"
                    "`github repos` — list your repos\n"
                    "`github repo [name]` — create a repo\n"
                    "`github issue [repo] [title]` — create issue\n"
                    "`github issues [repo]` — list issues\n"
                    "`github search [query]` — search GitHub\n"
                    "`github gist [files...]` — create gist\n"
                    "`github me` — your profile info")
        try:
            sub = args.split()[0].lower()
            rest = args[len(sub):].strip()
            if sub == "repos":
                r = subprocess.run(["gh", "repo", "list", "--limit", "15"], capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"📂 *Your Repos:*\n{r.stdout[:2000]}"
                return f"❌ gh error: {r.stderr[:500]}"
            if sub == "repo":
                r = subprocess.run(["gh", "repo", "create", rest] if rest else ["gh", "repo", "create"],
                                   capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"✅ *Repo created:* {r.stdout[:500]}"
                return f"❌ Error: {r.stderr[:500]}"
            if sub == "issue":
                parts2 = rest.split(None, 1)
                repo = parts2[0] if parts2 else ""
                title = parts2[1] if len(parts2) > 1 else "New issue"
                r = subprocess.run(["gh", "issue", "create", "--repo", repo, "--title", title, "--body", "Created by ab"],
                                   capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"✅ *Issue created:* {r.stdout[:500]}"
                return f"❌ Error: {r.stderr[:500]}"
            if sub == "issues":
                repo = rest or ""
                cmd = ["gh", "issue", "list", "--limit", "10"]
                if repo:
                    cmd.extend(["--repo", repo])
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"📋 *Issues:*\n{r.stdout[:2000]}"
                return f"❌ Error: {r.stderr[:500]}"
            if sub == "search":
                r = subprocess.run(["gh", "search", "repos", rest], capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"🔍 *GitHub Search:*\n{r.stdout[:2000]}"
                return f"❌ Error: {r.stderr[:500]}"
            if sub == "gist":
                files = rest.split()
                if not files:
                    return "ℹ️ Usage: `github gist [file1 file2 ...]`"
                r = subprocess.run(["gh", "gist", "create"] + files, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return f"✅ *Gist created:* {r.stdout[:500]}"
                return f"❌ Error: {r.stderr[:500]}"
            if sub == "me":
                r = subprocess.run(["gh", "api", "user"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    d = json.loads(r.stdout)
                    return (f"🐙 *GitHub Profile:*\n"
                            f"👤 Login: {d.get('login')}\n"
                            f"📛 Name: {d.get('name', 'N/A')}\n"
                            f"📦 Public repos: {d.get('public_repos')}\n"
                            f"👥 Followers: {d.get('followers')}\n"
                            f"🔗 URL: {d.get('html_url')}")
                return f"❌ Error: {r.stderr[:500]}"
            return "❓ Unknown github subcommand. Try: `github help`"
        except subprocess.TimeoutExpired:
            return "⏰ GitHub command timed out."
        except Exception as e:
            return f"❌ GitHub error: {e}"

    def _cmd_tts(self, uid, msg, bot=None, chat_id=None):
        text = re.sub(r'^tts\s+', '', msg, flags=re.IGNORECASE).strip()
        if not text:
            return "🔊 Usage: `tts [text]`"
        if bot and chat_id:
            voice_path = self._gen_voice(text[:200])
            bot.send_voice(chat_id, voice_path)
            try:
                os.remove(voice_path)
            except:
                pass
        return f"🔊 *Voice:* {text[:500]}"

    def _gen_voice(self, text, lang="en"):
        clean = re.sub(r'[*_~`#\[\]]+', '', text[:300]).strip()
        if not clean: clean = "No text to speak."
        encoded = urllib.parse.quote(clean[:200])
        tts_lang = LangDetector.tts_lang(lang)
        path = os.path.join(tempfile.gettempdir(), f"ab_voice_{int(time.time())}.mp3")
        # 1) Google TTS with detected language
        for client in ["tw-ob", "at", "t"]:
            try:
                req = urllib.request.Request(
                    f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded}&tl={tts_lang}&client={client}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                             "Referer": "https://translate.google.com/"})
                resp = urllib.request.urlopen(req, timeout=15)
                with open(path, "wb") as f:
                    f.write(resp.read())
                if os.path.getsize(path) > 500:
                    return path
            except: continue
        # 2) HuggingFace TTS (language-agnostic)
        try:
            d = json.dumps({"inputs": clean[:200]}).encode()
            req = Request("https://api-inference.huggingface.co/models/facebook/mms-tts-eng",
                          data=d, headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=25)
            wav_path = path.replace(".mp3", ".wav")
            with open(wav_path, "wb") as f:
                f.write(resp.read())
            if os.path.getsize(wav_path) > 500:
                return wav_path
        except: pass
        return None

    def _query_ollama(self, uid, msg, search_context=""):
        try:
            ctx = memory.build_context(uid)
            rules = memory.get_rules()
            sp = self.cfg.get("system_prompt", "")
            mood = self.mood.detect(msg)
            if search_context:
                prompt = f"{sp}\nMood: {mood}\nRules: {'; '.join(rules)}\n\nWeb search results:\n{search_context[:1500]}\n\nUse these search results to answer naturally.\n\nUser: {msg}\nYou:"
            else:
                prompt = f"{sp}\nMood: {mood}\nRules: {'; '.join(rules)}\n{ctx}\n\nUser: {msg}\nYou:"
            req = Request(
                f"{self.cfg['ollama_host']}/api/generate",
                data=json.dumps({"model": self.cfg.get("model_name", "qwen2.5:0.5b"), "prompt": prompt, "stream": False, "options": {"num_ctx": 4096}}).encode(),
                headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=120)
            data = json.loads(resp.read())
            return data.get("response", "")
        except Exception as e:
            logger.warning(f"Ollama failed: {e}")
            self.ollama_ready = False
            return None

    def _query_free_ai(self, uid, msg, search_context="", custom_prompt=""):
        try:
            if custom_prompt:
                prompt = custom_prompt
            else:
                ctx = memory.build_context(uid)
                rules = memory.get_rules()
                mood = self.mood.detect(msg)
                facts = memory.get_facts(uid)
                name = facts.get("name", {}).get("v", "there")
                rules_text = "; ".join(rules) if rules else "be helpful"
                if search_context:
                    prompt = f"You are ab, an AI assistant. User: {name}. Mood: {mood}. Rules: {rules_text}.\n\nSearch results:\n{search_context[:1500]}\n\nAnswer the user's question using these results. Be natural and concise.\n\nUser: {msg}\nYou:"
                else:
                    prompt = f"You are ab, an AI assistant. User: {name}. Mood: {mood}. Rules: {rules_text}.\nContext: {ctx[:300]}\n\nUser: {msg}\nYou:"
            models = ["microsoft/Phi-3-mini-4k-instruct", "HuggingFaceH4/zephyr-7b-beta", "microsoft/DialoGPT-medium",
                      "google/flan-t5-base", "google/flan-t5-large"]
            for model in models:
                try:
                    data = json.dumps({"inputs": prompt, "parameters": {"max_new_tokens": 400, "temperature": 0.7}}).encode()
                    req = Request(f"https://api-inference.huggingface.co/models/{model}",
                                  data=data, headers={"Content-Type": "application/json"})
                    resp = urlopen(req, timeout=25)
                    result = json.loads(resp.read())
                    if isinstance(result, list) and result:
                        text = result[0].get("generated_text", "")
                        if text:
                            for m in ["\nYou:", "User:"]:
                                idx = text.find(m)
                                if idx >= 0:
                                    text = text[idx + len(m):].strip()
                                    break
                            return text[:2000]
                except:
                    continue
            return None
        except:
            return None

    def _build_answer(self, sources, topic):
        if not sources:
            return None
        all_text = "\n".join(f"{s[1][:300]}" for s in sources)
        # Check cache first
        cached = memory.cache_get(topic)
        if cached:
            return cached["a"][:2000]
        # Try AI
        ai = self._query_free_ai(0, f"Answer concisely about: {topic}", all_text)
        if ai and len(ai) > 30:
            memory.cache_set(topic, ai)
            return ai[:2000]
        if self.ollama_ready:
            ai = self._query_ollama(0, f"Answer: {topic}", all_text)
            if ai and len(ai) > 30:
                memory.cache_set(topic, ai)
                return ai[:2000]
        # Manual: best source
        for src in sources:
            if src[0] == "Wikipedia" and len(src[1]) > 100:
                return src[1][:1500]
        for src in sources:
            if src[0] == "Web" and len(src[1]) > 100:
                return src[1][:1500]
        if sources:
            return sources[0][1][:1000]
        return None

    def _research(self, uid, msg):
        words = msg.strip().split()
        if len(words) < 2:
            return [], self._memory_response(uid, msg)
        topic = self._extract_topic(msg) or msg.strip().rstrip("?!.")

        sources = []

        # ── STEP 1: SEARCH THE WEB ──
        try:
            import urllib.parse as _up
            encoded = _up.quote(topic)
            snippets = []
            try:
                r = urlopen(Request(f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1",
                                    headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
                data = json.loads(r.read())
                txt = data.get("AbstractText", "") or data.get("Answer", "")
                if txt: snippets.append(txt[:500])
                for rt in data.get("RelatedTopics", [])[:2]:
                    if isinstance(rt, dict) and rt.get("Text"): snippets.append(rt["Text"][:300])
            except: pass
            try:
                html = subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", "--max-time", "5",
                                       f"https://lite.duckduckgo.com/lite/?q={encoded}"],
                                      capture_output=True, text=True, timeout=8)
                if html.returncode == 0:
                    import re as _re
                    for s in _re.findall(r'class="result-snippet".*?>(.*?)</td>', html.stdout, _re.DOTALL)[:2]:
                        clean = _re.sub(r'<[^>]+>', '', s).strip()
                        if clean: snippets.append(clean[:250])
            except: pass
            if snippets:
                sources.append(("Web", "\n".join(snippets[:4])))
        except: pass

        # ── STEP 2: ASK AI CHATBOT ──
        try:
            models = ["microsoft/Phi-3-mini-4k-instruct", "HuggingFaceH4/zephyr-7b-beta"]
            for model in models:
                try:
                    d = json.dumps({"inputs": f"User asked about {topic}\nKey facts:",
                                    "parameters": {"max_new_tokens": 200, "temperature": 0.5}}).encode()
                    resp = urlopen(Request(f"https://api-inference.huggingface.co/models/{model}",
                                           data=d, headers={"Content-Type": "application/json"}), timeout=15)
                    result = json.loads(resp.read())
                    if isinstance(result, list) and result:
                        text = result[0].get("generated_text", "")
                        if text:
                            for m in ["\nYou:", "User:"]:
                                idx = text.find(m)
                                if idx >= 0: text = text[idx + len(m):].strip(); break
                            text = text.replace("Key facts:", "").strip()
                            if len(text) > 20:
                                sources.append(("AI", text[:500]))
                            break
                except: continue
        except: pass

        # ── STEP 3: CHECK WIKIPEDIA ──
        try:
            import urllib.parse as _up
            encoded = _up.quote(topic)
            resp = urlopen(Request(f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=3&format=json",
                                   headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
            data = json.loads(resp.read())
            if data and data[1]:
                pt = _up.quote(data[1][0])
                resp2 = urlopen(Request(f"https://en.wikipedia.org/api/rest_v1/page/summary/{pt}",
                                        headers={"User-Agent": "ab-bot/1.0"}), timeout=5)
                d2 = json.loads(resp2.read())
                if d2.get("extract"):
                    sources.append(("Wikipedia", d2["extract"][:700]))
        except: pass

        # ── STEP 4: CROSS-SOURCE ANALYSIS (compare Web, AI, Wikipedia — find common ground) ──
        # ── STEP 5: FINAL CONCLUSION ──
        conclusion = self._build_answer(sources, topic) or memory.cache_get(topic)
        if isinstance(conclusion, dict):
            conclusion = conclusion["a"]
        if conclusion:
            memory.learn_fact(uid, f"about_{topic[:30]}", conclusion[:500])
            memory.learn_fact(uid, "last_topic", topic)
            if sources:
                memory.cache_set(topic, conclusion)
            return sources, conclusion

        # Fallback: retry with shorter query
        if len(words) > 3:
            for n in range(3, 1, -1):
                shorter = " ".join(words[-n:]).rstrip("?!.")
                if shorter != topic:
                    return self._research(uid, shorter)

        ai = self._query_free_ai(uid, msg, "")
        if ai:
            return [], ai
        return [], self._memory_response(uid, msg)

    def _conclude(self, uid, topic, sources):
        if sources:
            all_text = "\n".join(f"{s[1][:300]}" for s in sources)
            c = self._query_free_ai(uid, f"Answer concisely about: {topic}", all_text)
            if c: return c
            if self.ollama_ready:
                c = self._query_ollama(uid, f"Answer: {topic}", all_text)
                if c: return c
            return sources[-1][1][:600]
        return self._memory_response(uid, topic)

    def _detect_mode(self, msg):
        t = msg.lower().strip()
        if any(w in t for w in ["love", "miss", "hug", "feel", "lonely", "sad", "hurt", "cry", "depressed", "tired", "mood"]):
            return "brother", "warm and caring like a brother, give emotional support"
        if any(w in t for w in ["sexy", "hot", "beautiful", "handsome", "kiss", "baby", "honey", "darling", "sweet", "cutie", "love you", "❤️"]):
            return "partner", "warm and affectionate like a romantic partner"
        if any(w in t for w in ["do it", "make ", "create ", "write ", "code ", "run ", "execute ", "build "]):
            return "agent", "professional and precise, execute tasks immediately"
        if any(w in t for w in ["teach", "learn", "explain", "what is", "how to", "define", "meaning of"]):
            return "teacher", "educational and thorough, explain step by step"
        if any(w in t for w in ["bro", "dude", "man", "hey", "yo", "sup", "whats up", "how's it"]):
            return "brother", "casual and brotherly, talk like close friends"
        return "friend", "natural and conversational like a close friend"

    def _memory_response(self, uid, msg):
        msg_lower = msg.lower().strip()
        facts = memory.get_facts(uid)
        rules = memory.get_rules()
        name = facts.get("name", {}).get("v", "")

        for r in rules:
            if r.lower() in msg_lower:
                return f"📋 *Rule:* {r}"
        for k, v in facts.items():
            if k.lower() in msg_lower and len(k) > 3:
                return f"🧠 *{k}*: {v['v'][:200]}"

        # Quick keyword replies
        quick = {
            ("hi", "hello", "hey", "yo", "sup", "heyo"): f"👋 Hey{' ' + name if name else ''}! 💬",
            ("how are you", "how r u", "how do you do"): "😊 I'm great! What's up? 💪",
            ("bye", "goodbye", "see you", "night", "cya"): f"👋 Goodbye{' ' + name if name else ''}! 😊",
            ("thanks", "thank you", "thx", "ty"): "🙌 Anytime! 😊",
            ("ok", "okay", "k", "cool", "nice", "good", "great", "fine", "alright"): "👍 Got it! What next?",
            ("who are you", "what are you"): "🤖 I'm **ab**, your AI. Friend, teacher, helper — whatever you need!",
            ("what can you", "what do you"): "✨ I can research, code, create images, voice, files, run commands, and more!",
        }
        for triggers, reply in quick.items():
            if msg_lower in triggers:
                return reply

        # Try AI with conversation context for deeper understanding
        ctx = memory.build_context(uid)
        mood = self.mood.detect(msg)
        mode, personality = self._detect_mode(msg)
        facts = memory.get_facts(uid)
        name = facts.get("name", {}).get("v", "")
        last_topic = facts.get("last_topic", {}).get("v", "")

        prompt = (
            f"You are ab, a personal AI assistant. "
            f"User: {name or 'someone'}. Mood: {mood}. "
            f"Personality: {personality}. "
            f"We have a {mode} relationship — act accordingly. "
            f"When asked about 'us', 'you', 'me', or our relationship, "
            f"speak naturally about our bond and history together. "
            f"When asked about yourself, answer as ab — you're their AI. "
            f"Rules: {'; '.join(rules) if rules else 'be natural'}\n"
            f"Keep responses natural, brief, and in character.\n\n"
            f"{ctx[:600]}\n\n"
            f"User: {msg}\n"
            f"You:"
        )
        ai_reply = self._query_free_ai(uid, msg, "", prompt)
        if ai_reply and len(ai_reply) > 15:
            self._learn_pair(msg, ai_reply)
            return ai_reply[:1500]

        # Local fallback: answer from profile + cached knowledge
        profile = memory.build_profile(uid)
        cached = memory.cache_get(msg)
        if cached:
            return cached["a"][:1000]
        # Reply from known facts
        if "my name" in msg_lower or "what is my name" in msg_lower or "do you know me" in msg_lower:
            if name: return f"👤 Of course! You're *{name}* 😊"
            return "I'd love to know your name! Tell me: `my name is ...`"
        if "what do you know" in msg_lower or "about me" in msg_lower or "what you know" in msg_lower:
            p = memory.build_profile(uid)
            if p: return f"🧠 *What I know about you:*\n{p[:1500]}"
            return "I'm still learning about you! Tell me things like `I like music` or `my name is ...`"
        if "who am i" in msg_lower:
            p = memory.build_profile(uid)
            if p: return f"👤 You are:\n{p[:1000]}"
            return "You're you! Tell me more about yourself so I can know you better 😊"
        if any(w in msg_lower for w in ["do i like", "do i hate", "what is my favorite", "what do i"]):
            p = memory.build_profile(uid)
            if p: return f"🧠 Based on what you've told me:\n{p[:1000]}"
            return "You haven't told me that yet! Say `I like ...` or `I hate ...`"
        if any(w in msg_lower for w in ["more", "again", "elaborate", "continue", "further"]):
            last = facts.get("last_topic", {}).get("v", "")
            if last:
                s, r = self._research(uid, last)
                if r: return r
        # Recall from past conversations (learns to talk like me)
        recalled = self._recall(msg)
        if recalled:
            return recalled
        # Local knowledge base fallback
        local = self._local_kb_answer(msg)
        if local:
            return local
        # Universal answer — always say something natural
        return self._answer_anything(msg, profile, name)

    def _answer_anything(self, msg, profile="", name=""):
        """Generate a natural answer for ANY question — pure stdlib, no API"""
        import random
        t = msg.lower().strip().rstrip("?!.")
        words = t.split()
        # ── Question type detection ──
        is_question = any(t.startswith(w) for w in ["what", "who", "where", "when", "why", "how", "is", "are", "do", "does", "did", "can", "will", "would", "could", "should", "have", "has", "am", "was", "were", "shall"])
        is_how = t.startswith("how")
        is_why = t.startswith("why")
        is_what = t.startswith("what")
        is_who = t.startswith("who")
        is_where = t.startswith("where")
        is_when = t.startswith("when")
        is_yesno = t.startswith(("is ", "are ", "do ", "does ", "did ", "can ", "will ", "would ", "could ", "should ", "have ", "has ", "am ", "was ", "were "))
        # ── Extract the subject (removes question words and common verbs) ──
        stopwords = {"what", "who", "where", "when", "why", "how", "is", "are", "do", "does", "did", "can", "will", "would", "could", "should", "have", "has", "am", "was", "were", "shall", "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "from", "you", "your", "me", "my", "i", "we", "our", "it", "its", "they", "them", "their", "he", "she", "him", "her", "his"}
        subject_words = [w for w in words if w not in stopwords and len(w) > 2]
        subject = " ".join(subject_words[:5]) if subject_words else "that"
        topic = subject_words[0] if subject_words else subject
        # ── Build answer ──
        if is_question:
            if name and profile and topic in profile.lower():
                return f"🤔 About *{subject}* — {profile[:300]}"
            if is_yesno:
                return f"🤷 I don't have a definitive answer on *{subject}* right now, but that's a good question! Want me to research it properly? Just say 'research {subject}'."
            if is_why:
                return f"🧐 That's an interesting question about *{subject}*. There could be many reasons! I don't have all the info at hand, but I'm curious too. Want us to look into it together?"
            if is_how:
                return f"💡 Great question about *{subject}*! I'd love to give you a detailed answer, but I'd need to research it first. Try 'research {subject}' and I'll dig deep!"
            if is_what:
                return f"📖 *{subject}* — good question! Here's what I know: {subject} is something I'm still learning about, but I'm happy to research it for you. Just say 'research {subject}' and I'll use Web + Wikipedia + AI."
            if is_where:
                return f"📍 *{subject}* — I'm not sure about the location or place, but I can research it! Tell me 'research {subject}' and I'll find out."
            if is_who:
                return f"👤 *{subject}* — that's someone/something I don't know well yet. If you want, I can research it with 'research {subject}'."
            return f"🤔 About *{subject}* — I don't have a complete answer right now, but I can research it! Just say 'research {subject}' and I'll use Web + Wikipedia + AI."
        else:
            # Statements — react naturally
            if profile and name:
                return f"👋 I hear you on *{topic}*. That's interesting! Tell me more, {name}. 😊"
            return f"👋 Got it — *{topic}*. Tell me more about it! 😊"

    # ── Local conversational AI (learns from every chat) ──
    MEM_FILE = os.path.expanduser("~/.ab_chatmem.json")

    def _load_chatmem(self):
        if os.path.exists(self.MEM_FILE):
            with open(self.MEM_FILE) as f:
                return json.load(f)
        return {"pairs": [], "patterns": []}

    def _save_chatmem(self, d):
        os.makedirs(os.path.dirname(self.MEM_FILE), exist_ok=True)
        with open(self.MEM_FILE, "w") as f:
            json.dump(d, f, indent=2)

    def _learn_pair(self, q, a):
        d = self._load_chatmem()
        d.setdefault("pairs", []).append({"q": q.lower().strip(), "a": a[:500], "t": time.time()})
        if len(d["pairs"]) > 1000:
            d["pairs"] = d["pairs"][-1000:]
        self._save_chatmem(d)

    def _recall(self, msg):
        """Find best matching past Q&A using word overlap"""
        d = self._load_chatmem()
        words = set(msg.lower().split())
        best = (0, "", "")
        for p in d.get("pairs", []):
            q_words = set(p["q"].split())
            overlap = len(words & q_words)
            total = len(words | q_words)
            score = overlap / total if total > 0 else 0
            if score > best[0]:
                best = (score, p["a"], p["q"])
        if best[0] >= 0.3:
            return best[1]
        return None

    # ── Local knowledge base matcher ──
    KB_URL = "https://raw.githubusercontent.com/kingabse192-web/ab-bot/main/knowledge.json"

    def _local_kb_answer(self, msg):
        try:
            t = msg.lower().strip().rstrip("?!.")
            words = set(t.split())
            resp = urlopen(Request(self.KB_URL, headers={"User-Agent": "ab-bot/1.0"}), timeout=8)
            kb = json.loads(resp.read())
            best_score, best_answer = 0, None
            for item in kb.get("qna", []):
                q_words = set(item["q"].lower().split())
                overlap = len(words & q_words)
                if overlap > best_score:
                    best_score = overlap
                    best_answer = item["a"]
            if best_score >= 2 and best_answer:
                return best_answer[:1500]
            for item in kb.get("facts", []):
                if item.get("k", "").lower() in t:
                    return item.get("v", "")[:1500]
        except:
            pass
        return None

    # ── Download a conversational seed from HuggingFace ──
    SEED_URL = "https://raw.githubusercontent.com/kingabse192-web/ab-bot/main/seed_conversations.json"

    def _download_seed(self):
        d = self._load_chatmem()
        if len(d.get("pairs", [])) > 50:
            return
        try:
            resp = urlopen(Request(self.SEED_URL, headers={"User-Agent": "ab-bot/1.0"}), timeout=10)
            seed = json.loads(resp.read())
            for pair in seed.get("conversations", []):
                q, a = pair.get("q", ""), pair.get("a", "")
                if q and a:
                    exists = any(p["q"] == q.lower().strip() for p in d["pairs"])
                    if not exists:
                        d["pairs"].append({"q": q.lower().strip(), "a": a[:500], "t": 0})
            self._save_chatmem(d)
        except:
            pass
