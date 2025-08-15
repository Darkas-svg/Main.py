# -*- coding: utf-8 -*-
from flask import Flask, request, Response, jsonify, make_response
from flask_cors import CORS
import os, json, random, string, time
import requests

app = Flask(__name__)
app.url_map.strict_slashes = False
CORS(app)  # Browser-POSTs erlauben

# ===== Konfiguration =====
OPENROUTER_KEY       = (os.getenv("OPENROUTER_KEY") or "").strip()
DEFAULT_MODEL        = (os.getenv("OPENROUTER_MODEL") or "deepseek/deepseek-chat").strip()
PREFERRED_PROVIDER   = (os.getenv("OPENROUTER_PROVIDER") or "").strip()  # z.B. "Novita" oder "DeepSeek"
UPSTREAM_TIMEOUT_SEC = int(os.getenv("UPSTREAM_TIMEOUT_SEC", "20"))  # kürzeres Timeout

# Aliasse → stabile Slugs
MODEL_ALIASES = {
    "deepseek": "deepseek/deepseek-chat",
    "deepseek-chat": "deepseek/deepseek-chat",
    "deepseek-chat:free": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat:free": "deepseek/deepseek-chat",
    "deepseek-chat-v3": "deepseek/deepseek-chat",
    "deepseek-chat-v3-0324": "deepseek/deepseek-chat",
    "deepseek-chat-v3-0324:free": "deepseek/deepseek-chat",
    # Falls jemand OpenAI-IDs schickt:
    "gpt-3.5-turbo": "deepseek/deepseek-chat",
    "gpt-4o-mini": "deepseek/deepseek-chat",
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ===== Hilfen =====
def rnd(n=8):
    import string, random
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def normalize_payload(data: dict) -> dict:
    data = dict(data or {})

    # prompt/input → messages
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input") or data.get("content")
        if isinstance(txt, list):
            txt = "\n".join(map(str, txt))
        if txt:
            data["messages"] = [{"role": "user", "content": str(txt)}]

    # messages bereinigen (content ggf. Liste → String)
    if isinstance(data.get("messages"), list):
        msgs = []
        for m in data["messages"]:
            if not isinstance(m, dict):
                msgs.append({"role": "user", "content": str(m)})
                continue
            role = m.get("role", "user")
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in c)
            msgs.append({"role": role, "content": str(c)})
        data["messages"] = msgs

    # Modell normalisieren
    wanted = (data.get("model") or DEFAULT_MODEL).strip()
    slug = MODEL_ALIASES.get(wanted, wanted)
    data["model"] = slug

    # Provider-Präferenz, wenn gesetzt
    if PREFERRED_PROVIDER:
        data["provider"] = PREFERRED_PROVIDER

    # Nicht streamen (Janitor / Browser mögen non-stream JSON)
    data.setdefault("stream", False)
    return data

def proxy_to_openrouter(payload: dict):
    """Schickt Request zu OpenRouter, mit kurzem Timeout & klaren Fehlern"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # optional – hilft bei Routing/Analytics:
        "HTTP-Referer": "https://janitor.ai",
        "X-Title": "JanitorAI-Proxy",
    }
    try:
        r = requests.post(
            OPENROUTER_URL,
            json=payload,
            headers=headers,
            timeout=UPSTREAM_TIMEOUT_SEC,
        )
        return r, None
    except requests.Timeout as e:
        return None, {"error": {"type": "upstream_timeout", "message": f"OpenRouter Timeout nach {UPSTREAM_TIMEOUT_SEC}s"}}
    except requests.RequestException as e:
        return None, {"error": {"type": "upstream_error", "message": f"OpenRouter-Request fehlgeschlagen: {str(e)}"}}

def pass_response(r: requests.Response) -> Response:
    """Antwort inkl. nützlicher Header zurückgeben"""
    resp = Response(r.content, status=r.status_code, mimetype=r.headers.get("Content-Type", "application/json"))
    # Provider/Model sichtbar machen (hilft beim Debuggen)
    for hk in ("x-openrouter-model", "x-openrouter-provider", "openrouter-processing-ms"):
        if hk in r.headers:
            resp.headers[hk] = r.headers[hk]
    return resp

# ===== Info / Health / Models =====
@app.route("/", methods=["GET"])
def root():
    return jsonify(ok=True, endpoint="v1/chat/completions", note="Sende POST im OpenAI-Chat-Format an diesen Endpoint.")

@app.route("/health", methods=["GET"])
def health():
    return jsonify(ok=True, code=f"ok-{rnd()}")

def _models_payload():
    ids = sorted(set([
        "deepseek/deepseek-chat",
        "deepseek/deepseek-coder",
        "deepseek/deepseek-r1",
        "deepseek-chat-v3-0324",
        "deepseek-chat",
    ]))
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}

@app.route("/models", methods=["GET"])
@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify(_models_payload())

# ===== Mini-Tester (Browser) =====
@app.route("/tester", methods=["GET"])
def tester():
    html = f"""<!doctype html><meta charset="utf-8"><title>Proxy Tester</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:24px;max-width:900px}}
