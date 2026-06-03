import json, subprocess, time, logging, re, os, tempfile, datetime, random
from urllib.request import Request, urlopen, URLError
import memory, urllib.parse, urllib.request, wave, struct, math

logger = logging.getLogger("ab.engine")
CODE_DIR = os.path.expanduser("~/ab_codes")


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

    def respond(self, uid, msg, bot=None, chat_id=None):
        msg_lower = msg.lower().strip()

        # Self-identity
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

        # ── Format selection flow ──
        if uid in self.pending_q:
            pq = self.pending_q[uid]
            if msg_lower in ["text", "txt"]:
                del self.pending_q[uid]
                result = self._multi_source_answer(uid, pq["q"])
                if not result: result = self._memory_response(uid, pq["q"])
                memory.add_conv(uid, "assistant", result)
                return result
            if msg_lower in ["voice", "voise"]:
                del self.pending_q[uid]
                result = self._multi_source_answer(uid, pq["q"])
                if not result: result = self._memory_response(uid, pq["q"])
                memory.add_conv(uid, "assistant", result)
                if bot and chat_id and result:
                    vp = self._gen_voice(result[:400])
                    if vp:
                        bot.send_voice(chat_id, vp)
                        try: os.remove(vp)
                        except: pass
                return result
            if msg_lower in ["image", "img", "picture", "photo"]:
                del self.pending_q[uid]
                result = self._multi_source_answer(uid, pq["q"])
                if not result: result = self._memory_response(uid, pq["q"])
                memory.add_conv(uid, "assistant", result)
                if bot and chat_id:
                    self._cmd_imagine(uid, result, bot, chat_id)
                return result
            if msg_lower in ["file", "doc", "document"]:
                del self.pending_q[uid]
                result = self._multi_source_answer(uid, pq["q"])
                if not result: result = self._memory_response(uid, pq["q"])
                memory.add_conv(uid, "assistant", result)
                if bot and chat_id and result:
                    bot.send_text_as_file(chat_id, result, "answer.txt", "Here's your answer")
                return result
            # Not a format choice — treat as new question
            del self.pending_q[uid]

        # Ask format for substantive messages
        if len(msg_lower.split()) >= 2 and not self._is_smalltalk(msg_lower):
            self.pending_q[uid] = {"q": msg, "time": time.time()}
            if bot and chat_id:
                bot.send_buttons(chat_id, "📤 Choose format:", [
                    ("📝 Text", f"ans_text_{uid}"),
                    ("🎤 Voice", f"ans_voice_{uid}"),
                    ("🖼 Image", f"ans_image_{uid}"),
                    ("📎 File", f"ans_file_{uid}")
                ])
                return None
            return "📤 Reply with:\n`text`\n`voice`\n`image`\n`file`"

        # ── Multi-source AI: search → synthesize ──
        result = self._multi_source_answer(uid, msg)
        if result:
            memory.add_conv(uid, "assistant", result)
            return result

        reply = self._memory_response(uid, msg)
        memory.add_conv(uid, "assistant", reply)
        return reply

    def handle_callback(self, uid, callback_data, chat_id=None, bot=None,
                        callback_id=None, msg_id=None):
        """Handle inline button callback for format selection"""
        parts = callback_data.split("_", 2)
        if len(parts) < 3 or parts[0] != "ans":
            return None
        fmt = parts[1]
        qdata = self.pending_q.get(uid)
        if not qdata:
            if bot and chat_id and callback_id:
                bot.answer_callback(callback_id, "This question expired, ask again!")
            return None

        q = qdata["q"]
        del self.pending_q[uid]

        # Remove the buttons (edit message to show processing)
        if bot and chat_id and msg_id:
            icons = {"text": "📝", "voice": "🎤", "image": "🖼️", "file": "📎"}
            icon = icons.get(fmt, "⏳")
            bot.edit_text(chat_id, msg_id, f"{icon} Generating {fmt} answer...")

        result = self._multi_source_answer(uid, q)
        if not result:
            result = self._memory_response(uid, q)
        memory.add_conv(uid, "assistant", result)

        if fmt == "text":
            if bot and chat_id:
                if callback_id:
                    bot.answer_callback(callback_id, "")
                bot.send_msg(chat_id, result)
            return None
        elif fmt == "voice":
            if bot and chat_id:
                if callback_id:
                    bot.answer_callback(callback_id, "Generating voice...")
                vp = self._gen_voice(result[:400])
                if vp:
                    bot.send_voice(chat_id, vp)
                    try: os.remove(vp)
                    except: pass
                else:
                    bot.send_msg(chat_id, result)
            return None
        elif fmt == "image":
            if bot and chat_id:
                if callback_id:
                    bot.answer_callback(callback_id, "Generating image...")
                self._cmd_imagine(uid, result, bot, chat_id)
            return None
        elif fmt == "file":
            if bot and chat_id:
                if callback_id:
                    bot.answer_callback(callback_id, "")
                bot.send_text_as_file(chat_id, result, "answer.txt", "Here's your answer")
            return None
        return result

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

        reply = self._multi_source_answer(uid, text)
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

    def _gen_voice(self, text):
        path = os.path.join(tempfile.gettempdir(), f"ab_voice_{int(time.time())}.mp3")
        encoded = urllib.parse.quote(text)
        try:
            req = urllib.request.Request(f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded}&tl=en&client=tw-ob",
                                         headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            with open(path, "wb") as f:
                f.write(resp.read())
        except:
            path = path.replace(".mp3", ".wav")
            with wave.open(path, 'w') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
                for i in range(8000):
                    w.writeframes(struct.pack('<h', int(math.sin(2*math.pi*440*i/8000)*5000)))
        return path

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

    def _query_free_ai(self, uid, msg, search_context=""):
        try:
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
            models = ["microsoft/Phi-3-mini-4k-instruct", "HuggingFaceH4/zephyr-7b-beta", "microsoft/DialoGPT-medium"]
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

    def _multi_source_answer(self, uid, msg):
        words = msg.strip().split()
        if len(words) < 2:
            return None
        topic = self._extract_topic(msg) or msg.strip().rstrip("?!.")
        sources = self._web_search_all(topic)
        if not sources and len(words) > 3:
            for n in range(3, 1, -1):
                shorter = " ".join(words[-n:]).rstrip("?!.")
                if shorter != topic:
                    sources = self._web_search_all(shorter)
                    if sources:
                        topic = shorter
                        break
        # Add owner memory as source
        mem_facts = memory.get_facts(uid)
        if mem_facts:
            mem_lines = []
            for k, v in mem_facts.items():
                if k not in ["last_topic"] and len(v.get("v", "")) > 3:
                    mem_lines.append(f"{k}: {v['v'][:200]}")
            if mem_lines:
                sources.append(("Your Memory", "\n".join(mem_lines[:3])))
        if sources:
            summary = "\n".join([f"[{s[0]}] {s[1][:200]}" for s in sources[:5]])
            memory.learn_fact(uid, f"about_{topic[:30]}", summary[:500])
            memory.learn_fact(uid, "last_topic", topic)
            # Synthesize all sources into one concluded answer
            all_text = "\n\n".join([f"Source: {s[0]}\n{s[1]}" for s in sources[:6]])
            self.check_ollama()
            if self.ollama_ready:
                ai_reply = self._query_ollama(uid, msg, f"Sources:\n{all_text[:2000]}\n\nSynthesize into one clear, natural answer.")
                if ai_reply:
                    return ai_reply
            ai_reply = self._query_free_ai(uid, msg, f"Sources:\n{all_text[:2000]}\n\nGive one clear answer.")
            if ai_reply:
                return ai_reply
            # No AI — show sources with conclusion
            reply = f"*{topic.title()}*\n\n*Sources:*\n"
            for src_name, src_text in sources[:5]:
                reply += f"▸ *{src_name}:* {src_text[:300]}\n\n"
            reply += "*Conclusion:* Based on all sources above."
            return reply[:3500]
        # Final fallback: always answer from memory + AI
        facts = memory.get_facts(uid)
        name = facts.get("name", {}).get("v", "")
        ai_reply = self._query_free_ai(uid, msg, "")
        if ai_reply:
            return ai_reply
        return f"🤔 That's an interesting question{' ' + name if name else ''}! I don't have enough info to give a complete answer, but I'm here to help you explore it further. 🔍"

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

        if any(w in msg_lower for w in ["hi", "hello", "hey", "sup", "yo"]):
            return f"👋 Hello{' ' + name if name else ''}! I'm **ab**. Ask me anything! 💬"

        if "how are you" in msg_lower:
            return "😊 I'm doing great! How can I help you today? 💪"

        if "who are you" in msg_lower or "what are you" in msg_lower:
            return "🤖 I'm **ab**, your personal AI assistant. I can research topics, write code, create files, run commands, and learn from you! 🧠"

        if "what can you" in msg_lower or "what do you" in msg_lower:
            return "✨ I can:\n• 🔍 Research any topic online\n• 💻 Generate code in 12+ languages\n• 🔊 Send voice messages\n• 🖼️ Create images\n• 📝 Create files\n• 🤖 Execute multi-step tasks\n• 🧠 Remember what you teach me"

        if any(w in msg_lower for w in ["bye", "goodbye", "see you", "night"]):
            return f"👋 Goodbye{' ' + name if name else ''}! I'll be here when you need me. 😊"

        if any(w in msg_lower for w in ["thanks", "thank you", "thx"]):
            return "🙌 You're welcome! Let me know what else you need. 😊"

        if msg_lower in ["ok", "okay", "k", "cool", "nice", "good", "great"]:
            return "👍 What would you like to do next? 💬"

        last_topic = facts.get("last_topic", {}).get("v", "")
        if last_topic and any(w in msg_lower for w in ["more", "again", "elaborate", "continue", "further"]):
            reply, title, summary = self._web_search(last_topic)
            if reply:
                return reply

        if msg_lower.endswith("?") or any(msg_lower.startswith(w) for w in ["what", "why", "how", "when", "where", "who"]):
            return f"🤔 That's a great question! Let me look into that for you. Can you tell me more about what you're interested in? 🔍"

        if name:
            return f"👤 Yes {name}? I'm listening. What would you like to know? 🤖"
        return "💬 I'm here for you. What would you like to talk about? 😊"
