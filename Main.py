from flask import Flask, request, Response
import requests, os, random, string, json

app = Flask(__name__)

# ---- Config aus Umgebungsvariablen ----
OPENROUTER_KEY   = os.getenv("OPENROUTER_KEY", "").strip()
DEFAULT_MODEL    = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Aliase erlauben flexible Model-Namen aus Janitor
MODEL_ALIASES = {
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":      "deepseek/deepseek-chat",
    "deepseek-chat":              "deepseek/deepseek-chat",
    "deepseek-v3":                "deepseek/deepseek-chat",
    "deepseek":                   "deepseek/deepseek-chat",
}

# ---- CORS Helper ----
def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

# ---- Healthcheck (random Text) ----
@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(Response(f"ok-{code}", status=200, mimetype="text/plain"))

# ---- Body-Normalisierung (Janitor schickt verschiedenes) ----
def normalize_body(data: dict) -> dict:
    # prompt/input -> messages
    if "messages" not in data:
        # text kann als "prompt" oder "input" kommen
        txt = data.pop("prompt", None) or data.pop("input", None)
        if isinstance(txt, (list, tuple)):
            txt = " ".join(map(str, txt))
        if isinstance(txt, (str, int, float)) and str(txt).strip():
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # messages als String -> Liste
    if isinstance(data.get("messages"), (str, int, float)):
        data["messages"] = [{"role": "user", "content": str(data["messages"])}]

    # content-Teile zusammenführen, falls Liste/Objekte
    if isinstance(data.get("messages"), list):
        for m in data["messages"]:
            c = m.get("content")
            if isinstance(c, list):
                m["content"] = " ".join(part.get("text","") if isinstance(part,dict) else str(part) for part in c)
            elif not isinstance(c, str):
                m["content"] = str(c)

    # Model auflösen/standardisieren
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # falls nicht gestreamt gewünscht
    data.setdefault("stream", False)

    return data

# ---- Standard-Endpoint, den Janitor erwartet ----
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS", "HEAD"])
@app.route("/chat/completions",   methods=["POST", "OPTIONS", "HEAD"])  # falls du nur den kurzen Pfad nutzt
def completions():
    if request.method in ("OPTIONS", "HEAD"):
        return cors(Response("", status=204))

    if not OPENROUTER_KEY:
        return cors(Response(json.dumps({"error": "Missing OPENROUTER_KEY"}), status=500, mimetype="application/json"))

    data = request.get_json(silent=True) or {}
    data = normalize_body(data)

    try:
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
    except requests.RequestException as e:
        return cors(Response(json.dumps({"error": "upstream_failed", "detail": str(e)}),
                             status=502, mimetype="application/json"))

    resp = Response(upstream.content, status=upstream.status_code)
    # Header durchreichen (z. B. Ratelimits)
    for k, v in upstream.headers.items():
        resp.headers[k] = v
    return cors(resp)

# ---- Catch-all: GET = alive, POST/OPTIONS nur wenn Pfad stimmt ----
@app.route("/<path:_path>", methods=["GET", "POST", "OPTIONS", "HEAD"])
def catch_all(_path=""):
    path = "/".join(p for p in _path.strip().split("/") if p).lower()
    is_completions = (
        path.rstrip("/").endswith("chat/completions")
        or path.rstrip("/").endswith("/completions")
    )

    if request.method in ("OPTIONS", "HEAD"):
        return cors(Response("", status=204))

    if request.method == "GET":
        # einfache Liveness-Antwort für irgendwelche GETs
        return cors(Response("alive", 200, mimetype="text/plain"))

    if not is_completions:
        return cors(Response(json.dumps({"error": "wrong endpoint", "path": path}),
                             status=404, mimetype="application/json"))

    # Wenn es doch Completions ist, leite an die Hauptfunktion weiter
    return completions()

if __name__ == "__main__":
    # Render lauscht standardmäßig auf 10000/8080 – 8080 ist safe
    app.run(host="0.0.0.0", port=8080)
