from flask import Flask, request, Response, jsonify
import os, requests, random, string, json

app = Flask(__name__)
app.url_map.strict_slashes = False  # /path und /path/ sind gleich

OPENROUTER_KEY   = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL    = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Bekannte Aliasse -> OpenRouter Slugs
MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free":     "deepseek/deepseek-chat:free",
    "deepseek-chat-v3:free":          "deepseek/deepseek-chat:free",
    "deepseek-chat:free":             "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat:free":    "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat-v3:free": "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    # ohne :free auch erlauben:
    "deepseek-chat-v3-0324":          "deepseek/deepseek-chat:free",
    "deepseek-chat-v3":               "deepseek/deepseek-chat:free",
    "deepseek-chat":                  "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat":         "deepseek/deepseek-chat:free",
}

def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

@app.route("/", methods=["GET"])
def root():
    return cors(jsonify({"ok": True, "endpoint": "chat/completions"}))

@app.route("/health", methods=["GET", "HEAD"])
def health():
    code = "ok-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(jsonify({"ok": True, "code": code}))

# Beide Pfade erlauben (mit/ohne v1, mit/ohne Slash)
@app.route("/chat/completions", methods=["POST","OPTIONS"])
@app.route("/v1/chat/completions", methods=["POST","OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return cors(Response("", status=204))

    if not OPENROUTER_KEY:
        return cors(jsonify({"ok": False, "error": "Missing OPENROUTER_KEY"})), 500

    # Payload robust einlesen
    data = request.get_json(silent=True) or {}

    # prompt -> messages wandeln (falls nötig)
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if isinstance(txt, list):
            txt = " ".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # messages-Content vereinheitlichen (join von Content-Listen)
    if "messages" in data:
        for m in data["messages"]:
            c = m.get("content")
            if isinstance(c, list):
                m["content"] = "".join(
                    part.get("text","") if isinstance(part, dict) else str(part)
                    for part in c
                )

    # Model normalisieren
    slug_in = (data.get("model") or DEFAULT_MODEL).strip()
    slug = MODEL_ALIASES.get(slug_in, slug_in)
    data["model"] = slug

    # Default: kein Stream, falls Client nichts angibt
    data.setdefault("stream", False)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://janitor.ai",
        "X-Title": "JanitorAI-Proxy",
    }

    # Erste Anfrage
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=data,
        timeout=90,
    )

    # Automatischer Fallback bei 404 „No endpoints found…“
    if r.status_code == 404:
        try:
            err = r.json()
            msg = (err.get("error", {}) or {}).get("message", "")
        except Exception:
            msg = ""
        if "No endpoints found" in msg and slug != "deepseek/deepseek-chat:free":
            data["model"] = "deepseek/deepseek-chat:free"
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=90,
            )

    # Antwort + Header durchreichen
    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        resp.headers[k] = v
    return cors(resp)

if __name__ == "__main__":
    # Für Render mit Gunicorn, lokal geht auch `python Main.py`
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
