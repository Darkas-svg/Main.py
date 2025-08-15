from flask import Flask, request, Response
import requests, os, random, string

app = Flask(__name__)
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek-chat-v3-0324:free")

def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

@app.route("/health", methods=["GET"])
def health():
    # zufälliger Code, damit du sicher siehst, dass der aktuelle Build läuft
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(Response(f"ok-{code}", status=200))

# Beide Pfade akzeptieren (Janitor nutzt teils /v1)
@app.route("/chat/completions", methods=["POST", "OPTIONS"])
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return cors(Response("", status=204))

    if not OPENROUTER_KEY:
        return cors(Response("Missing OPENROUTER_KEY", status=500))

    # Request normalisieren
    data = request.get_json(silent=True) or {}

    # prompt/input -> messages
    if "messages" not in data:
        if "prompt" in data:
            data["messages"] = [{"role": "user", "content": data.pop("prompt")}]
        elif "input" in data:
            data["messages"] = [{"role": "user", "content": data.pop("input")}]

    # Model setzen, falls fehlt
    if not data.get("model"):
        data["model"] = DEFAULT_MODEL

    # Stream default
    data.setdefault("stream", False)

    # An OpenRouter weiterleiten
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "HTTP-Referer": "https://janitor.ai",
            "X-Title": "JanitorAI-Proxy"
        },
        json=data,
        timeout=60
    )

    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        resp.headers[k] = v
    return cors(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
