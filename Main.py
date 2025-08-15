# Main.py
# Minimaler, robuster OpenRouter-Proxy für JanitorAI – mit CORS & Tester

from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import requests, os, json, random, string

app = Flask(__name__)
# CORS für alle Routen aktivieren (ermöglicht Browser-POST vom Handy)
CORS(app)

# --- Konfiguration / Umgebungsvariablen ---
OPENROUTER_KEY   = os.getenv("OPENROUTER_KEY") or ""
DEFAULT_MODEL    = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")

# Bequeme Aliasnamen (Janitor erwartet oft "deepseek-chat-v3-0324:free" etc.)
MODEL_ALIASES = {
    "deepseek-chat":                 "deepseek/deepseek-chat",
    "deepseek-chat:free":            "deepseek/deepseek-chat:free",
    "deepseek/deepseek-chat:free":   "deepseek/deepseek-chat:free",
    "deepseek-chat-v3-0324":         "deepseek/deepseek-chat-v3-0324",
    "deepseek-chat-v3-0324:free":    "deepseek/deepseek-chat-v3-0324:free",
    "deepseek/deepseek-chat-v3-0324:free": "deepseek/deepseek-chat-v3-0324:free",
}

# --- Helfer: Eingabe normalisieren ---
def normalize_payload(data: dict) -> dict:
    data = dict(data or {})

    # 1) prompt/input -> messages
    if "messages" not in data:
        txt = data.get("prompt") or data.get("input")
        if isinstance(txt, list):
            txt = " ".join(map(str, txt))
        if isinstance(txt, str) and txt.strip():
            data["messages"] = [{"role": "user", "content": txt.strip()}]

    # 2) content-Listenteile zu String (sicher)
    if isinstance(data.get("messages"), list):
        norm_msgs = []
        for m in data["messages"]:
            role = m.get("role", "user")
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join([p.get("text","") if isinstance(p, dict) else str(p) for p in c])
            norm_msgs.append({"role": role, "content": c})
        data["messages"] = norm_msgs

    # 3) Model-Alias anwenden
    slug = data.get("model") or DEFAULT_MODEL
    slug = MODEL_ALIASES.get(slug, slug)
    data["model"] = slug

    # 4) Streaming standardmäßig aus (Janitor kann non-stream gut lesen)
    if "stream" not in data:
        data["stream"] = False

    return data

# --- Routen ---

@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "endpoint": "v1/chat/completions"})

@app.route("/health", methods=["GET"])
def health():
    code = "ok-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return jsonify({"ok": True, "code": code})

@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def chat_completions():
    # OPTIONS (Preflight) erledigt flask_cors automatisch; lassen wir zu
    if request.method == "OPTIONS":
        return Response(status=204)

    if not OPENROUTER_KEY:
        return jsonify({"error": "OPENROUTER_KEY fehlt auf dem Server."}), 500

    try:
        in_data = request.get_json(silent=True) or {}
        payload = normalize_payload(in_data)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            # Optional, aber manchmal hilfreich:
            "HTTP-Referer": "https://janitorai.com",
            "X-Title": "JanitorAI-Proxy",
        }

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=45,
        )

        # Response 1:1 an den Browser weiterreichen
        resp = Response(r.content, status=r.status_code)
        # Wichtig: Content-Type mitgeben, damit Janitor/Browser korrekt parsen
        ct = r.headers.get("Content-Type")
        if ct: resp.headers["Content-Type"] = ct
        return resp

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/tester", methods=["GET"])
def tester():
    # Simple Browser-Seite zum Testen per Handy
    return """
<!DOCTYPE html>
<html lang="de"><meta charset="utf-8">
<title>Proxy Tester</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:24px auto;padding:0 12px">
<h2>Proxy Tester</h2>
<p>Testet <code>/v1/chat/completions</code> direkt vom Browser. Dein Server-Key bleibt <b>serverseitig</b>.</p>
<textarea id="payload" rows="10" style="width:100%;font-family:monospace">
{
  "model": "deepseek/deepseek-chat:free",
  "messages": [{"role": "user", "content": "Sag nur: Hallo von Darkas!"}]
}
</textarea><br><br>
<button id="btn">Senden</button>
<pre id="out" style="white-space:pre-wrap;background:#111;color:#eee;padding:12px;border-radius:8px;min-height:120px;margin-top:12px"></pre>
<script>
const btn=document.getElementById('btn'), out=document.getElementById('out'), ta=document.getElementById('payload');
btn.onclick=async ()=>{
  out.textContent='Bitte warten…';
  try {
    const res = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: ta.value
    });
    const text = await res.text();
    out.textContent = 'Status: ' + res.status + '\\n\\n' + text;
  } catch (e) {
    out.textContent = 'Fetch-Fehler: ' + e;
  }
};
</script>
</body></html>
    """

# Lokaler Start (Render nutzt gunicorn, aber das hier schadet nicht)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
