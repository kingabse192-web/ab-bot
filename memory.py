import json, os, time, re, logging

MEM = os.path.expanduser("~/.ab_memory.json")
CACHE = os.path.expanduser("~/.ab_cache.json")
logger = logging.getLogger("ab.memory")

def _load():
    if os.path.exists(MEM):
        with open(MEM) as f:
            return json.load(f)
    return {"users":{}, "convs":{}, "facts":{}, "rules":[], "prefs":{}, "profile":{}}

def _save(d):
    os.makedirs(os.path.dirname(MEM), exist_ok=True)
    with open(MEM, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

def _load_cache():
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    return {}

def _save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(c, f, indent=2)

def add_conv(uid, role, text):
    d = _load(); u = str(uid)
    d.setdefault("convs", {}).setdefault(u, [])
    d["convs"][u].append({"role":role, "text":text[:500], "t":time.time()})
    if len(d["convs"][u]) > 500:
        d["convs"][u] = d["convs"][u][-500:]
    if role == "user":
        _auto_extract(uid, text, d)
    _save(d)

def _auto_extract(uid, msg, d):
    u = str(uid)
    d.setdefault("facts", {}).setdefault(u, {})
    d.setdefault("prefs", {}).setdefault(u, {})
    t = msg.lower().strip()
    patterns = [
        (r"my name is (\w+)", "name"), (r"i(?:'m| am) called (\w+)", "name"),
        (r"call me (\w+)", "name"), (r"i(?:'m| am) (\d+)", "age"),
        (r"i(?:'m| am) (\d+) year", "age"), (r"(\d+) years old", "age"),
        (r"i live in (.+)", "location"), (r"i(?:'m| am) from (.+)", "location"),
        (r"i (?:like|love) (.+)", "likes"), (r"i enjoy (.+)", "likes"),
        (r"i (?:hate|dislike|don't like|cant stand) (.+)", "dislikes"),
        (r"i work as (.+)", "job"), (r"i(?:'m| am) a (.+)", "job"),
        (r"i (?:study|learn) (.+)", "study"), (r"i(?:'m| am) studying (.+)", "study"),
        (r"my (?:favorite|fav) (.+) is (.+)", "fav"), (r"i want (.+)", "wants"),
        (r"i need (.+)", "needs"), (r"i (?:have|got) a (.+)", "has"),
        (r"i (?:speak|talk) (.+)", "language"),
        (r"i(?:'m| am) (?:a |an )?(male|female|guy|girl|man|woman|boy)", "gender"),
    ]
    for pat, cat in patterns:
        m = re.search(pat, t)
        if m:
            if cat == "fav":
                d["prefs"][u].setdefault(f"favorite_{m.group(1)}", [])
                if m.group(2) not in d["prefs"][u][f"favorite_{m.group(1)}"]:
                    d["prefs"][u][f"favorite_{m.group(1)}"].append(m.group(2))
            else:
                d["facts"][u][cat] = {"v": m.group(1), "t": time.time()}

def get_history(uid, limit=15):
    d = _load(); u = str(uid)
    return d.get("convs", {}).get(u, [])[-limit:]

def get_all_history(uid):
    d = _load(); u = str(uid)
    return d.get("convs", {}).get(u, [])

def learn_fact(uid, k, v):
    d = _load(); u = str(uid)
    d.setdefault("facts", {}).setdefault(u, {})[k.lower()] = {"v":v, "t":time.time()}
    _save(d)

def forget_fact(uid, k):
    d = _load(); u = str(uid)
    k = k.lower()
    if k in d.get("facts", {}).get(u, {}):
        del d["facts"][u][k]; _save(d); return True
    return False

def get_facts(uid):
    d = _load(); u = str(uid)
    return d.get("facts", {}).get(u, {})

def add_rule(text):
    d = _load()
    if text not in d.setdefault("rules", []):
        d["rules"].append(text); _save(d); return True
    return False

def remove_rule(text):
    d = _load()
    for r in d.get("rules", []):
        if text in r: d["rules"].remove(r); _save(d); return True
    return False

def get_rules():
    return _load().get("rules", [])

def learn_pref(uid, cat, val):
    d = _load(); u = str(uid)
    d.setdefault("prefs", {}).setdefault(u, {}).setdefault(cat, [])
    if val not in d["prefs"][u][cat]: d["prefs"][u][cat].append(val); _save(d)

def get_prefs(uid):
    d = _load(); u = str(uid)
    return d.get("prefs", {}).get(u, {})

def cache_get(q):
    c = _load_cache()
    return c.get(q.lower().strip())

def cache_set(q, a):
    c = _load_cache(); k = q.lower().strip()
    c[k] = {"a": a[:2000], "t": time.time()}
    if len(c) > 500:
        old = sorted(c.keys(), key=lambda x: c[x]["t"])[:100]
        for o in old: del c[o]
    _save_cache(c)

def build_profile(uid):
    d = _load(); u = str(uid)
    facts = d.get("facts", {}).get(u, {})
    prefs = d.get("prefs", {}).get(u, {})
    lines = []
    if facts:
        lines.append("USER PROFILE:")
        for k, v in facts.items():
            lines.append(f"  {k}: {v['v']}")
    if prefs:
        lines.append("PREFERENCES:")
        for cat, vals in prefs.items():
            lines.append(f"  {cat}: {', '.join(vals)}")
    return "\n".join(lines)

def build_context(uid, include_history=True):
    facts = get_facts(uid)
    prefs = get_prefs(uid)
    rules = get_rules()
    lines = []
    if rules:
        lines.append("RULES: " + "; ".join(rules))
    if facts:
        lines.append("ABOUT USER: " + "; ".join(f"{k}={v['v']}" for k,v in facts.items()))
    if prefs:
        for cat, vals in prefs.items():
            lines.append(f"  {cat}: {', '.join(vals[:3])}")
    if include_history:
        hist = get_history(uid, 10)
        if hist:
            lines.append("RECENT:")
            for h in hist[-6:]:
                lines.append(f"  {'U' if h['role']=='user' else 'A'}: {h['text'][:150]}")
    return "\n".join(lines)
