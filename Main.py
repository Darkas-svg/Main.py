from flask import Flask, request, Response, jsonify
import requests, os, random, string, json

app = Flask(__name__)

# === Konfiguration ===
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Häufige Kurzschreibweisen -> OpenRouter-Slug
MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":      "deepseek/deepseek-chat:free",
    "deepseek-chat:v3":           "deepseek/deepseek-chat:free",
    "deepseek-chat":              "deepseek/deepseek-chat:free",
    "deepseek":                   "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat:free":         "deepseek/deepseek-chat:free",
}

# CORS-Helfer
def add_cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

# Healthcheck (random, damit du siehst, dass es DEIN Server ist)
@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return add_cors(Response(f"ok-{code}", status=200))

# Home
@app.route("/", methods=["GET"])
def home():
    return add_cors(Response("ready", status=200))

# === Normalisierung eingehender Daten ===
def normalize_payload(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}

    # Prompt/Inputs zu messages umbiegen
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if txt is not None:
            if isinstance(txt, list):
                txt = "\n".join(map(str, txt))
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # content immer als string
    if "messages" in data:
        norm_msgs = []
        for m in data["messages"]:
            if isinstance(m, dict):
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(part) for part in content)
                else:
                    content = str(content)
                role = m.get("role", "user")
                norm_msgs.append({"role": role, "content": content})
            else:
                norm_msgs.append({"role": "user", "content": str(m)})
        data["messages"] = norm_msgs

    # Modell-Alias lösen
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # Streaming standardmäßig aus (Janitor erwartet meist non-stream)
    data.setdefault("stream", False)

    return data

# === Proxy-Handler ===
def handle_proxy():
    # Preflight
    if request.method == "OPTIONS":
        return add_cors(Response("", status=204))

    # Janitor prüft oft mit GET – gib 200 zurück, damit es „grün“ ist
    if request.method == "GET":
        return add_cors(Response(json.dumps({"ok": True, "endpoint": "chat/completions"}), mimetype="application/json", status=200))

    # Ab hier POST -> an OpenRouter weiterleiten
    if not OPENROUTER_KEY:
        return add_cors(Response(json.dumps({"error": "Missing OPENROUTER_KEY"}), mimetype="application/json", status=500))

    try:
        data = request.get_json(silent=True) or {}
        data = normalize_payload(data)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            # Nettes Signal an OpenRouter, woher der Traffic kommt
            "HTTP-Referer": "https://janitor.ai",
            "X-Title": "JanitorAI-Proxy",
        }

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=90
        )

        # Antwort zurückreichen + CORS
        resp = Response(r.content, status=r.status_code)
        # Nützliche Header übernehmen
        for k, v in r.headers.items():
            if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}:
                resp.headers[k] = v
        return add_cors(resp)

    except Exception as e:
        return add_cors(Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500))

# Alle relevanten Pfade -> gleicher Handler
@app.route("/chat/completions", methods=["GET", "POST", "OPTIONS"])
@app.route("/v1/chat/completions", methods=["GET", "POST", "OPTIONS"])
def proxy():
    return handle_proxy()

if __name__ == "__main__":
    # Lokal/Dev – auf Render übernimmt Gunicorn das Listening
    app.run(host="0.0.0.0", port=8080)
