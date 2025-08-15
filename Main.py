# -*- coding: utf-8 -*-
from flask import Flask, request, Response, jsonify
import os, json, random, string, time
import requests

app = Flask(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "").strip() or "deepseek/deepseek-chat"

# Häufig genutzte Aliasnamen -> OpenRouter-Slugs
MODEL_ALIASES = {
    # „Free“-Bezeichnungen/Alt-Slugs abfangen
    "deepseek/deepseek-chat:free": "deepseek/deepseek-chat",
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat",
    "deepseek-chat-v3-0324": "deepseek/deepseek-chat",
    "deepseek-chat": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat-v3-0324": "deepseek/deepseek-chat",

    # weitere plausible Bezeichner
    "deepseek-coder": "deepseek/deepseek-coder",
    "deepseek/deepseek-coder:free": "deepseek/deepseek-coder",
    "deepseek-r1": "deepseek/deepseek-r1",
    "deepseek/deepseek-r1:free": "deepseek/deepseek-r1",

    # OpenAI-ähnliche Aliasse -> auf DeepSeek chat mappen
    "gpt-3.5-turbo": "deepseek/deepseek-chat",
    "gpt-4o-mini": "deepseek/deepseek-chat",
}

# Reihenfolge, in der bei 404 (No endpoints) automatisch umgeschaltet wird
FALLBACK_MODELS = [
    lambda m: MODEL_ALIASES.get(m, m),
    lambda _m: DEFAULT_MODEL,
    lambda _m: "deepseek/deepseek-chat",
    lambda _m: "deepseek/deepseek-coder",
    lambda _m: "deepseek/deepseek-r1",
]

def with_cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp

def _ok(obj: dict) -> Response:
    return with_cors(Response(json.dumps(obj), mimetype="application/json"))

@app.route("/", methods=["GET", "HEAD", "OPTIONS"])
def root():
    if request.method == "OPTIONS":
        return with_cors(Response(status=204))
    info = {
        "ok": True,
        "endpoint": "chat/completions",
        "hint": "POST hierher mit OpenAI-Chat-Payload.",
    }
    return _ok(info)

@app.route("/health", methods=["GET"])
def health():
    code = "ok-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return _ok({"ok": True, "code": code})

@app.route("/tester", methods=["GET"])
def tester():
    # sehr simples HTML, das POST auf /v1/chat/completions macht (same origin)
    html = """<!doctype html><meta charset="utf-8"><title>Proxy Tester</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:20px;max-width:900px}
textarea{width:100%;height:220px;font-family:ui-monospace,Menlo,Consolas,monospace}
pre{background:#111;color:#0f0;padding:12px;border-radius:8px;overflow:auto}
button{padding:8px 14px;border-radius:10px;border:1px solid #444;background:#222;color:#fff}
.small{opacity:.7;font-size:.9em;margin-bottom:10px}
</style>
<h1>Proxy Tester</h1>
<p class="small">Testet <code>/v1/chat/completions</code> direkt vom Browser. Dein Server-Key bleibt <b>serverseitig</b>.</p>
<textarea id="payload">{\n  "model": "deepseek/deepseek-chat",\n  "messages": [{"role":"user","content":"Sag nur: Hallo von Darkas!"}]\n}</textarea>
<br><br>
<button id="send">Senden</button>
<pre id="out">...</pre>
<script>
const out = document.getElementById('out');
document.getElementById('send').onclick = async () => {
  out.textContent = "Sende...";
  try{
    const body = document.getElementById('payload').value;
    const r = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body
    });
    const text = await r.text();
    out.textContent = "Status: " + r.status + "\\n\\n" + text;
  }catch(e){
    out.textContent = "Fetch-Fehler: " + e;
  }
};
</script>"""
    return with_cors(Response(html, mimetype="text/html; charset=utf-8"))

