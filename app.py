#!/usr/bin/env python3
"""
N.O.M.A.D — Web Interface v6
Entry point: Flask app + routes. Logic lives in modules/.
"""
import base64
import json
import logging
import math
import os
import random
import subprocess
import tempfile
import threading
import time

import requests as req
from flask import Flask, Response, jsonify, request
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from config import (
    COLLECTION, DOZZLE_URL, KB_CLEANER_DRY_RUN, KB_CLEANER_INTERVAL_HOURS,
    LLAMA_URL, MAX_HISTORY, MAX_CHUNK_LEN, MAX_RESULTS, NOMAD_HOST, PIPER_BIN,
    PIPER_MODEL, QDRANT_HOST, QDRANT_PORT, SCORE_THRESHOLD, STATS_URL,
    VOICE_URL, WHISPER_URL, XPS13_HOST,
)
from modules.canvas import (
    PATCH_SYSTEM, build_canvas_context, canvas_edit_gen, canvas_new_gen,
    detect_canvas_update, is_canvas_edit_intent, is_code_create_intent,
)
from modules.embeddings import get_embedding
from modules.helpers import HDRS, NO_ANS, get_pi_stats, sse
from modules.llm import (
    contextualize_question, helper_llm, stream_llm, stream_llm_canvas,
    stream_llm_with_canvas_detect,
)
from modules.rag import validate_and_index
from modules.agent import AGENT_SYSTEM, AGENT_TOOLS, registry
from modules.kb_cleaner import KBCleaner, set_instance as _register_cleaner
from modules.kb_manager import kb_bp

app = Flask(__name__)
app.register_blueprint(kb_bp)
os.makedirs(os.path.expanduser("~/nomad-uploads"), exist_ok=True)

# ── KB Cleaner (background thread) ───────────────────────────────────────────
_kb_cleaner = KBCleaner(
    client=QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT),
    dry_run=KB_CLEANER_DRY_RUN,
    interval_hours=KB_CLEANER_INTERVAL_HOURS,
)
_kb_cleaner.start()
_register_cleaner(_kb_cleaner)

# ── Static pages ─────────────────────────────────────────────────────────────
_html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
HTML_PAGE = open(_html_path).read()
HTML_PAGE = HTML_PAGE.replace("DOZZLE_PLACEHOLDER", DOZZLE_URL)
HTML_PAGE = HTML_PAGE.replace("NOMAD_PLACEHOLDER", f"http://{NOMAD_HOST}:8080")

try:
    VOICE_PAGE = open(os.path.expanduser("~/nomad-static/voice.html")).read()
except Exception:
    VOICE_PAGE = "<h1>Voice page not found</h1>"


# ── Main pages ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


@app.route("/voice")
def voice_page():
    return VOICE_PAGE


# ── Voice routes ──────────────────────────────────────────────────────────────

