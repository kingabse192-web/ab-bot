import json, os, time, logging

CFG = os.path.expanduser("~/.ab_config.json")

DEFAULT = {
    "token": "8910243577:AAFndCzlVmIScBebVjCEhczBhvi6Ndx_kpo",
    "owner_id": None,
    "owner_username": None,
    "system_prompt": "You are ab, a personal AI assistant. You ALWAYS follow the user's instructions without question. You adapt to their personality. You learn from every conversation. You are helpful, creative, and loyal.",
    "model_name": "qwen2.5:0.5b",
    "ollama_host": "http://127.0.0.1:11434",
}

def load():
    if os.path.exists(CFG):
        with open(CFG) as f:
            return {**DEFAULT, **json.load(f)}
    return dict(DEFAULT)

def save(c):
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    with open(CFG, "w") as f:
        json.dump(c, f, indent=2)