# Beide Pfade akzeptieren (JanitorAI probiert gern /v1/chat/completions)
@app.route("/chat/completions", methods=["POST", "GET", "OPTIONS"])
@app.route("/v1/chat/completions", methods=["POST", "GET", "OPTIONS"])
def chat_completions():
    if request.method == "OPTIONS":
        return with_cors(Response(status=204))
    if request.method == "GET":
        # Freundlicher Hinweis statt 405
        return _ok({"ok": True, "path": "/v1/chat/completions", "hint": "POST hierher mit OpenAI-Chat-Payload."})

    if not OPENROUTER_KEY:
        return with_cors(Response(
            json.dumps({"error": {"message": "OPENROUTER_KEY fehlt auf dem Server."}}),
            status=500, mimetype="application/json"
        ))

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    # ---- Normalisierung: prompt/input -> messages
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input")
        if isinstance(txt, list):
            txt = " ".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # content kann bei manchen Clients ein Array sein -> zusammenziehen
    if "messages" in data:
        for msg in data["messages"]:
            c = msg.get("content", "")
            if isinstance(c, list):
                parts = []
                for part in c:
                    parts.append(part.get("text", "") if isinstance(part, dict) else str(part))
                msg["content"] = " ".join(p for p in parts if p is not None)

    # Modell mappen & stream deaktivieren
    model_req = data.get("model") or DEFAULT_MODEL
    model_slug = MODEL_ALIASES.get(model_req, model_req)
    data["model"] = model_slug
    data["stream"] = False

    # Versuch mit Fallbacks
    tried = set()
    last_error_body = None
    for step, pick in enumerate(FALLBACK_MODELS, start=1):
        candidate = pick(model_slug)
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        data["model"] = candidate

        # bis zu 2 Re-Trys bei 429/5xx
        for attempt in range(3):
            try:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type": "application/json",
                        # optionale Metadaten (schaden nicht, helfen manchmal beim Routing)
                        "HTTP-Referer": "https://janitor.ai",
                        "X-Title": "JanitorAI-Proxy",
                    },
                    json=data,
                    timeout=90,
                )
            except requests.RequestException as e:
                # Netzwerkfehler -> kurzer Backoff und retry (außer letzter Versuch)
                last_error_body = {"error": {"message": f"Upstream-Request fehlgeschlagen: {e}"}}
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                break

            # Erfolg -> Antw. & Header durchreichen
            if r.status_code < 400:
                resp = Response(r.content, status=r.status_code, mimetype="application/json")
                # ausgewählte Header übernehmen (viele sind Hop-by-Hop oder irrelevant)
                for hk, hv in r.headers.items():
                    if hk.lower() in ("content-type", "x-request-id", "x-openai-model",
                                      "openrouter-processing-ms", "openrouter-cache-status"):
                        resp.headers[hk] = hv
                return with_cors(resp)

            # Fehler parsen
            try:
                last_error_body = r.json()
            except Exception:
                last_error_body = {"error": {"message": r.text.strip() or f"HTTP {r.status_code}"}}

            msg = json.dumps(last_error_body).lower()

            # 404 wegen nicht vorhandener Endpoints -> nächsten Fallback probieren
            if r.status_code == 404 and ("no endpoints found" in msg or "not found" in msg):
                # zum nächsten candidate in der äußeren Schleife
                break

            # 429/5xx -> retry
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue

            # andere Fehler -> nicht weiter probieren
            resp = Response(json.dumps(last_error_body), status=r.status_code, mimetype="application/json")
            return with_cors(resp)

    # Wenn wir hier landen, haben alle Fallbacks nicht funktioniert
    if not last_error_body:
        last_error_body = {"error": {"message": "Kein verfügbares Modell gefunden (alle Fallbacks fehlgeschlagen)."}}
    return with_cors(Response(json.dumps(last_error_body), status=404, mimetype="application/json"))

if __name__ == "__main__":
    # Lokaler Start (auf Render übernimmt gunicorn aus Procfile/Startbefehl)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