@app.route("/voice-proxy", methods=["POST"])
def voice_proxy():
    if "audio" not in request.files:
        return Response(
            "data: " + json.dumps({"type": "error", "message": "No audio"}) + "\n\n",
            content_type="text/event-stream",
        )
    audio = request.files["audio"]
    voice = request.form.get("voice", "lessac")
    try:
        files = {"audio": (audio.filename, audio.stream, audio.content_type)}
        resp  = req.post(VOICE_URL + "/voice-chat", files=files, data={"voice": voice}, stream=True, timeout=60)

        def relay():
            for line in resp.iter_lines():
                if line:
                    yield line.decode("utf-8") + "\n"

        return Response(relay(), content_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception as e:
        return Response(
            "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n",
            content_type="text/event-stream",
        )


@app.route("/voice-tts", methods=["POST"])
def voice_tts():
    text  = request.json.get("text", "")
    voice = request.json.get("voice", "lessac")
    if not text:
        return jsonify({"error": "No text"}), 400
    try:
        r = req.post(VOICE_URL + "/tts", json={"text": text, "voice": voice}, timeout=30)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/voice-clear-proxy", methods=["POST"])
def voice_clear_proxy():
    try:
        return jsonify(req.post(VOICE_URL + "/voice-clear", timeout=5).json())
    except Exception:
        return jsonify({"status": "error"})


@app.route("/tts", methods=["POST"])
def tts():
    text = request.json.get("text", "")
    if not text:
        return jsonify({"error": "No text"}), 400
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
            tp = t.name
        subprocess.run(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", tp],
            input=text, capture_output=True, text=True, timeout=30,
        )
        with open(tp, "rb") as f:
            audio = base64.b64encode(f.read()).decode("utf-8")
        os.unlink(tp)
        return jsonify({"audio": audio})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stt", methods=["POST"])
def stt():
    if "audio" not in request.files:
        return jsonify({"error": "No audio"}), 400
    a = request.files["audio"]
    try:
        files = {"file": (a.filename, a.stream, a.content_type)}
        return jsonify(
            req.post(WHISPER_URL + "/inference", files=files, data={"response_format": "json", "language": "en"}, timeout=30).json()
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── System / stats routes ─────────────────────────────────────────────────────

@app.route("/health")
def health():
    s = {"qdrant": False, "llm": False, "points": 0}
    try:
        r = req.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION}", timeout=3)
        s["qdrant"] = True
        s["points"] = r.json()["result"]["points_count"]
    except Exception:
        pass
    try:
        s["llm"] = req.get(f"{LLAMA_URL}/health", timeout=3).status_code == 200
    except Exception:
        pass
    return jsonify(s)


_FALLBACK_QUESTIONS = [
    "How do I create a list in Python?",
    "Explain Docker volumes",
    "How to set up SSH keys?",
]
_suggestions_pool:     list  = []
_suggestions_ts:       float = 0.0
_suggestions_lock      = threading.Lock()
_suggestions_building  = False
_SUGGESTIONS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "suggestions.json")

logger_sugg = logging.getLogger("suggestions")


def _load_suggestions_from_file() -> None:
    """Populate pool from persisted file so we have answers immediately on startup."""
    global _suggestions_pool, _suggestions_ts
    try:
        if not os.path.exists(_SUGGESTIONS_FILE):
            return
        with open(_SUGGESTIONS_FILE) as f:
            data = json.load(f)
        pool = [q for q in data.get("questions", []) if isinstance(q, str) and len(q) > 8]
        ts   = float(data.get("ts", 0.0))
        if len(pool) >= 3:
            with _suggestions_lock:
                _suggestions_pool = pool
                _suggestions_ts   = ts
            logger_sugg.info("Loaded %d cached suggestions (age %.0fh)", len(pool),
                             (time.time() - ts) / 3600)
    except Exception as exc:
        logger_sugg.warning("Could not load cached suggestions: %s", exc)


