from flask import Flask, request, Response
import requests, os, random, string, json

app = Flask(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Modell-Aliase
MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":      "deepseek/deepseek-chat",
    "deepseek-chat:":             "deepseek/deepseek-chat:",
    "deepseek-v3":                "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
}

# CORS-Helfer
def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    # Nimmt exakt die Header an, die der Browser anfragt
    req_headers = request.headers.get("Access-Control-Request-Headers", "")
    resp.headers["Access-Control-Allow-Headers"] = req_headers or "*"
    resp.headers["Access-Control-Expose-Headers"] = "*"
    return resp

@app.after_request
def add_cors_headers(r):
    return cors(r)

# Health-Check mit Zufallscode
@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=6))
    return cors(Response(f"ok-{code}", status=200))

# Endpunkte /chat/completions und /v1/chat/completions
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
@app.route("/chat/completions", methods=["POST", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return cors(Response("", status=204))

    if not OPENROUTER_KEY:
        return cors(Response("Fehlender OPENROUTER_KEY", status=500))

    data = request.get_json(silent=True) or {}

    # Falls keine messages vorhanden, aus prompt bauen
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if isinstance(txt, list):
            txt = " ".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": txt}]

    # content-Listen in Strings umwandeln
    if isinstance(data.get("messages"), list):
        for m in data["messages"]:
            if isinstance(m, dict) and "content" in m:
                c = m["content"]
                if isinstance(c, list):
                    m["content"] = " ".join(
                        str(part.get("text", "")) if isinstance(part, dict) else str(part)
                        for part in c
                    )

    # Modell setzen
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # Streaming deaktivieren
    data.setdefault("stream", False)

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": "https://janitor.ai",
                "X-Title": "JanitorAI-Proxy",
            },
            json=data,
            timeout=90,
        )
    except requests.RequestException as e:
        return cors(Response(json.dumps({"error": f"Upstream-Fehler: {str(e)}"}), status=502, mimetype="application/json"))

    resp = Response(r.content, status=r.status_code, mimetype=r.headers.get("Content-Type", "application/json"))
    for k, v in r.headers.items():
        resp.headers[k] = v
    return cors(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
