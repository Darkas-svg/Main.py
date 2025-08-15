from flask import Flask, request, Response
import requests, os, random, string, json

app = Flask(__name__)
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":      "deepseek/deepseek-chat",
    "deepseek-chat":              "deepseek/deepseek-chat",
    "deepseek-v3":                "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
}

def cors(resp: Response) -> Response:
    h = resp.headers
    h["Access-Control-Allow-Origin"] = "*"
    h["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    h["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

@app.route("/health", methods=["GET"])
def health():
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(Response(f"ok-{code}", status=200))

# Akzeptiere mehrere Pfade wie UIs sie senden
@app.route("/chat/completions", methods=["POST", "OPTIONS"])
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
@app.route("/v1/completions", methods=["POST", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return cors(Response("", status=204))
    if not OPENROUTER_KEY:
        return cors(Response("Missing OPENROUTER_KEY", status=500))

    data = request.get_json(silent=True) or {}

    # --- Normalisierung ---
    # prompt/input -> messages
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if isinstance(txt, list):  # manche UIs schicken list content
            txt = " ".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": txt}]

    # content evtl. als Liste -> string
    if "messages" in data:
        for m in data["messages"]:
            c = m.get("content")
            if isinstance(c, list):
                m["content"] = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in c
                )

    # Model setzen/umbenennen
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # Stream standardmäßig aus
    data.setdefault("stream", False)
    # ----------------------

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer": "https://janitor.ai",
            "X-Title": "JanitorAI-Proxy"
        },
        json=data,
        timeout=90
    )
    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        resp.headers[k] = v
    return cors(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