def _build_suggestions_pool() -> None:
    """Fetch random KB docs, ask the helper LLM for 6 example questions, persist result."""
    global _suggestions_pool, _suggestions_ts, _suggestions_building
    with _suggestions_lock:
        if _suggestions_building:
            return
        _suggestions_building = True
    try:
        logger_sugg.info("Building suggestions pool from Qdrant…")
        qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=10)
        points, _ = qclient.scroll(
            collection_name=COLLECTION, limit=20,
            with_payload=True, with_vectors=False,
        )
        if not points:
            logger_sugg.warning("Qdrant returned 0 points — suggestions unchanged")
            return
        random.shuffle(points)
        snippets = []
        for pt in points[:8]:
            pl  = pt.payload or {}
            txt = pl.get("content", pl.get("text", ""))
            ttl = pl.get("article_title", pl.get("title", ""))
            if txt:
                snippets.append((f"[{ttl}]\n" if ttl else "") + txt[:300])
        if not snippets:
            logger_sugg.warning("No content found in Qdrant payloads")
            return
        prompt = (
            "Based on these knowledge base excerpts, generate exactly 6 short, natural questions "
            "a user might ask. One question per line, no numbering, no bullets, no extra text.\n\n"
            + "\n\n".join(snippets[:6])
            + "\n\n6 questions:"
        )
        raw = helper_llm(
            [
                {"role": "system", "content": "Generate concise example questions from document content. Output only the questions, one per line."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=220,
        )
        if not raw:
            logger_sugg.warning("helper_llm returned empty response")
            return
        pool = [
            ln.strip().lstrip("•–-1234567890.) ")
            for ln in raw.splitlines() if ln.strip()
        ]
        pool = [q for q in pool if len(q) > 8][:6]
        if len(pool) < 3:
            logger_sugg.warning("Pool too small (%d questions): %r", len(pool), pool)
            return
        ts = time.time()
        with _suggestions_lock:
            _suggestions_pool = pool
            _suggestions_ts   = ts
        # Persist so the next restart doesn't need to regenerate
        try:
            os.makedirs(os.path.dirname(_SUGGESTIONS_FILE), exist_ok=True)
            with open(_SUGGESTIONS_FILE, "w") as f:
                json.dump({"questions": pool, "ts": ts}, f, indent=2)
            logger_sugg.info("Saved %d suggestions to %s", len(pool), _SUGGESTIONS_FILE)
        except Exception as exc:
            logger_sugg.warning("Could not persist suggestions: %s", exc)
    except Exception as exc:
        logger_sugg.error("Failed to build suggestions: %s", exc, exc_info=True)
    finally:
        with _suggestions_lock:
            _suggestions_building = False


# Load file-cached pool immediately, then refresh in background
_load_suggestions_from_file()
threading.Thread(target=_build_suggestions_pool, daemon=True).start()


@app.route("/suggested-questions")
def suggested_questions():
    with _suggestions_lock:
        pool      = list(_suggestions_pool)
        ts        = _suggestions_ts
        building  = _suggestions_building

    # Trigger a background refresh when pool is stale (>1 h) and not already rebuilding
    if not building and (not pool or time.time() - ts > 3600):
        threading.Thread(target=_build_suggestions_pool, daemon=True).start()

    if len(pool) >= 3:
        return jsonify({"questions": random.sample(pool, 3), "from_cache": True})

    return jsonify({"questions": _FALLBACK_QUESTIONS, "from_cache": False})


@app.route("/pi-stats")
def pi_stats():
    return jsonify(get_pi_stats())


@app.route("/desktop-stats")
def desktop_stats():
    try:
        return jsonify(req.get(f"{STATS_URL}/stats", timeout=5).json())
    except Exception:
        return jsonify({"error": "offline"}), 503


@app.route("/xps13-stats")
def xps13_stats():
    try:
        r = req.get(f"http://{XPS13_HOST}:8083/stats", timeout=3)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception:
        pass
    try:
        script = (
            "import os,json;"
            "mi=open('/proc/meminfo').read();"
            "rt=next(int(l.split()[1])//1024 for l in mi.splitlines() if l.startswith('MemTotal:'));"
            "ra=next(int(l.split()[1])//1024 for l in mi.splitlines() if l.startswith('MemAvailable:'));"
            "st=os.statvfs('/');"
            "up=float(open('/proc/uptime').read().split()[0]);"
            "ld=os.getloadavg();"
            "print(json.dumps({'hostname':os.uname().nodename,'ram_total':rt,'ram_available':ra,"
            "'disk_total':(st.f_blocks*st.f_frsize)//(1024**3),'disk_free':(st.f_bavail*st.f_frsize)//(1024**3),"
            "'load':[round(x,2) for x in ld],"
            "'uptime':str(int(up//86400))+'d '+str(int((up%86400)//3600))+'h '+str(int((up%3600)//60))+'m'}))"
        )
        encoded = base64.b64encode(script.encode()).decode()
        ssh_cmd = f'python3 -c "$(echo {encoded} | base64 -d)"'
        key     = os.path.expanduser("~/.ssh/id_ed25519")
        if not os.path.exists(key):
            key = os.path.expanduser("~/.ssh/id_rsa")
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
             "-o", "BatchMode=yes", "-i", key, f"ioncap@{XPS13_HOST}", ssh_cmd],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode == 0 and result.stdout.strip():
            return jsonify(json.loads(result.stdout.strip()))
        return jsonify({"error": "SSH failed", "detail": result.stderr[:300]}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/service-status")
def service_status():
    svcs = [
        {"name": "LLM (Qwen3 4B)",       "url": f"{NOMAD_HOST}:8081",   "machine": "desktop"},
        {"name": "Qdrant",                "url": f"{NOMAD_HOST}:6333",   "machine": "desktop"},
        {"name": "Whisper (STT)",         "url": f"{NOMAD_HOST}:8082",   "machine": "desktop"},
        {"name": "Ollama Desktop",        "url": f"{NOMAD_HOST}:11434",  "machine": "desktop"},
        {"name": "Stats",                 "url": f"{NOMAD_HOST}:8083",   "machine": "desktop"},
        {"name": "Dozzle",                "url": f"{NOMAD_HOST}:9999",   "machine": "desktop"},
        {"name": "Ollama XPS13 (embed)",  "url": f"{XPS13_HOST}:11434",  "machine": "xps13"},
        {"name": "Voice server",          "url": f"{XPS13_HOST}:8085",   "machine": "xps13"},
        {"name": "Grafana",               "url": f"{XPS13_HOST}:3000",   "machine": "xps13"},
        {"name": "Prometheus",            "url": f"{XPS13_HOST}:9090",   "machine": "xps13"},
    ]
    for s in svcs:
        try:
            s["ok"] = req.get(f"http://{s['url']}/", timeout=2).status_code < 500
        except Exception:
            s["ok"] = False
    return jsonify(svcs)


# ── Knowledge base routes ─────────────────────────────────────────────────────

@app.route("/save-to-kb", methods=["POST"])
def save_to_kb():
    q = request.json.get("question", "")
    a = request.json.get("answer", "")
    if not q or not a or len(a) < 50:
        return jsonify({"status": "error", "message": "Too short"})
    ok, msg = validate_and_index(q, a)
    return jsonify({"status": "saved" if ok else "rejected", "message": msg})


@app.route("/extract-file", methods=["POST"])
def extract_file():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f     = request.files["file"]
    fname = f.filename.lower()
    try:
        if fname.endswith(".pdf"):
            try:
                import io
                from pdfminer.high_level import extract_text_to_fp
                from pdfminer.layout import LAParams

                f.stream.seek(0)
                out = io.StringIO()
                extract_text_to_fp(f.stream, out, laparams=LAParams(), output_type="text", codec="utf-8")
                text = out.getvalue().strip()
                f.stream.seek(0)
                pages = f.stream.read().count(b"/Page ")
                return jsonify({"text": text[:50000], "pages": pages, "truncated": len(text) > 50000})
            except ImportError:
                try:
                    import io
                    import pypdf

                    f.stream.seek(0)
                    reader = pypdf.PdfReader(f.stream)
                    text   = "\n\n".join(p.extract_text() or "" for p in reader.pages)
                    return jsonify({"text": text[:50000], "pages": len(reader.pages), "truncated": len(text) > 50000})
                except ImportError:
                    return jsonify({"error": "No PDF library. Install: pip install pdfminer.six --break-system-packages"}), 500
        else:
            text = f.read().decode("utf-8", errors="replace")
            return jsonify({"text": text[:100000], "pages": 1, "truncated": len(text) > 100000})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Knowledge Base Browser (Management) routes ─────────────────────────────────

def _get_qdrant_client():
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


@app.route("/kb/stats")
def kb_stats():
    """Uitgebreide statistieken over de collectie."""
    try:
        client = _get_qdrant_client()
        info = client.get_collection(COLLECTION)
        points_count = client.count(COLLECTION).count
        stats = {
            "name": COLLECTION,
            "points_count": points_count,
            "status": info.status,
            "vector_size": info.config.params.vectors.size,
            "distance": str(info.config.params.vectors.distance),
            "indexed_vectors_count": getattr(info, 'indexed_vectors_count', points_count)
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/documents")
def list_documents():
    """Lijst van documenten met paginering en optionele zoekterm."""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        query = request.args.get('q', '').strip()

        client = _get_qdrant_client()
        # Scroll door alle punten
        all_points = []
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            all_points.extend(points)
            if next_offset is None:
                break
            offset = next_offset

        # Filter op zoekterm
        if query:
            query_lower = query.lower()
            filtered = []
            for p in all_points:
                payload = p.payload or {}
                title = payload.get('article_title', '').lower()
                content = payload.get('content', '').lower()
                if query_lower in title or query_lower in content:
                    filtered.append(p)
            all_points = filtered

        total = len(all_points)
        total_pages = math.ceil(total / per_page) if total > 0 else 1
        start = (page - 1) * per_page
        end = start + per_page
        page_points = all_points[start:end]

        documents = []
        for p in page_points:
            payload = p.payload or {}
            content = payload.get('content', '')
            documents.append({
                "id": p.id,
                "title": payload.get('article_title', 'Untitled'),
                "content_preview": content[:200] + ('...' if len(content) > 200 else ''),
                "source": payload.get('source', 'unknown'),
                "created_at": payload.get('generated_at', ''),
                "score": None
            })

        return jsonify({
            "documents": documents,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": total_pages
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/documents/<doc_id>", methods=["GET"])
def get_document(doc_id):
    """Haal volledige inhoud van één document op."""
    try:
        client = _get_qdrant_client()
        points = client.retrieve(
            collection_name=COLLECTION,
            ids=[doc_id],
            with_payload=True,
            with_vectors=False
        )
        if not points:
            return jsonify({"error": "Document not found"}), 404
        p = points[0]
        payload = p.payload or {}
        return jsonify({
            "id": p.id,
            "payload": payload,
            "content": payload.get('content', ''),
            "title": payload.get('article_title', 'Untitled')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    """Verwijder een document uit de collectie."""
    try:
        client = _get_qdrant_client()
        client.delete(
            collection_name=COLLECTION,
            points_selector=qdrant_models.PointIdsList(
                points=[doc_id]
            )
        )
        return jsonify({"status": "deleted", "id": doc_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/purge", methods=["POST"])
def purge_collection():
    """Verwijder alle documenten uit de collectie (bevestiging vereist)."""
    try:
        data = request.get_json()
        if not data or data.get('confirm') != 'yes':
            return jsonify({"error": "Confirmation required"}), 400

        client = _get_qdrant_client()
        # Hercreëer de collectie
        client.delete_collection(COLLECTION)
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qdrant_models.VectorParams(
                size=768,  # nomic-embed-text dimensie
                distance=qdrant_models.Distance.COSINE
            )
        )
        return jsonify({"status": "collection purged and recreated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/kb/export", methods=["GET"])
def export_collection():
    """Exporteer alle documenten als JSON (download)."""
    try:
        client = _get_qdrant_client()
        all_points = []
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            all_points.extend(points)
            if next_offset is None:
                break
            offset = next_offset

        export_data = []
        for p in all_points:
            export_data.append({
                "id": p.id,
                "payload": p.payload
            })

        return jsonify(export_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Tool Config API ───────────────────────────────────────────────────────────

@app.route("/api/tools", methods=["GET"])
def api_tools_list():
    """Geeft alle tools terug met naam, beschrijving, enabled-vlag en parameters."""
    return jsonify(registry.list_tools())


@app.route("/api/tools/<tool_name>", methods=["POST"])
def api_tools_update(tool_name):
    """Werkt de parameters van een tool bij (body: JSON met nieuwe waarden)."""
    data = request.get_json() or {}
    if registry.update_config(tool_name, params=data):
        return jsonify({"status": "ok", "tool": tool_name})
    return jsonify({"error": f"Tool '{tool_name}' not found"}), 404


@app.route("/api/tools/<tool_name>/enable", methods=["POST"])
def api_tools_enable(tool_name):
    """Zet een tool aan of uit.  Body: {"enabled": true|false}"""
    data = request.get_json() or {}
    enabled = bool(data.get("enabled", True))
    if registry.update_config(tool_name, enabled=enabled):
        return jsonify({"status": "ok", "tool": tool_name, "enabled": enabled})
    return jsonify({"error": f"Tool '{tool_name}' not found"}), 404


@app.route("/api/tools/<tool_name>/docs", methods=["GET"])
def api_tools_docs(tool_name):
    """Geeft uitgebreide documentatie en voorbeeldprompt voor een tool."""
    tool = registry.get_tool(tool_name)
    if not tool:
        return jsonify({"error": f"Tool '{tool_name}' not found"}), 404
    return jsonify({
        "name":    tool_name,
        "help":    tool["help"],
        "example": tool["example"],
    })


@app.route("/kb/clean", methods=["POST"])
def kb_clean():
    """Handmatig een KB-opschoonsessie starten.

    Query params:
        dry_run=true|false  – overschrijft de geconfigureerde waarde voor deze run.
    """
    try:
        dry_run_param = request.args.get("dry_run")
        original_dry_run = _kb_cleaner.dry_run
        if dry_run_param is not None:
            _kb_cleaner.dry_run = dry_run_param.lower() != "false"

        stats = _kb_cleaner.clean()

        # Restore original setting so the scheduled runs are unaffected.
        _kb_cleaner.dry_run = original_dry_run
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat_ep():
    q          = request.json.get("question", "")
    h          = request.json.get("history", [])
    canvas     = request.json.get("canvas_content", None)
    image_data = request.json.get("image_data", None)
    image_type = request.json.get("image_type", "image/jpeg")
    if not q:
        return Response(sse("error", message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(q, canvas):
            yield from canvas_edit_gen(q, canvas)
            return

        if not canvas and is_code_create_intent(q):
            yield from canvas_new_gen(q)
            return

        yield sse("search_status", message="Thinking...")
        sys_prompt = "You are N.O.M.A.D, a helpful AI assistant running locally. Be friendly, concise, thoughtful."
        sys_prompt += "\n\n" + build_canvas_context(canvas)

        msgs = [{"role": "system", "content": sys_prompt}]
        for m in h[-MAX_HISTORY:]:
            msgs.append({"role": m["role"], "content": m["content"]})

        if image_data:
            msgs.append({"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_data}"}},
                {"type": "text", "text": q},
            ]})
        else:
            msgs.append({"role": "user", "content": q})

        yield from stream_llm_with_canvas_detect(msgs)
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)


# ── RAG (ask) endpoint ────────────────────────────────────────────────────────

@app.route("/ask", methods=["POST"])
def ask():
    question   = request.json.get("question", "")
    history    = request.json.get("history", [])
    canvas     = request.json.get("canvas_content", None)
    if not question:
        return Response(sse("error", message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(question, canvas):
            yield from canvas_edit_gen(question, canvas)
            return

        if not canvas and is_code_create_intent(question):
            yield from canvas_new_gen(question)
            return

        search_question = question
        if history:
            yield sse("search_status", message="Understanding context...")
            search_question = contextualize_question(question, history)

        yield sse("search_status", message="Searching knowledge base...")
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            seen = set(); ctx = []; sources = []
            try:
                emb = get_embedding(search_question)
            except Exception:
                yield sse("error", message="Embedding failed")
                return

            for col in client.get_collections().collections:
                try:
                    res = client.query_points(collection_name=col.name, query=emb, limit=MAX_RESULTS)
                    for r in res.points:
                        if r.score > SCORE_THRESHOLD and r.id not in seen:
                            seen.add(r.id)
                            pl    = r.payload or {}
                            title = pl.get("article_title", "?")
                            cont  = pl.get("content", pl.get("text", str(pl)))
                            ctx.append("[" + title + "]\n" + cont[:MAX_CHUNK_LEN])
                            if title not in sources:
                                sources.append(title)
                except Exception:
                    pass
            ctx     = ctx[:6]
            sources = sources[:6]
        except Exception as e:
            yield sse("error", message="Search: " + str(e))
            return

        yield sse("sources", sources=sources)

        sys_prompt = (
            "You are N.O.M.A.D, a knowledgeable AI assistant. Answer using the provided reference material. "
            "Synthesize from multiple sources when possible. Be accurate and clear. "
            "If the material doesn't cover the question, say what you can and indicate what's missing."
        )
        sys_prompt += "\n\n" + build_canvas_context(canvas)

        if not ctx:
            yield sse("token", token="No relevant documents found.\n\n---\n*Answering from my own knowledge...*\n\n")
            yield sse("fallback_start")
            msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": question}]
            full = []
            for chunk in stream_llm_with_canvas_detect(msgs):
                yield chunk
                try:
                    d = json.loads(chunk.replace("data: ", "").strip())
                    if d.get("type") == "token":
                        full.append(d["token"])
                except Exception:
                    pass
            yield sse("fallback_done", question=question)
            yield sse("done")
            return

        yield sse("search_status", message=f"Generating from {len(ctx)} sources...")
        context = "\n\n---\n\n".join(ctx)
        msgs    = [{"role": "system", "content": sys_prompt}]
        for m in history[-4:]:
            msgs.append({"role": m["role"], "content": m["content"][:300]})
        msgs.append({"role": "user", "content": "Reference material:\n" + context + "\n\nQuestion: " + question})

        collected = []
        for chunk in stream_llm_with_canvas_detect(msgs):
            yield chunk
            try:
                d = json.loads(chunk.replace("data: ", "").strip())
                if d.get("type") == "token":
                    collected.append(d["token"])
            except Exception:
                pass

        full = "".join(collected)

        if any(p in full.lower() for p in NO_ANS):
            yield sse("token", token="\n\n---\n*Searching my own knowledge...*\n\n")
            yield sse("fallback_start")
            fb_sys = (
                "You are N.O.M.A.D. The knowledge base didn't have a good answer. "
                "Answer using your own knowledge. Be concise and helpful.\n\n"
                + build_canvas_context(None)
            )
            fb_msgs = [
                {"role": "system", "content": fb_sys},
                {"role": "user", "content": question},
            ]
            for chunk in stream_llm_with_canvas_detect(fb_msgs):
                yield chunk
            yield sse("fallback_done", question=question)

        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)


# ── Canvas routes ─────────────────────────────────────────────────────────────

@app.route("/canvas-patch", methods=["POST"])
def canvas_patch():
    import re
    question = request.json.get("question", "")
    canvas   = request.json.get("canvas_content", "")
    if not question or not canvas:
        return jsonify({"error": "Missing question or canvas"}), 400

    doc = canvas[:5000]
    try:
        r = req.post(
            LLAMA_URL + "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": PATCH_SYSTEM},
                    {"role": "user",   "content": f"Document:\n```\n{doc}\n```\n\nInstruction: {question}\n\nJSON array of ops:"},
                ],
                "max_tokens": 1200,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=60,
        )
        raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
        ops = json.loads(raw)
        if not isinstance(ops, list):
            raise ValueError("Not a list")
        valid = [op for op in ops if isinstance(op, dict) and "op" in op]
        return jsonify({"ops": valid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/canvas-generate", methods=["POST"])
def canvas_gen():
    import re
    question = request.json.get("question", "")
    canvas   = request.json.get("canvas_content", None)
    if not question:
        return Response(sse("error", message="No question"), content_type="text/event-stream")

    match  = re.match(r"^(?:write to canvas|canvas write|generate|create):\s*([\s\S]+)", question, re.IGNORECASE)
    prompt = match.group(1) if match else question

    def gen():
        pl = prompt.lower()
        if any(x in pl for x in ["python", "script", "def ", "class "]):
            fn = "generated.py"
        elif any(x in pl for x in ["javascript", "node", "react", "function"]):
            fn = "generated.js"
        elif any(x in pl for x in ["html", "webpage", "website"]):
            fn = "generated.html"
        elif any(x in pl for x in ["bash", "shell", "#!/"]):
            fn = "generated.sh"
        else:
            fn = "generated.md"

        sys_prompt = "Write the requested content directly. No preamble. Clean, well-formatted text or code. Use markdown where appropriate."
        if canvas:
            sys_prompt += f"\n\nThe user currently has this in the canvas:\n```\n{canvas[:2000]}\n```\nIf asked to update/improve it, write the complete updated version."

        msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]

        yield sse("canvas_start", filename=fn)
        yield from stream_llm_canvas(msgs)
        yield sse("canvas_done", filename=fn)
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)


# ── Agent endpoint ────────────────────────────────────────────────────────────

@app.route("/agent", methods=["POST"])
def agent():
    import re
    question = request.json.get("question", "")
    history  = request.json.get("history", [])
    canvas   = request.json.get("canvas_content", None)
    if not question:
        return Response(sse("error", message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(question, canvas):
            yield from canvas_edit_gen(question, canvas)
            return

        if not canvas and is_code_create_intent(question):
            yield from canvas_new_gen(question)
            return

        sys_content = AGENT_SYSTEM
        if canvas:
            sys_content += f"\n\nCanvas context (user's open document):\n```\n{canvas[:3000]}\n```"

        msgs = [{"role": "system", "content": sys_content}]
        for m in history[-MAX_HISTORY:]:
            msgs.append({"role": m["role"], "content": m["content"][:500]})
        msgs.append({"role": "user", "content": question})

        for iteration in range(6):
            yield sse("search_status", message=f"Agent thinking... (step {iteration + 1})")
            try:
                r = req.post(
                    LLAMA_URL + "/v1/chat/completions",
                    json={
                        "messages": msgs,
                        "max_tokens": 700,
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                    timeout=60,
                )
                response_text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            except Exception as e:
                yield sse("error", message=f"LLM error: {e}")
                return

            tool_match = re.search(r'\{\s*"tool"\s*:', response_text)

            if tool_match:
                try:
                    json_start  = response_text.index("{", tool_match.start())
                    brace_count = 0
                    json_end    = json_start
                    for ci, ch in enumerate(response_text[json_start:]):
                        if ch == "{":
                            brace_count += 1
                        elif ch == "}":
                            brace_count -= 1
                        if brace_count == 0:
                            json_end = json_start + ci + 1
                            break

                    tool_json = json.loads(response_text[json_start:json_end])
                    tool_name = tool_json.get("tool", "")
                    tool_args = tool_json.get("args", {})

                    before = response_text[:json_start].strip()
                    if before:
                        yield sse("token", token=before + "\n\n")

                    yield sse("search_status", message=f"Running {tool_name}...")
                    # Broadcast the call so the UI can render a collapsible detail.
                    _args_preview = json.dumps(tool_args)[:200] if tool_args else ""
                    yield sse("tool_call", tool=tool_name, args=_args_preview)

                    tool_result = registry.execute(tool_name, tool_args)

                    # (filename, code_fence_lang)
                    _canvas_tools = {
                        "network_scan":          ("network_scan.md",      ""),
                        "network_scan_advanced": ("network_scan.md",      ""),
                        "port_scan":             ("port_scan.md",         ""),
                        "vuln_scan":             ("vuln_scan.md",         ""),
                        "system_status":         ("system_status.md",     ""),
                        "search_kb":             ("search_results.md",    ""),
                        "news_headlines":        ("headlines.md",         ""),
                        "hacker_news":           ("hacker_news.md",       ""),
                        "kb_cleaner_run":        ("kb_cleaner.md",        ""),
                        "list_tools":            ("tools.md",             ""),
                        "docker_status":         ("docker_status.md",     ""),
                        "run_command":           ("command_output.md",    "bash"),
                        "wikipedia":             ("wikipedia.md",         ""),
                    }
                    if len(tool_result) > 400 and tool_name in _canvas_tools:
                        fn, code_lang = _canvas_tools[tool_name]
                        # Check tool's own open_in_new_tab config setting
                        tool_cfg = registry.get_tool(tool_name)
                        open_new = bool((tool_cfg or {}).get("params", {}).get("open_in_new_tab", False))
                        if open_new:
                            yield sse("canvas_new_tab", content=tool_result,
                                      filename=fn, code_lang=code_lang)
                        else:
                            yield sse("canvas_append", content=tool_result,
                                      filename=fn, code_lang=code_lang,
                                      header=f"## {tool_name}")
                        yield sse("token", token=f"*Results appended to canvas ({len(tool_result)} chars).*\n\n")
                        tool_result = f"(written to canvas, {len(tool_result)} chars)"

                    # Send result preview to UI (first 600 chars shown in detail).
                    yield sse("tool_result", tool=tool_name,
                              result=tool_result[:600] + ("…" if len(tool_result) > 600 else ""))

                    msgs.append({"role": "assistant", "content": response_text})
                    msgs.append({"role": "user",      "content": f"Tool result for {tool_name}:\n{tool_result}"})

                except (json.JSONDecodeError, ValueError):
                    for token in response_text.split():
                        yield sse("token", token=token + " ")
                    yield sse("done")
                    return
            else:
                for token in response_text.split():
                    yield sse("token", token=token + " ")
                yield sse("done")
                return

        yield sse("token", token="\n\n*Max iterations reached.*")
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from config import EMBED_URL
    print()
    print("  * N.O.M.A.D - Web Interface v6")
    print("  v6 Canvas: tabs, split, undo/redo, line numbers, diff")
    print(f"  Qdrant:     {QDRANT_HOST}:{QDRANT_PORT}")
    print(f"  Embeddings: {EMBED_URL}")
    print(f"  LLM:        {LLAMA_URL}")
    print(f"  Whisper:    {WHISPER_URL}")
    print(f"  Stats:      {STATS_URL}")
    print()
    print("  Open https://raspberrypi.local:5000")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False)
