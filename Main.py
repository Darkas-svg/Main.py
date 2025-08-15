from flask import Flask, request, Response, jsonify, make_response
import os, requests, random, string, json, html

app = Flask(__name__)
app.url_map.strict_slashes = False

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free").strip()

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

def cors(resp: Response) -> Response:
    # Weite CORS-Freigabe
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*") or "*"
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

@app.after_request
def after(resp):
    return cors(resp)

# -------------------- Health & Info --------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify(ok=True, endpoint="v1/chat/completions")

@app.route("/ping", methods=["GET"])
def ping():
    code = "ok-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return jsonify(ok=True, code=code)

# sehr simple Debug-Seite im Browser
@app.route("/tester", methods=["GET"])
def tester():
    html_page = f"""<!doctype html>
<html lang="de"><meta charset="utf-8"/>
<title>Proxy Tester</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}}
 textarea{{width:100%;height:160px}}
 pre{{white-space:pre-wrap;background:#111;color:#eee;padding:1rem;border-radius:.5rem;overflow:auto}}
 button{{padding:.6rem 1rem;border-radius:.5rem;border:0;background:#0a7;cursor:pointer}}
</style>
<h1>Proxy Tester</h1>
<p>Testet <code>/v1/chat/completions</code> direkt vom Browser.</p>
<p><strong>Hinweis:</strong> Dein OpenRouter-Key bleibt <em>serverseitig</em> – im Browser wird nichts verraten.</p>

<label>Payload (OpenAI-Chat-Format):</label>
<textarea id="payload">{{
  "model": "deepseek/deepseek-chat:free",
  "messages": [{{"role":"user","content":"Sag nur: Hallo von Darkas!"}}],
  "stream": false
}}</textarea>
<br><br>
<button id="go">Senden</button>
<pre id="out">Noch nichts gesendet…</pre>

<script>
document.getElementById('go').onclick = async () => {{
  const out = document.getElementById('out');
  out.textContent = "Sende…";
  try {{
    const res = await fetch("{html.escape(request.url_root.rstrip('/'))}/v1/chat/completions", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: document.getElementById('payload').value
    }});
    const text = await res.text();
    out.textContent = "HTTP " + res.status + "\\n\\n" + text;
  }} catch (e) {{
    out.textContent = "Fetch-Fehler: " + e;
  }}
}};
</script>
"""
    resp = make_response(html_page)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

# -------------------- Models (für UIs) --------------------
def _models_payload():
    ids = sorted(set([
        "deepseek/deepseek-chat:free",
        "deepseek/deepseek-chat",
        "deepseek-chat:free",
        "deepseek-chat",
        "deepseek-chat-v3",
        "deepseek-chat-v3-0324:free",
    ]))
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}

@app.route("/models", methods=["GET"])
@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify(_models_payload())

# -------------------- Proxy Handler --------------------
def handle_proxy():
    # Logging ins Render-Log
    try:
        app.logger.info("REQ %s %s", request.method, request.path)
    except Exception:
        pass

    if request.method == "OPTIONS":
        return Response("", status=204)

    if request.method == "GET":
        return jsonify(ok=True, path="v1/chat/completions",
                       hint="Bitte als POST mit JSON-Body im OpenAI-Chat-Format senden.")

    if not OPENROUTER_KEY:
        return cors(Response(json.dumps({"error": "Missing OPENROUTER_KEY"}),
                             status=500, mimetype="application/json"))

    data = request.get_json(silent=True) or {}

    # prompt/input -> messages
    if "messages" not in data:
        txt = data.pop("prompt", None) or data.pop("input", None) or data.get("content")
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # messages säubern
    if isinstance(data.get("messages"), list):
        msgs = []
        for m in data["messages"]:
            if isinstance(m, dict) and "content" in m:
                c = m["content"]
                if isinstance(c, list):
                    text = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in c)
                else:
                    text = str(c)
                msgs.append({"role": m.get("role", "user"), "content": text})
            elif isinstance(m, str):
                msgs.append({"role": "user", "content": m})
        if msgs:
            data["messages"] = msgs

    # Modell normalisieren
    wanted = (data.get("model") or DEFAULT_MODEL).strip()
    slug = MODEL_ALIASES.get(wanted, wanted)
    data["model"] = slug

    data.setdefault("stream", False)

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

    resp = Response(r.content, status=r.status_code)
    for k, v in r.headers.items():
        if k.lower() not in {"content-length", "transfer-encoding", "connection"}:
            resp.headers[k] = v
    return cors(resp)

# Chat-Completions – viele Varianten erlaubt
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS", "GET"])
@app.route("/v1/chat/completions/", methods=["POST", "OPTIONS", "GET"])
@app.route("/chat/completions", methods=["POST", "OPTIONS", "GET"])
@app.route("/chat/completions/", methods=["POST", "OPTIONS", "GET"])
# Legacy
@app.route("/v1/completions", methods=["POST", "OPTIONS", "GET"])
@app.route("/completions", methods=["POST", "OPTIONS", "GET"])
def proxy():
    return handle_proxy()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
