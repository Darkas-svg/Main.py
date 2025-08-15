from flask import Flask, request, Response
import requests, os, random, string, json

app = Flask(__name__)
app.url_map.strict_slashes = False  # toleriert /pfad und /pfad/

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL  = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":      "deepseek/deepseek-chat",
    "deepseek-chat":              "deepseek/deepseek-chat",
    "deepseek-v3":                "deepseek/deepseek-chat",
    # häufige OpenRouter-Schreibweise:
    "deepseek/deepseek-chat:v3-0324:free": "deepseek/deepseek-chat:free",
}

TARGETS = {
    "v1/chat/completions",
    "chat/completions",
    "v1/completions",
    "completions",
}

def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

def normalize_body(data: dict) -> dict:
    # prompt/input → messages
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if txt is not None:
            if isinstance(txt, list):
                txt = " ".join(map(str, txt))
            data["messages"] = [{"role": "user", "content": txt}]
    # list-content → string
    if "messages" in data:
        for m in data["messages"]:
            c = m.get("content")
            if isinstance(c, list):
                m["content"] = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in c
                )
    # Model mappen/setzen
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    data.setdefault("stream", False)
    return data

@app.route("/", methods=["GET", "HEAD"])
def root():
    return cors(Response("alive", status=200))

@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(Response(f"ok-{code}", status=200))

# ---- Catch-all: akzeptiert JEDE URL und prüft intern auf *completions*
@app.route("/<path:_path>", methods=["GET", "POST", "OPTIONS", "HEAD"])
@app.route("", methods=["GET", "POST", "OPTIONS", "HEAD"])
def catch_all(_path=""):
    # Pfad normalisieren (ohne führende/Trailing Slashes, doppelte Slashes etc.)
    path = "/".join(part for part in _path.strip().split("/") if part).lower()

    # Direktantworten / Preflight
    if request.method in ("OPTIONS", "HEAD"):
        return cors(Response("", status=204))
    if request.method == "GET":
        # Bei GET auf irgendeinen completions-Pfad → ready, sonst alive
        if path in TARGETS:
            return cors(Response("ready", status=200))
        return cors(Response("alive", status=200))

    # Ab hier: POST → nur weiterleiten, wenn completions-Pfad
    if path not in TARGETS:
        return cors(Response(json.dumps({"error":"not a completions endpoint","path":path}),
                             status=404, mimetype="application/json"))

    if not OPENROUTER_KEY:
        return cors(Response(json.dumps({"error":"Missing OPENROUTER_KEY"}),
                             status=500, mimetype="application/json"))

    data = request.get_json(silent=True) or {}
    data = normalize_body(data)

    upstream = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer":  "https://janitor.ai",
            "X-Title":       "JanitorAI-Proxy",
        },
        json=data,
        timeout=90,
    )

    resp = Response(upstream.content, status=upstream.status_code)
    for k, v in upstream.headers.items():
        resp.headers[k] = v
    return cors(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
