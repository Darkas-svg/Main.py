# Main.py
from flask import Flask, request, Response, jsonify
import os, requests, random, string, json

app = Flask(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")  # MUSS gesetzt sein!
DEFAULT_MODEL  = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Mögliche Alias-Namen aus Janitor normalisieren → OpenRouter-Slug
MODEL_ALIASES = {
    # DeepSeek v3 free Varianten
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3:free":      "deepseek/deepseek-chat:free",
    "deepseek-chat:free":         "deepseek/deepseek-chat:free",
    "deepseek:free":              "deepseek/deepseek-chat:free",
    "deepseekv3:free":            "deepseek/deepseek-chat:free",
    "deepseek-v3:free":           "deepseek/deepseek-chat:free",

    # Ohne „:free“ z. B. von Janitor
    "deepseek/deepseek-chat:free": "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat":      "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":       "deepseek/deepseek-chat:free",
    "deepseek-chat-v3":            "deepseek/deepseek-chat:free",
    "deepseek-chat":               "deepseek/deepseek-chat:free",
    "deepseek":                    "deepseek/deepseek-chat:free",

    # Manchmal kommt nur "gpt-3.5-turbo" o.ä. – mappen wir auch auf DeepSeek-free
    "gpt-3.5-turbo":               "deepseek/deepseek-chat:free",
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# -------- Hilfen --------
def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

def _ok_json(data: dict, code=200):
    return _cors(Response(json.dumps(data), status=code, mimetype="application/json"))

def _rand_token(n=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

def _normalize_payload(data: dict) -> dict:
    """Janitor schickt manchmal prompt/input statt messages – wir formen das passend um."""
    if not data:
        data = {}

    # 1) prompt/input -> messages
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input")
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # 2) messages als Fallback
    if "messages" not in data or not data["messages"]:
        data["messages"] = [{"role": "user", "content": "Hello!"}]

    # 3) Modell normalisieren
    slug_in = str(data.get("model") or DEFAULT_MODEL)
    slug = MODEL_ALIASES.get(slug_in, slug_in)
    data["model"] = slug

    # 4) Standard: kein Stream
    data.setdefault("stream", False)
    return data

# -------- Routen --------

@app.route("/", methods=["GET"])
def root():
    return _ok_json({"ok": True, "endpoint": "chat/completions"})

@app.route("/health", methods=["GET"])
def health():
    return _ok_json({"ok": True, "code": f"ok-{_rand_token()}"} )

# Catch-All: akzeptiere *jeden* Pfad (GET/POST/OPTIONS).
@app.route("/<path:anypath>", methods=["GET", "POST", "OPTIONS"])
def catch_all(anypath: str):
    # Für CORS-Preflight
    if request.method == "OPTIONS":
        return _cors(Response("", status=204))

    # Wenn der Pfad nicht „completions“ enthält, nur Info ausgeben (kein 404).
    if "completions" not in anypath:
        return _ok_json({"ok": True, "info": "Proxy läuft. Verwende /v1/chat/completions oder /chat/completions."})

    # Für GET (z.B. Janitor „Test“) einfach 200 OK zurückgeben
    if request.method == "GET":
        return _ok_json({"ok": True, "path": anypath, "hint": "POST hierher mit OpenAI-Chat-Payload."})

    # Ab hier: POST → an OpenRouter weiterleiten
    if not OPENROUTER_KEY:
        return _ok_json({"error": "OPENROUTER_KEY fehlt in der Umgebung."}, code=500)

    try:
        incoming = request.get_json(silent=True) or {}
        payload  = _normalize_payload(incoming)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://janitor.ai",
            "X-Title": "JanitorAI-Proxy",
        }

        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=90)

        # Antwort inkl. Header zurückreichen
        resp = Response(r.content, status=r.status_code, mimetype="application/json")
        for k, v in r.headers.items():
            resp.headers[k] = v
        return _cors(resp)

    except Exception as e:
        return _ok_json({"error": str(e)}, code=500)

# Lokaler Start (Render nutzt Gunicorn/Startkommando)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
