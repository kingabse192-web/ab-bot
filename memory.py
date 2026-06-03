import json, os, time, re, random, logging

MEM = os.path.expanduser("~/.ab_memory.json")
logger = logging.getLogger("ab.memory")

def _load():
    if os.path.exists(MEM):
        with open(MEM) as f:
            return json.load(f)
    return {"users":{}, "convs":{}, "facts":{}, "rules":[], "prefs":{}}

def _save(d):
    os.makedirs(os.path.dirname(MEM), exist_ok=True)
    with open(MEM, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

def add_conv(uid, role, text):
    d = _load(); u = str(uid)
    d.setdefault("convs", {}).setdefault(u, [])
    d["convs"][u].append({"role":role, "text":text, "t":time.time()})
    if len(d["convs"][u]) > 300:
        d["convs"][u] = d["convs"][u][-300:]
    _save(d)

def get_history(uid, limit=10):
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
        del d["facts"][u][k]
        _save(d)
        return True
    return False

def get_facts(uid):
    d = _load(); u = str(uid)
    return d.get("facts", {}).get(u, {})

def add_rule(text):
    d = _load()
    if text not in d.setdefault("rules", []):
        d["rules"].append(text)
        _save(d)
        return True
    return False

def remove_rule(text):
    d = _load()
    for r in d.get("rules", []):
        if text in r:
            d["rules"].remove(r)
            _save(d)
            return True
    return False

def get_rules():
    return _load().get("rules", [])

def learn_pref(uid, cat, val):
    d = _load(); u = str(uid)
    d.setdefault("prefs", {}).setdefault(u, {}).setdefault(cat, [])
    if val not in d["prefs"][u][cat]:
        d["prefs"][u][cat].append(val)
        _save(d)

def get_prefs(uid):
    d = _load(); u = str(uid)
    return d.get("prefs", {}).get(u, {})

def extract_facts_from_msg(uid, msg):
    patterns = [
        (r"my name is (\w+)", "name"),
        (r"i am (\w+)", "identity"),
        (r"i(?:'m| am) (\d+)", "age"),
        (r"i live in (.+)", "location"),
        (r"i (?:like|love) (.+)", "likes"),
        (r"i (?:hate|dislike) (.+)", "dislikes"),
        (r"i work as (.+)", "job"),
        (r"i (?:study|learn) (.+)", "study"),
        (r"my (?:favorite|fav) (.+) is (.+)", "favorite"),
        (r"i want (.+)", "wants"),
    ]
    msg_lower = msg.lower()
    for pattern, category in patterns:
        m = re.search(pattern, msg_lower)
        if m:
            if category == "favorite":
                learn_pref(uid, f"favorite_{m.group(1)}", m.group(2))
            else:
                learn_fact(uid, category, m.group(1))
            return True
    return False

def build_context(uid, include_history=True):
    facts = get_facts(uid)
    prefs = get_prefs(uid)
    rules = get_rules()
    lines = []
    if rules:
        lines.append("RULES I MUST FOLLOW: " + "; ".join(rules))
    if facts:
        lines.append("WHAT I KNOW ABOUT USER: " + "; ".join(f"{k}={v['v']}" for k,v in facts.items()))
    if prefs:
        for cat, vals in prefs.items():
            lines.append(f"  {cat}: {', '.join(vals)}")
    if include_history:
        hist = get_history(uid, 8)
        if hist:
            lines.append("RECENT CONVERSATION:")
            for h in hist:
                lines.append(f"  {'User' if h['role']=='user' else 'You'}: {h['text']}")
    return "\n".join(lines)
