# Main.py
from flask import Flask, request, Response, jsonify
import os, requests, random, string, json

app = Flask(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free").strip()

# Alle sinnvollen Aliases -> OpenRouter-Slug
MODEL_ALIASES = {
    "deepseek": "deepseek/deepseek-chat:free",
    "deepseek-chat": "deepseek/deepseek-chat:free",
    "deepseek-chat:free": "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat": "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat:free": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324": "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat:free",
}

# ---- CORS Helper -----------------------------------------------------------
def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

@app.after_request
def after(resp):
    return cors(resp)

# ---- Health & Info ---------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify(ok=True, endpoint="chat/completions")

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify(ok=True, path="v1/chat/completions", hint="POST hierher mit OpenAI-Chat-Payload.")

@app.route("/health", methods=["GET"])
def health():
    code = "ok-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return jsonify(ok=True, code=code)

# ---- Models (für Janitor „No endpoints found …“) ---------------------------
def _models_payload():
    # Liefere mehrere IDs, damit Frontends „was finden“
    ids = sorted(set([
        "deepseek/deepseek-chat:free",
        "deepseek/deepseek-chat",
        "deepseek-chat:free",
        "deepseek-chat",
        "deepseek-chat-v3",
        "deepseek-chat-v3-0324:free",
    ]))
    # OpenAI-kompatibel
    data = {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}
    return data

@app.route("/models", methods=["GET"])
@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify(_models_payload())

# ---- Chat Completions ------------------------------------------------------
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS", "GET"])
@app.route("/chat/completions", methods=["POST", "OPTIONS", "GET"])
def proxy():
    # OPTIONS: CORS preflight
    if request.method == "OPTIONS":
        return Response("", status=204)

    # GET: freundlich antworten statt 405, damit Tests im Browser/Janitor grün sind
    if request.method == "GET":
        return jsonify(ok=True, path="v1/chat/completions",
                       hint="Bitte als POST mit JSON-Body im OpenAI-Chat-Format senden.")

    if not OPENROUTER_KEY:
        return cors(Response(json.dumps({"error": "Missing OPENROUTER_KEY"}), status=500, mimetype="application/json"))

    # JSON holen (tolerant: auch leere Bodies)
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    # --- Prompt/Input -> messages umwandeln
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None)
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt is None:
            # evtl. aus "content" (manche Tools schicken nur das)
            txt = data.get("content")
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # Falls messages vorhanden aber nicht im gewünschten Format: flachziehen
    if isinstance(data.get("messages"), list):
        msgs = []
        for m in data["messages"]:
            if isinstance(m, dict) and "content" in m:
                # content-Teile (strings/objekte) zu einem String joinen
                c = m["content"]
                if isinstance(c, list):
                    text = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in c)
                else:
                    text = str(c)
                role = m.get("role", "user")
                msgs.append({"role": role, "content": text})
            elif isinstance(m, str):
                msgs.append({"role": "user", "content": m})
        if msgs:
            data["messages"] = msgs

    # --- Modell setzen/normalisieren
    wanted = (data.get("model") or DEFAULT_MODEL).strip()
    slug = MODEL_ALIASES.get(wanted, wanted)
    data["model"] = slug

    # --- Defaults
    data.setdefault("stream", False)

    # --- Upstream an OpenRouter
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": "https://janitor.ai",
                "X-Title": "JanitorAI-Proxy",
            },
            json=data,
            timeout=90,
        )
    except requests.RequestException as e:
        return cors(Response(json.dumps({"error": str(e)}), status=502, mimetype="application/json"))

    # Antwort & Header durchreichen
    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        # sicherheitshalber keine hop-by-hop Header übernehmen
        if k.lower() not in {"content-length", "transfer-encoding", "connection"}:
            resp.headers[k] = v
    return cors(resp)

# ---- Start (Render verwendet Gunicorn; lokal geht app.run) -----------------
if __name__ == "__main__":
    # Lokal testen: python Main.py
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
