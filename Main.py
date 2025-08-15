from flask import Flask, request, Response, jsonify
import requests, os, random, string, json

app = Flask(__name__)

# === Konfiguration ===
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")  # MUSS gesetzt sein
# Falls du später ein anderes Default willst, hier umstellen oder per Env:
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# CORS-Helfer
def cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

# Health mit Zufallscodes
@app.route("/health", methods=["GET"])
def health():
    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return cors(Response(json.dumps({"ok": True, "code": code, "endpoint": "v1/chat/completions"}), mimetype="application/json"))

# Root zeigt knappe Hilfe
@app.route("/", methods=["GET"])
def root():
    return cors(Response(json.dumps({"ok": True, "endpoint": "v1/chat/completions"}), mimetype="application/json"))

# ---- Eingabe normalisieren (OpenAI- & Janitor-Varianten) ----
def normalize_payload(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}

    # messages konstruieren, falls nur "prompt" oder "input" kam
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input")
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # Minimales Fallback
    if "messages" not in data or not data["messages"]:
        data["messages"] = [{"role": "user", "content": "Hi"}]

    # Streaming standardmäßig aus, wenn es nicht explizit gesetzt wurde
    data.setdefault("stream", False)

    # Egal, was client schickt → immer DeepSeek verwenden
    data["model"] = DEFAULT_MODEL

    return data

# ---- Proxy-Routen (mit & ohne /v1) ----
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
@app.route("/chat/completions", methods=["POST", "OPTIONS"])
def proxy():
    if request.method == "OPTIONS":
        return cors(Response("", status=204))

    # API-Key prüfen (nur Server-seitig)
    if not OPENROUTER_KEY:
        return cors(Response(json.dumps({"error": "Missing OPENROUTER_KEY"}), status=500, mimetype="application/json"))

    # JSON einlesen (ohne Exception)
    try:
        incoming = request.get_json(silent=True) or {}
    except Exception:
        incoming = {}

    # Nutzlast normalisieren und Modell festzurren
    outgoing = normalize_payload(incoming)

    # Anfrage an OpenRouter
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                # Referrer/Title optional – schaden nicht:
                "HTTP-Referer": "https://janitor.ai",
                "X-Title": "JanitorAI-Proxy"
            },
            json=outgoing,
            timeout=90
        )
    except requests.RequestException as e:
        return cors(Response(json.dumps({"error": "Upstream request failed", "detail": str(e)}), status=502, mimetype="application/json"))

    # Antwort 1:1 weiterreichen (Body & Header), aber CORS drüberlegen
    resp = Response(r.content, status=r.status_code, mimetype=r.headers.get("Content-Type", "application/json"))
    for k, v in r.headers.items():
        # sicher ist sicher, nur sinnvolle Header kopieren
        if k.lower() in ("content-type",):
            resp.headers[k] = v
    return cors(resp)

# ---- Start (lokal) ----
if __name__ == "__main__":
    # Für Render läuft gunicorn, local zum Test so:
    app.run(host="0.0.0.0", port=8080)
