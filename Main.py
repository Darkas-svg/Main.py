from flask import Flask, request, Response, jsonify
import os, requests, json, random, string

app = Flask(__name__)
app.url_map.strict_slashes = False  # /pfad und /pfad/ beides ok

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324": "deepseek/deepseek-chat",
    "deepseek-chat": "deepseek/deepseek-chat",
    "deepseek-v3": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
}

def add_cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return add_cors(Response(f"ok-{code}", status=200))

@app.route("/", methods=["GET"])
def root():
    return add_cors(Response("ready", status=200))

@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return add_cors(Response("", status=204))

# die eigentliche Proxy-Funktion
def handle_proxy():
    if request.method == "OPTIONS":
        return add_cors(Response("", status=204))

    if not OPENROUTER_KEY:
        return add_cors(Response("Missing OPENROUTER_KEY", status=500))

    data = request.get_json(silent=True) or {}

    # Texte normalisieren (Janitor kann prompt/input oder messages schicken)
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input")
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # Modell auflösen/ersetzen
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # Streaming standardmäßig aus
    data.setdefault("stream", False)

    # Request an OpenRouter
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

    # Antwort inkl. Status & Headers zurückreichen
    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        resp.headers[k] = v
    return add_cors(resp)

# alle Varianten der Pfade registrieren (mit/ohne v1, mit/ohne Slash)
for p in ["/chat/completions", "/v1/chat/completions",
          "/chat/completions/", "/v1/chat/completions/"]:
    app.add_url_rule(p, view_func=handle_proxy, methods=["POST", "OPTIONS"])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