textarea{{width:100%;height:200px;font-family:ui-monospace,Menlo,Consolas,monospace}}
pre{{white-space:pre-wrap;background:#111;color:#eee;padding:12px;border-radius:8px}}
button{{padding:.6rem 1rem;border:0;border-radius:.6rem;background:#0a7;color:#fff}}
</style>
<h2>Proxy Tester</h2>
<p>Sendet einen echten POST an <code>/v1/chat/completions</code> (Timeout {UPSTREAM_TIMEOUT_SEC}s).</p>
<textarea id="p">{{"model":"deepseek/deepseek-chat","messages":[{{"role":"user","content":"Sag nur: Hallo von Darkas!"}}]}}</textarea><br><br>
<button id="go">Senden</button>
<pre id="out">–</pre>
<script>
go.onclick = async () => {{
  out.textContent = "Sende …";
  try {{
    const res = await fetch("/v1/chat/completions", {{
      method: "POST", headers: {{ "Content-Type": "application/json" }},
      body: document.getElementById("p").value
    }});
    const text = await res.text();
    out.textContent = "HTTP " + res.status + "\\n" + text;
  }} catch(e) {{
    out.textContent = "Fetch-Fehler: " + e;
  }}
}};
</script>"""
    r = make_response(html)
    r.headers["Content-Type"] = "text/html; charset=utf-8"
    return r

# ===== Proxy-Endpunkte =====
@app.route("/v1/chat/completions", methods=["POST", "OPTIONS", "GET"])
@app.route("/chat/completions",   methods=["POST", "OPTIONS", "GET"])
def completions():
    if request.method == "OPTIONS":
        return Response("", status=204)
    if request.method == "GET":
        # Freundlicher Hinweis statt 405
        return jsonify(ok=True, hint="Sende POST im OpenAI-Chat-Format an diesen Endpoint.")

    if not OPENROUTER_KEY:
        return jsonify(error={"type": "config", "message": "OPENROUTER_KEY fehlt auf dem Server."}), 500

    # Body lesen & normalisieren
    try:
        incoming = request.get_json(silent=True) or {}
    except Exception:
        incoming = {}
    payload = normalize_payload(incoming)

    # 1. Versuch
    r, err = proxy_to_openrouter(payload)
    if err:
        return jsonify(err), 504

    # Bei „No endpoints found …“ auf andere Slugs wechseln
    if r.status_code == 404:
        try:
            msg = r.json()
        except Exception:
            msg = {"error": {"message": r.text}}
        txt = json.dumps(msg).lower()
        if "no endpoints found" in txt or "not found" in txt:
            # Fallback-Kandidaten in Reihenfolge
            for candidate in [
                payload.get("model"),
                DEFAULT_MODEL,
                "deepseek/deepseek-chat",
                "deepseek/deepseek-coder",
                "deepseek/deepseek-r1",
            ]:
                if not candidate or candidate == payload.get("model"):
                    continue
                payload["model"] = candidate
                r2, err2 = proxy_to_openrouter(payload)
                if err2:
                    continue
                if r2.status_code < 400:
                    return pass_response(r2)
            # Wenn alles fehlschlägt, 404 mit Originaltext:
            return pass_response(r)

    # Bei 429/5xx: einmal kurzer Retry
    if r.status_code in (429, 500, 502, 503, 504):
        time.sleep(0.5)
        r2, err2 = proxy_to_openrouter(payload)
        if not err2:
            return pass_response(r2)

    return pass_response(r)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
