#!/usr/bin/env python3
"""
N.O.M.A.D — Web Interface v5 + Canvas Integration
Canvas works as a shared context window: LLM can read AND write to it.
"""
import os, json, time, hashlib, subprocess, tempfile, base64, re
import functools
import requests as req
from flask import Flask, request, Response, jsonify
from qdrant_client import QdrantClient, models

# Laad .env configuratie
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
os.makedirs(os.path.expanduser("~/nomad-uploads"), exist_ok=True)

# ═══ Config (uit .env of fallback) ═══════════════════════════════════════
NOMAD_HOST = os.getenv("NOMAD_HOST", "nomad.home")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.2.20:11434")
OLLAMA_URL = f"http://{NOMAD_HOST}:11434"
HELPER_URL = os.getenv("HELPER_URL", "http://192.168.2.20:11434")
HELPER_MODEL = os.getenv("HELPER_MODEL", "qwen2.5:1.5b")
LLAMA_URL = f"http://{NOMAD_HOST}:8081"
QDRANT_HOST = os.getenv("QDRANT_HOST", "nomad.home")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
WHISPER_URL = f"http://{NOMAD_HOST}:8082"
STATS_URL = f"http://{NOMAD_HOST}:8083"
DOZZLE_URL = f"http://{NOMAD_HOST}:9999"
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://192.168.2.20:3000")
PIPER_MODEL = os.getenv("PIPER_MODEL", os.path.expanduser("~/piper-voices/en_US-lessac-medium.onnx"))
PIPER_BIN = os.getenv("PIPER_BIN", os.path.expanduser("~/tinybert-env/bin/piper"))
VOICE_URL = os.getenv("VOICE_URL", "http://192.168.2.20:8085")
XPS13_HOST = os.getenv("XPS13_HOST", "192.168.2.20")
XPS13_STATS_URL = f"http://{XPS13_HOST}:8083"
COLLECTION = os.getenv("COLLECTION", "nomad_knowledge_base")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.15"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "6"))
MAX_CHUNK_LEN = int(os.getenv("MAX_CHUNK_LEN", "500"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))

# ═══ Embedding cache ═══════════════════════════════════════════════════════
@functools.lru_cache(maxsize=128)
def get_embedding(text: str):
    """Haalt embedding op van de XPS13 embed-server, met caching."""
    try:
        r = req.post(f"{EMBED_URL}/api/embed",
                     json={"model": "nomic-embed-text:v1.5", "input": text},
                     timeout=30)
        return r.json()["embeddings"][0]
    except Exception as e:
        print(f"Embedding error: {e}")
        raise

# ═══ HTML ═════════════════════════════════════════════════
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>N.O.M.A.D v6</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Mono:wght@300;400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,600;1,8..60,300;1,8..60,400&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<link id="prism-theme" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />
<style>
:root,.dark{
  --bg:#1a1a1e;--bg2:#222226;--bg3:#2a2a2f;
  --border:#363640;--border2:#2e2e38;
  --t1:#e8e6e3;--t2:#9d9b97;--t3:#6b6966;
  --accent:#c49a6c;--accent2:#8b7355;--accentg:rgba(196,154,108,0.08);
  --chat:#7a9ec4;--chat2:#557799;--chatg:rgba(122,158,196,0.08);
  --ok:#7d9e7a;--err:#c47070;--warn:#c4a86c;
  --code:#1e1e22;--scroll:#363640;
  --cv-active:#4a9e6a;--cv-activeg:rgba(74,158,106,0.12);
  --r:12px;--rs:8px;--tr:0.2s cubic-bezier(0.4,0,0.2,1);
}
.light{--bg:#f5f5f5;--bg2:#fff;--bg3:#eee;--border:#ddd;--border2:#ccc;--t1:#1a1a1e;--t2:#555;--t3:#888;--accent:#8b5e3c;--accent2:#6b4423;--accentg:rgba(139,94,60,0.08);--chat:#557799;--ok:#5a8f5a;--code:#f0f0f0;--scroll:#ccc;--cv-active:#3a8f5a;--cv-activeg:rgba(58,143,90,0.08);}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:var(--bg);color:var(--t1);font-family:'Source Serif 4',Georgia,serif;font-size:16px;line-height:1.7;overflow:hidden;transition:background 0.3s,color 0.3s}
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--scroll);border-radius:3px}
.app{display:flex;height:100vh;position:relative}
.chat-panel{display:flex;flex-direction:column;flex:1;transition:margin-right var(--tr)}
.chat-inner{max-width:780px;width:100%;margin:0 auto;display:flex;flex-direction:column;height:100%;padding:0 24px}
.toast-container{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:1000;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none}
.toast{background:var(--bg2);border:1px solid var(--border);border-radius:20px;padding:8px 20px;font-family:'DM Mono',monospace;font-size:11px;color:var(--t2);box-shadow:0 4px 12px rgba(0,0,0,0.2);animation:toastIn 0.3s ease}
@keyframes toastIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.canvas-panel{position:fixed;top:0;right:-600px;width:600px;min-width:400px;max-width:900px;height:100vh;background:var(--bg);border-left:1px solid var(--border);display:flex;flex-direction:column;transition:right 0.3s cubic-bezier(0.4,0,0.2,1);z-index:50;box-shadow:-4px 0 24px rgba(0,0,0,0.3)}
.canvas-panel.open{right:0}
.cv-tab-bar{display:flex;align-items:center;background:var(--bg2);border-bottom:1px solid var(--border2);flex-shrink:0}
.cv-tabs-container{display:flex;flex:1;overflow-x:auto}
.cv-tab-item{display:flex;align-items:center;gap:6px;padding:8px 12px;font-family:'DM Mono',monospace;font-size:11px;color:var(--t3);border-right:1px solid var(--border2);cursor:pointer;white-space:nowrap;user-select:none}
.cv-tab-item:hover{background:var(--bg3);color:var(--t2)}.cv-tab-item.active{background:var(--bg);color:var(--accent);border-bottom:2px solid var(--accent)}
.cv-tab-close{margin-left:4px;opacity:0.5;cursor:pointer;font-size:14px}.cv-tab-close:hover{opacity:1;color:var(--err)}
.cv-new-tab{display:flex;align-items:center;justify-content:center;width:32px;height:32px;font-size:18px;color:var(--t3);cursor:pointer;flex-shrink:0}.cv-new-tab:hover{background:var(--bg3);color:var(--t2)}
.cv-head{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;border-bottom:1px solid var(--border2);flex-shrink:0}
.cv-title{font-family:'DM Mono',monospace;font-size:12px;color:var(--t2);display:flex;align-items:center;gap:8px}
.cv-toolbar{display:flex;gap:4px;padding:4px 16px;background:var(--bg2);border-bottom:1px solid var(--border2);flex-shrink:0;flex-wrap:wrap;align-items:center}
.cv-toolbar-btn{font-family:'DM Mono',monospace;font-size:10px;padding:4px 8px;border:1px solid var(--border);border-radius:12px;background:transparent;color:var(--t3);cursor:pointer;transition:all var(--tr)}.cv-toolbar-btn:hover{color:var(--t2);border-color:var(--t3);background:var(--bg3)}
.cv-body{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative}
.cv-split-container{display:flex;flex:1;overflow:hidden}
.cv-split .cv-edit{flex:1;border-right:1px solid var(--border)}.cv-split .cv-prev-inner{flex:1;display:block!important;padding:20px 24px;overflow-y:auto}
.cv-edit{flex:1;overflow:auto;background:var(--code);display:flex;position:relative}
.cv-line-numbers{width:50px;background:var(--bg2);color:var(--t3);font-family:'JetBrains Mono',monospace;font-size:13px;line-height:1.7;padding:16px 8px;text-align:right;user-select:none;border-right:1px solid var(--border);overflow:hidden;flex-shrink:0}
.cv-edit textarea{flex:1;height:100%;background:transparent;border:none;outline:none;color:var(--t1);font-family:'JetBrains Mono',monospace;font-size:13px;line-height:1.7;padding:16px 20px;resize:none;tab-size:2;transition:background 0.4s}
.cv-edit textarea.writing{background:#1a2420}
.cv-minimap{position:absolute;right:0;top:0;width:60px;height:100%;background:var(--bg2);opacity:0.4;overflow:hidden;z-index:10;pointer-events:none}
.cv-minimap-content{font-size:2px;line-height:1;color:var(--t2);white-space:pre-wrap;word-break:break-all;padding:4px}
.cv-writing-indicator{display:none;position:absolute;top:8px;right:68px;font-family:'DM Mono',monospace;font-size:9px;color:var(--cv-active);background:var(--cv-activeg);border:1px solid rgba(74,158,106,0.3);padding:3px 10px;border-radius:20px;z-index:5}.cv-writing-indicator.visible{display:block}
.cv-prev-inner{display:none;padding:20px 24px;overflow-y:auto}.cv-prev-inner h1,.cv-prev-inner h2,.cv-prev-inner h3{font-family:'Instrument Serif',serif;margin:16px 0 8px}.cv-prev-inner pre{background:var(--code);border:1px solid var(--border);border-radius:var(--rs);padding:14px;margin:10px 0;overflow-x:auto}.cv-prev-inner code{font-family:'JetBrains Mono',monospace;font-size:13px;background:var(--code);padding:2px 6px;border-radius:4px;color:var(--accent)}
.cv-ctx-bar{display:none;align-items:center;gap:8px;padding:6px 16px;background:var(--cv-activeg);border-bottom:1px solid rgba(74,158,106,0.25);font-family:'DM Mono',monospace;font-size:10px;color:var(--cv-active);flex-shrink:0}.cv-ctx-bar.visible{display:flex}
.cv-ctx-dot{width:5px;height:5px;border-radius:50%;background:var(--cv-active);animation:pulse 2s ease-in-out infinite}
.cv-goal-bar{height:3px;background:var(--border);margin:0 16px 8px;border-radius:3px;overflow:hidden}.cv-goal-progress{height:100%;width:0%;background:var(--cv-active);transition:width 0.3s}
.cv-diff{display:none;flex-direction:column;flex:1;overflow:hidden}.cv-diff.visible{display:flex}
.cv-diff-toolbar{display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid var(--border2);flex-shrink:0;background:var(--bg2)}.cv-diff-toolbar span{font-family:'DM Mono',monospace;font-size:10px;color:var(--t3);flex:1}
.cv-diff-btn{font-family:'DM Mono',monospace;font-size:10px;padding:3px 10px;border-radius:16px;border:1px solid var(--border);background:transparent;cursor:pointer;transition:all var(--tr)}.cv-diff-btn.accept-all{color:var(--ok);border-color:var(--ok)}.cv-diff-btn.reject-all{color:var(--err);border-color:var(--err)}
.cv-diff-body{flex:1;overflow-y:auto;padding:8px 0}
.diff-op{border:1px solid var(--border);border-radius:var(--rs);margin:6px 12px;overflow:hidden}.diff-op-head{display:flex;align-items:center;gap:8px;padding:5px 10px;background:var(--bg2);border-bottom:1px solid var(--border)}.diff-op-label{font-family:'DM Mono',monospace;font-size:9px;text-transform:uppercase;padding:1px 6px;border-radius:20px}.diff-op-label.replace{background:rgba(196,154,108,0.2);color:var(--accent)}.diff-op-label.insert{background:rgba(125,158,122,0.2);color:var(--ok)}.diff-op-label.delete{background:rgba(196,112,112,0.2);color:var(--err)}
.diff-op-acts{margin-left:auto;display:flex;gap:4px}.diff-op-act{font-family:'DM Mono',monospace;font-size:9px;padding:2px 8px;border-radius:12px;border:1px solid var(--border);background:transparent;cursor:pointer;color:var(--t3);transition:all var(--tr)}.diff-op-act.acc{color:var(--ok);border-color:rgba(125,158,122,0.4)}.diff-op-act.rej{color:var(--err);border-color:rgba(196,112,112,0.4)}.diff-op-act.done{opacity:0.4;pointer-events:none}
.diff-op-body{padding:6px 10px;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.6}.diff-line-del{color:#e88;background:rgba(196,112,112,0.1);display:block;padding:1px 4px;border-radius:3px;margin:1px 0;white-space:pre-wrap;word-break:break-all}.diff-line-add{color:#8c8;background:rgba(125,158,122,0.1);display:block;padding:1px 4px;border-radius:3px;margin:1px 0;white-space:pre-wrap;word-break:break-all}.diff-fuzzy-warn{font-family:'DM Mono',monospace;font-size:9px;color:var(--warn);padding:2px 6px;border-radius:4px;display:inline-block}
.cv-foot{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;border-top:1px solid var(--border2);font-family:'DM Mono',monospace;font-size:10px;color:var(--t3);flex-shrink:0}.cv-foot-left{display:flex;align-items:center;gap:12px}
.cv-lang-select,.theme-select{font-family:'DM Mono',monospace;font-size:10px;background:transparent;border:1px solid var(--border);color:var(--t3);padding:2px 8px;border-radius:16px;cursor:pointer}
.cv-input-badge{display:none;align-items:center;gap:4px;font-family:'DM Mono',monospace;font-size:9px;color:var(--cv-active);background:var(--cv-activeg);border:1px solid rgba(74,158,106,0.3);border-radius:20px;padding:2px 8px;margin-bottom:4px}.cv-input-badge.visible{display:flex}
.cv-input-badge-dot{width:4px;height:4px;border-radius:50%;background:var(--cv-active);display:inline-block}
.ma{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}.mab{display:inline-flex;align-items:center;gap:3px;background:none;border:1px solid var(--border);color:var(--t3);border-radius:20px;padding:3px 8px;font-family:'DM Mono',monospace;font-size:9px;cursor:pointer;transition:all var(--tr)}.mab:hover{color:var(--t2);border-color:var(--t3)}.mab.saved{color:var(--ok);border-color:var(--ok)}
.sources{margin-top:8px;padding-top:8px;border-top:1px solid var(--border2)}.sl{font-family:'DM Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--t3);margin-bottom:4px}.st{display:inline-block;font-family:'DM Mono',monospace;font-size:10px;color:var(--accent2);background:var(--accentg);border:1px solid var(--border);padding:2px 8px;border-radius:20px;margin:2px 3px 2px 0}
.autocomplete-dropdown{position:fixed;background:var(--bg2);border:1px solid var(--border);border-radius:var(--rs);max-height:200px;overflow-y:auto;z-index:200;font-family:'JetBrains Mono',monospace;font-size:12px;display:none}.autocomplete-item{padding:4px 12px;cursor:pointer;color:var(--t2)}.autocomplete-item:hover,.autocomplete-item.selected{background:var(--accentg);color:var(--accent)}
header{padding:24px 0 16px;border-bottom:1px solid var(--border2);flex-shrink:0}.header-row{display:flex;align-items:baseline;justify-content:space-between}
.logo{font-family:'Instrument Serif',serif;font-size:26px;color:var(--t1);letter-spacing:0.04em;display:flex;align-items:baseline;gap:10px;cursor:default}
.logo-dot{width:5px;height:5px;background:var(--accent);border-radius:50%;animation:pulse 3s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:1;transform:scale(1.3)}}
.nav{display:flex;align-items:center;gap:6px}.nav-btn{font-family:'DM Mono',monospace;font-size:10px;color:var(--t3);background:none;border:1px solid var(--border);padding:4px 12px;border-radius:20px;cursor:pointer;transition:all var(--tr);letter-spacing:.05em;text-decoration:none}.nav-btn:hover{color:var(--t2);border-color:var(--t3)}
.subtitle{font-family:'DM Mono',monospace;font-size:10px;color:var(--t3);letter-spacing:.08em;text-transform:uppercase;margin-top:4px}
.header-bottom{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.status-bar{display:flex;gap:14px;font-family:'DM Mono',monospace;font-size:10px;color:var(--t3)}.si{display:flex;align-items:center;gap:4px}.sd{width:4px;height:4px;border-radius:50%;background:var(--ok)}.sd.off{background:var(--err)}
.mode-toggle{display:flex;background:var(--bg2);border:1px solid var(--border);border-radius:20px;padding:2px;gap:2px}.mbtn{font-family:'DM Mono',monospace;font-size:10px;padding:3px 12px;border:none;border-radius:18px;cursor:pointer;transition:all var(--tr);background:transparent;color:var(--t3)}.mbtn.ar{background:var(--accent);color:var(--bg)}.mbtn.ac{background:var(--chat);color:var(--bg)}.mbtn.aa{background:var(--ok);color:var(--bg)}
.chat-area{flex:1;overflow-y:auto;padding:20px 0}.msg{margin-bottom:24px;animation:fi .3s ease}@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}.ml{font-family:'DM Mono',monospace;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;color:var(--t3)}.ml.u{color:var(--accent2)}.mb{font-size:15px;line-height:1.75;color:var(--t1)}.mb.ut{font-size:16px}.mb p{margin-bottom:10px}.mb p:last-child{margin-bottom:0}.mb code{font-family:'JetBrains Mono',monospace;font-size:13px;background:var(--code);padding:2px 6px;border-radius:4px;border:1px solid var(--border2);color:var(--accent)}.mb pre{background:var(--code);border:1px solid var(--border);border-radius:var(--rs);padding:14px 18px;margin:10px 0;overflow-x:auto;position:relative}.cpb{position:absolute;top:6px;right:6px;font-family:'DM Mono',monospace;font-size:9px;background:var(--bg2);border:1px solid var(--border);color:var(--t3);padding:2px 8px;border-radius:12px;cursor:pointer;opacity:0;transition:opacity var(--tr);z-index:10}.mb pre:hover .cpb{opacity:1}.cpb:hover{color:var(--t2);background:var(--bg3)}
.srch{display:flex;align-items:center;gap:8px;font-family:'DM Mono',monospace;font-size:11px;color:var(--t3);margin-bottom:16px}.dots span{display:inline-block;width:4px;height:4px;background:var(--accent);border-radius:50%;margin-right:2px;animation:bn 1.2s ease-in-out infinite}.dots span:nth-child(2){animation-delay:.15s}.dots span:nth-child(3){animation-delay:.3s}@keyframes bn{0%,80%,100%{opacity:.3;transform:scale(.8)}40%{opacity:1;transform:scale(1.2)}}.cur{display:inline-block;width:2px;height:1em;background:var(--accent);margin-left:2px;animation:bl .8s step-end infinite;vertical-align:text-bottom}@keyframes bl{50%{opacity:0}}
.input-area{flex-shrink:0;padding:14px 0 20px;border-top:1px solid var(--border2)}.iw{display:flex;align-items:flex-end;gap:8px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:4px 4px 4px 16px;transition:border-color var(--tr),box-shadow var(--tr)}.iw:focus-within{border-color:var(--accent2);box-shadow:0 0 0 3px var(--accentg)}.iw textarea{flex:1;background:none;border:none;outline:none;color:var(--t1);font-family:'Source Serif 4',serif;font-size:15px;line-height:1.6;resize:none;min-height:24px;max-height:120px;padding:8px 0}.iw textarea::placeholder{color:var(--t3);font-style:italic}.ib{flex-shrink:0;width:36px;height:36px;border:none;border-radius:var(--rs);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all var(--tr);background:transparent;color:var(--t3)}.ib:hover{color:var(--t2);background:var(--bg3)}.ib.send{background:var(--accent);color:var(--bg)}.ib.send:hover{opacity:.85;transform:scale(1.04)}.ib.send:disabled{opacity:.3;cursor:not-allowed;transform:none}.ib.rec{color:#ff4444;animation:mp 1s ease-in-out infinite}@keyframes mp{0%,100%{transform:scale(1)}50%{transform:scale(1.15)}}
.hint{text-align:center;font-family:'DM Mono',monospace;font-size:9px;color:var(--t3);padding:0 0 8px;letter-spacing:.05em}.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center;animation:fi .8s ease}.ei{font-family:'Instrument Serif',serif;font-size:42px;color:var(--border);margin-bottom:12px}.et{font-size:14px;color:var(--t3);max-width:340px;line-height:1.7}.exs{margin-top:20px;display:flex;flex-direction:column;gap:6px}.exb{background:var(--bg2);border:1px solid var(--border);border-radius:var(--rs);padding:8px 16px;color:var(--t2);font-family:'Source Serif 4',serif;font-size:13px;cursor:pointer;transition:all var(--tr);text-align:left}.exb:hover{border-color:var(--accent2);color:var(--t1);background:var(--bg3)}
.cv-drop-overlay{display:none;position:absolute;inset:0;background:rgba(74,158,106,0.15);border:2px dashed var(--cv-active);border-radius:var(--rs);z-index:20;align-items:center;justify-content:center;flex-direction:column;gap:8px;font-family:"DM Mono",monospace;font-size:13px;color:var(--cv-active);pointer-events:none}
.cv-drop-overlay.active{display:flex}
.cv-drop-icon{font-size:32px}
.file-badge{display:none;align-items:center;gap:6px;background:var(--accentg);border:1px solid var(--accent2);border-radius:20px;padding:3px 10px;font-family:"DM Mono",monospace;font-size:10px;color:var(--accent);margin-bottom:4px}
.file-badge.visible{display:flex}
.file-badge-remove{cursor:pointer;opacity:0.6;margin-left:2px}
.file-badge-remove:hover{opacity:1}
.history-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:var(--bg);z-index:60;overflow-y:auto;display:none}
.history-overlay.open{display:block}
.history-inner{max-width:860px;margin:0 auto;padding:32px 24px}
.history-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.history-title{font-family:"Instrument Serif",serif;font-size:28px;color:var(--t1)}
.history-list{display:flex;flex-direction:column;gap:10px}
.history-item{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px 18px;cursor:pointer;transition:all var(--tr)}
.history-item:hover{border-color:var(--accent2);background:var(--bg3)}
.history-item-date{font-family:"DM Mono",monospace;font-size:9px;color:var(--t3);margin-bottom:4px}
.history-item-preview{font-size:14px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.history-item-meta{font-family:"DM Mono",monospace;font-size:9px;color:var(--t3);margin-top:4px}
.history-empty{text-align:center;color:var(--t3);font-family:"DM Mono",monospace;font-size:12px;padding:40px}
@media(max-width:768px){.canvas-panel{width:100%!important}.chat-inner{padding:0 16px}}
.stats-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:var(--bg);z-index:60;overflow-y:auto;display:none;}
.stats-overlay.open{display:block}
.stats-inner{max-width:1100px;margin:0 auto;padding:32px 24px}
.stats-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.stats-title{font-family:"Instrument Serif",serif;font-size:28px;color:var(--t1)}
.stats-close{font-family:"DM Mono",monospace;font-size:11px;color:var(--t3);background:none;border:1px solid var(--border);padding:6px 16px;border-radius:20px;cursor:pointer;transition:all var(--tr)}
.stats-close:hover{color:var(--t2);border-color:var(--t3)}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px}
.stat-card h3{font-family:"DM Mono",monospace;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--t3);margin-bottom:12px;display:flex;align-items:center;gap:6px}
.stat-card h3 .sd{width:6px;height:6px}
.stat-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border2)}
.stat-row:last-child{border-bottom:none}
.stat-label{font-family:"DM Mono",monospace;font-size:11px;color:var(--t3)}
.stat-val{font-family:"DM Mono",monospace;font-size:11px;color:var(--t1);font-weight:500}
.stat-bar-wrap{width:100%;height:5px;background:var(--bg3);border-radius:3px;margin-top:3px;overflow:hidden}
.stat-bar{height:100%;border-radius:3px;transition:width .5s ease}
.stat-bar.ok{background:var(--ok)}.stat-bar.warn{background:var(--warn)}.stat-bar.err{background:var(--err)}
.svc-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:4px;margin-top:4px}
.svc{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border2);font-family:"DM Mono",monospace;font-size:11px;color:var(--t2)}
.svc:last-child{border-bottom:none}
.svc .sd{width:5px;height:5px;flex-shrink:0}
.svc-machine{font-size:9px;color:var(--t3);margin-left:auto}
.ext-links{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap}
.ext-link{font-family:"DM Mono",monospace;font-size:11px;color:var(--accent);border:1px solid var(--accent2);padding:7px 18px;border-radius:20px;text-decoration:none;transition:all var(--tr)}
.ext-link:hover{background:var(--accentg);color:var(--t1)}
@media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:600px){.stats-grid{grid-template-columns:1fr;}}
</style>
</style>
</head>
<body>
<div class="app">
  <div class="chat-panel" id="chatPanel">
    <div class="chat-inner">
      <header>
        <div class="header-row">
          <div class="logo">N.O.M.A.D<span class="logo-dot"></span></div>
          <div class="nav">
            <button class="nav-btn" onclick="toggleTheme()" id="themeBtn">&#127769; dark</button>
            <a class="nav-btn" href="/voice">voice</a>
            <button class="nav-btn" onclick="toggleHistory()">history</button>
            <button class="nav-btn" onclick="clearChat()">clear</button>
            <button class="nav-btn" onclick="toggleStats()">system</button>
            <div class="mode-toggle">
              <button class="mbtn ar" id="bRag" onclick="setMode('rag')">RAG</button>
              <button class="mbtn" id="bChat" onclick="setMode('chat')">CHAT</button>
              <button class="mbtn" id="bAgent" onclick="setMode('agent')">AGENT</button>
            </div>
          </div>
        </div>
        <div class="subtitle">local knowledge &middot; private inference</div>
        <div class="header-bottom">
          <div class="status-bar">
            <div class="si"><span class="sd" id="sQ"></span>qdrant</div>
            <div class="si"><span class="sd" id="sL"></span>llm</div>
            <div class="si" id="sP" style="display:none"><span id="sPn"></span> vectors</div>
          </div>
        </div>
      </header>
      <div class="chat-area" id="chat">
        <div class="empty" id="empty">
          <div class="ei">&#10022;</div>
          <div class="et">Ask anything about your offline knowledge base, chat freely, or open the canvas to collaborate.</div>
          <div class="exs">
            <button class="exb" onclick="askEx(this)">How do I create a list in Python?</button>
            <button class="exb" onclick="askEx(this)">Explain Docker volumes</button>
            <button class="exb" onclick="askEx(this)">How to set up SSH keys?</button>
          </div>
        </div>
      </div>
      <div class="input-area">
        <div class="file-badge" id="fileBadge"><span>&#128196;</span><span id="fileBadgeName"></span><span class="file-badge-remove" onclick="clearAttachment()" title="Remove">&#10005;</span></div>
        <div class="cv-input-badge" id="cvInputBadge"><span class="cv-input-badge-dot"></span>canvas is active as context</div>
        <div class="iw" id="iw">
          <textarea id="inp" placeholder="Ask your knowledge base..." rows="1" onkeydown="hk(event)" oninput="ar(this)"></textarea>
          <button class="ib" id="cvBtn" onclick="toggleCanvas()" title="Canvas">&#128196;</button>
          <button class="ib" id="micBtn" onclick="toggleRec()" title="Voice">&#127908;</button>
          <button class="ib send" id="sendBtn" onclick="sendMsg()"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
        </div>
      </div>
      <div class="hint">pi 5 &middot; nomad desktop &middot; fully local</div>
    </div>
  </div>
  <div class="canvas-panel" id="cvPanel">
    <div class="cv-tab-bar">
      <div class="cv-tabs-container" id="cvTabs"></div>
      <div class="cv-new-tab" onclick="cvNewTab()" title="New tab">+</div>
    </div>
    <div class="cv-head">
      <div class="cv-title"><span>&#128196;</span><span id="cvName">untitled</span></div>
      <div style="display:flex;gap:4px;align-items:center">
        <select id="themeSelect" class="theme-select" onchange="changePrismTheme(this.value)">
          <option value="tomorrow">Tomorrow</option><option value="dracula">Dracula</option><option value="monokai">Monokai</option>
        </select>
        <button class="nav-btn" onclick="cvToggleSplit()" id="splitBtn">split</button>
        <button class="nav-btn" onclick="toggleCanvas()">&#10005;</button>
      </div>
    </div>
    <div class="cv-toolbar">
      <button class="cv-toolbar-btn" onclick="cvUndo()">&#8617; undo</button>
      <button class="cv-toolbar-btn" onclick="cvRedo()">&#8618; redo</button>
      <button class="cv-toolbar-btn" onclick="cvFind()">find</button>
      <button class="cv-toolbar-btn" onclick="cvReplace()">replace</button>
      <button class="cv-toolbar-btn" onclick="cvBeautify()">&#10024; beautify</button>
      <button class="cv-toolbar-btn" onclick="document.getElementById('cvFileInput').click()">&#128228; load file</button>
      <input type="file" id="cvFileInput" style="display:none" accept=".txt,.py,.js,.html,.css,.json,.md,.sh,.sql,.pdf,.png,.jpg,.jpeg,.webp" onchange="cvLoadFile(this)">
      <button class="cv-toolbar-btn" onclick="cvDl()">download</button>
      <button class="cv-toolbar-btn" onclick="cvSetGoal()">word goal</button>
      <span style="flex:1"></span>
      <span id="mdToolbar" style="display:none;gap:4px">
        <button class="cv-toolbar-btn" onclick="insertMd('**','**')">B</button>
        <button class="cv-toolbar-btn" onclick="insertMd('*','*')">I</button>
        <button class="cv-toolbar-btn" onclick="insertMd('# ','')">H1</button>
        <button class="cv-toolbar-btn" onclick="insertMd('```\n','\n```')">Code</button>
      </span>
    </div>
    <div class="cv-ctx-bar" id="cvCtxBar"><span class="cv-ctx-dot"></span><span>active as context &mdash; LLM can read and edit this</span></div>
    <div class="cv-body">
      <div class="cv-drop-overlay" id="cvDropOverlay"><span class="cv-drop-icon">&#128196;</span><span>Drop file to load into canvas</span><span style="font-size:10px;opacity:0.7">PDF &middot; image &middot; text &middot; code</span></div>
      <div class="cv-goal-bar" id="cvGoalBar" style="display:none"><div class="cv-goal-progress" id="cvGoalProgress"></div></div>
      <div id="cvSplitContainer" class="cv-split-container">
        <div class="cv-edit" id="cvEdit">
          <div class="cv-line-numbers" id="cvLineNumbers">1</div>
          <textarea id="cvTa" placeholder="Start writing, or ask the LLM to generate content here.&#10;&#10;Canvas is sent as context with every message.&#10;Ask to 'fix', 'improve', 'add error handling', etc." oninput="cvStats();cvUpdateLineNumbers();cvPushHistory();cvUpdateMinimap();cvAutoSave()" onkeydown="cvHandleKeydown(event)" onscroll="cvSyncScroll()" spellcheck="false" wrap="off"></textarea>
          <div class="cv-writing-indicator" id="cvWritingIndicator">&#9998; LLM writing...</div>
          <div class="cv-minimap" id="cvMinimap"><div class="cv-minimap-content" id="cvMinimapContent"></div></div>
        </div>
        <div class="cv-prev-inner" id="cvPrevInner"></div>
        <div class="cv-diff" id="cvDiff">
          <div class="cv-diff-toolbar">
            <span id="diffSummary">0 changes</span>
            <button class="cv-diff-btn accept-all" onclick="diffAcceptAll()">&#10003; accept all</button>
            <button class="cv-diff-btn reject-all" onclick="diffRejectAll()">&#10007; reject all</button>
          </div>
          <div class="cv-diff-body" id="diffBody"></div>
        </div>
      </div>
    </div>
    <div class="cv-foot">
      <div class="cv-foot-left">
        <span id="cvSt">0 words</span>
        <select id="cvLangSelect" class="cv-lang-select" onchange="cvSetLanguage(this.value)">
          <option value="plaintext">plaintext</option><option value="python">Python</option><option value="javascript">JavaScript</option><option value="html">HTML</option><option value="css">CSS</option><option value="bash">Bash</option><option value="json">JSON</option><option value="markdown">Markdown</option><option value="sql">SQL</option>
        </select>
      </div>
      <span id="cvDiffTab" style="display:none;font-family:'DM Mono',monospace;cursor:pointer;color:var(--accent)" onclick="cvShowDiff()">diff <span id="diffCount" style="background:var(--accent);color:var(--bg);border-radius:20px;padding:0 5px;font-size:9px"></span></span>
    </div>
  </div>
  <div class="autocomplete-dropdown" id="autocompleteDropdown"></div>
</div>

<!-- Stats Overlay -->
<div class="stats-overlay" id="statsPanel">
  <div class="stats-inner">
    <div class="stats-header">
      <div class="stats-title">System Status</div>
      <button class="stats-close" onclick="toggleStats()">&#10005; close</button>
    </div>
    <div class="stats-grid" id="statsGrid">
      <div class="stat-card"><h3><span class="sd" id="sdPi"></span>Raspberry Pi 5</h3><div id="piStats"><div class="stat-row"><span class="stat-label">Loading...</span></div></div></div>
      <div class="stat-card"><h3><span class="sd" id="sdNomad"></span>NOMAD Desktop</h3><div id="nomadStats"><div class="stat-row"><span class="stat-label">Loading...</span></div></div></div>
      <div class="stat-card"><h3><span class="sd" id="sdXps"></span>XPS13</h3><div id="xpsStats"><div class="stat-row"><span class="stat-label">Loading...</span></div></div></div>
      <div class="stat-card"><h3><span class="sd"></span>Knowledge Base</h3><div id="kbStats"><div class="stat-row"><span class="stat-label">Loading...</span></div></div></div>
    </div>
    <div class="stat-card" style="margin-top:16px">
      <h3><span class="sd"></span>Services</h3>
      <div id="svcStats"><div class="stat-row"><span class="stat-label">Loading...</span></div></div>
    </div>
    <div class="ext-links">
      <a class="ext-link" href="DOZZLE_PLACEHOLDER" target="_blank">&#9881; Dozzle</a>
      <a class="ext-link" href="http://192.168.2.20:3000" target="_blank">&#9881; Grafana</a>
      <a class="ext-link" href="http://192.168.2.20:9090" target="_blank">&#9881; Prometheus</a>
      <a class="ext-link" href="NOMAD_PLACEHOLDER" target="_blank">&#9881; NOMAD Command Center</a>
    </div>
  </div>
</div>


<!-- History Overlay -->
<div class="history-overlay" id="historyPanel">
  <div class="history-inner">
    <div class="history-header">
      <div class="history-title">Chat History</div>
      <div style="display:flex;gap:8px">
        <button class="stats-close" onclick="historyClear()" style="color:var(--err);border-color:var(--err)">clear all</button>
        <button class="stats-close" onclick="toggleHistory()">&#10005; close</button>
      </div>
    </div>
    <div class="history-list" id="historyList">
      <div class="history-empty">No saved conversations yet.</div>
    </div>
  </div>
</div>

<div class="toast-container" id="toastContainer"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/js-beautify/1.15.1/beautify.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/js-beautify/1.15.1/beautify-html.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/js-beautify/1.15.1/beautify-css.min.js"></script>
<script>
var G={chat:document.getElementById("chat"),inp:document.getElementById("inp"),sendBtn:document.getElementById("sendBtn"),empty:document.getElementById("empty"),streaming:false,mode:"rag",history:[],cvOpen:false,cvWidth:600,cvSplit:false,audio:null,cvTabs:[{name:"untitled",content:"",language:"plaintext"}],cvActiveTab:0,cvHistory:[],cvHistoryIndex:-1,cvWordGoal:0,autoSaveTimer:null,cvLanguage:"plaintext"};
var G_diff={ops:[],resolved:[]};
var AC_WORDS={python:["def","class","import","from","if","else","elif","for","while","try","except","return","True","False","None","print","len","range","self","with","open","pass"],javascript:["function","const","let","var","if","else","for","while","try","catch","async","await","return","true","false","null","console","document","window"],html:["div","span","p","a","img","input","button","form","h1","h2","h3","ul","li"],sql:["SELECT","FROM","WHERE","JOIN","LEFT","RIGHT","GROUP BY","ORDER BY","INSERT","UPDATE","DELETE"]};
function ar(e){e.style.height="auto";e.style.height=Math.min(e.scrollHeight,120)+"px";}
function hk(e){if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMsg();}}
function askEx(b){G.inp.value=b.textContent;sendMsg();}
function esc(s){var d=document.createElement("div");d.appendChild(document.createTextNode(s));return d.innerHTML;}
function showToast(msg,dur){dur=dur||2500;var c=document.getElementById("toastContainer");var t=document.createElement("div");t.className="toast";t.textContent=msg;c.appendChild(t);setTimeout(function(){if(t.parentNode)t.remove();},dur);}
function cpCode(btn){var pre=btn.closest("pre");if(!pre)return;var code=pre.querySelector("code");navigator.clipboard.writeText(code?code.textContent:pre.textContent).then(function(){btn.textContent="copied!";setTimeout(function(){btn.textContent="copy";},1500)});}
function fmt(t){var f=t;f=f.replace(/```(\w*)\n([\s\S]*?)```/g,function(m,lang,code){return '<pre class="language-'+(lang||"plaintext")+'"><code>'+esc(code)+'</code><button class="cpb" onclick="cpCode(this)">copy</button></pre>';});f=f.replace(/`([^`]+)`/g,"<code>$1</code>");f=f.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");var p=f.split("\n\n");f=p.map(function(x){x=x.trim();if(!x)return"";if(x.indexOf("<pre")!==-1)return x;return"<p>"+x+"</p>";}).join("");f=f.replace(/\n/g,"<br>");setTimeout(function(){document.querySelectorAll(".mb pre code").forEach(function(b){if(window.Prism)Prism.highlightElement(b);});},10);return f;}
function toggleTheme(){var h=document.documentElement,b=document.getElementById("themeBtn");if(h.classList.contains("light")){h.classList.remove("light");b.innerHTML="&#127769; dark";localStorage.setItem("nomad_theme","dark");}else{h.classList.add("light");b.innerHTML="&#9728;&#65039; light";localStorage.setItem("nomad_theme","light");}}
function changePrismTheme(t){var themes={tomorrow:"prism-tomorrow",dracula:"prism-dracula",monokai:"prism-monokai"};document.getElementById("prism-theme").href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/"+themes[t]+".min.css";}
(function(){var s=localStorage.getItem("nomad_theme");if(s==="light"){document.documentElement.classList.add("light");document.getElementById("themeBtn").innerHTML="&#9728;&#65039; light";}})();
function getFileIcon(lang){var i={python:"&#128013;",javascript:"&#128249;",html:"&#127760;",css:"&#127912;",bash:"&#128187;",json:"&#128230;",markdown:"&#128196;",sql:"&#128451;"};return i[lang]||"&#128196;";}
function renderTabs(){var c=document.getElementById("cvTabs");c.innerHTML="";G.cvTabs.forEach(function(t,i){var d=document.createElement("div");d.className="cv-tab-item"+(i===G.cvActiveTab?" active":"");d.innerHTML=getFileIcon(t.language)+" "+esc(t.name)+(G.cvTabs.length>1?'<span class="cv-tab-close" onclick="event.stopPropagation();cvCloseTab('+i+')">\xd7</span>':"")+'';d.onclick=function(){cvSwitchTab(i);};c.appendChild(d);});}
function cvNewTab(){G.cvTabs.push({name:"untitled-"+(G.cvTabs.length+1),content:"",language:"plaintext"});G.cvActiveTab=G.cvTabs.length-1;renderTabs();loadActiveTab();}
function cvCloseTab(i){if(G.cvTabs.length<=1)return;G.cvTabs.splice(i,1);if(G.cvActiveTab>=i)G.cvActiveTab=Math.max(0,G.cvActiveTab-1);renderTabs();loadActiveTab();}
function cvSwitchTab(i){if(i===G.cvActiveTab)return;saveActiveTab();G.cvActiveTab=i;renderTabs();loadActiveTab();cvStats();}
function saveActiveTab(){if(G.cvTabs[G.cvActiveTab]){G.cvTabs[G.cvActiveTab].content=document.getElementById("cvTa").value;G.cvTabs[G.cvActiveTab].language=G.cvLanguage;}}
function loadActiveTab(){var t=G.cvTabs[G.cvActiveTab];document.getElementById("cvTa").value=t.content||"";document.getElementById("cvName").textContent=t.name;cvSetLanguage(t.language||"plaintext");G.cvHistory=[t.content||""];G.cvHistoryIndex=0;cvUpdateLineNumbers();cvUpdateMinimap();updateMdToolbar();}
function updateMdToolbar(){document.getElementById("mdToolbar").style.display=G.cvLanguage==="markdown"?"flex":"none";}
function cvPushHistory(){var c=document.getElementById("cvTa").value;if(G.cvHistory[G.cvHistoryIndex]!==c){G.cvHistory=G.cvHistory.slice(0,G.cvHistoryIndex+1);G.cvHistory.push(c);G.cvHistoryIndex++;if(G.cvHistory.length>50){G.cvHistory.shift();G.cvHistoryIndex--;}}}
function cvUndo(){if(G.cvHistoryIndex>0){G.cvHistoryIndex--;document.getElementById("cvTa").value=G.cvHistory[G.cvHistoryIndex];cvStats();cvUpdateLineNumbers();cvUpdateMinimap();}}
function cvRedo(){if(G.cvHistoryIndex<G.cvHistory.length-1){G.cvHistoryIndex++;document.getElementById("cvTa").value=G.cvHistory[G.cvHistoryIndex];cvStats();cvUpdateLineNumbers();cvUpdateMinimap();}}
function cvUpdateLineNumbers(){var lines=document.getElementById("cvTa").value.split("\n").length;var h="";for(var i=1;i<=lines;i++)h+=i+"<br>";document.getElementById("cvLineNumbers").innerHTML=h;}
function cvUpdateMinimap(){document.getElementById("cvMinimapContent").textContent=document.getElementById("cvTa").value;}
function cvSyncScroll(){var ta=document.getElementById("cvTa");document.getElementById("cvLineNumbers").scrollTop=ta.scrollTop;}
function cvAutoSave(){clearTimeout(G.autoSaveTimer);G.autoSaveTimer=setTimeout(function(){var c=document.getElementById("cvTa").value,n=document.getElementById("cvName").textContent;localStorage.setItem("nomad_autosave_"+n,c);showToast("auto-saved",800);},2000);}
function cvFind(){var t=prompt("Find:");if(!t)return;var ta=document.getElementById("cvTa");var p=ta.value.indexOf(t,ta.selectionStart);if(p>=0){ta.setSelectionRange(p,p+t.length);ta.focus();}else showToast("Not found",1500);}
function cvReplace(){var f=prompt("Find:");if(!f)return;var r=prompt("Replace with:");if(r===null)return;var ta=document.getElementById("cvTa");ta.value=ta.value.split(f).join(r);cvStats();cvUpdateLineNumbers();cvUpdateMinimap();cvPushHistory();}
function cvSetGoal(){var g=parseInt(prompt("Word count goal:"));if(g>0){G.cvWordGoal=g;document.getElementById("cvGoalBar").style.display="block";}}
function updateGoalProgress(){if(!G.cvWordGoal)return;var w=cvGetContent().split(/\s+/).filter(function(x){return x.length>0;}).length;var p=Math.min(100,Math.round(w/G.cvWordGoal*100));document.getElementById("cvGoalProgress").style.width=p+"%";if(w>=G.cvWordGoal){showToast("Word goal reached!");G.cvWordGoal=0;document.getElementById("cvGoalBar").style.display="none";}}
function insertMd(b,a){var ta=document.getElementById("cvTa");var s=ta.selectionStart,e=ta.selectionEnd;var sel=ta.value.substring(s,e);ta.setRangeText(b+sel+a,s,e,"select");ta.focus();cvStats();cvUpdateLineNumbers();cvPushHistory();}
function cvToggleSplit(){G.cvSplit=!G.cvSplit;var container=document.getElementById("cvSplitContainer");var prev=document.getElementById("cvPrevInner");var btn=document.getElementById("splitBtn");if(G.cvSplit){container.className="cv-split-container cv-split";prev.style.display="block";prev.innerHTML=renderMd(document.getElementById("cvTa").value);btn.style.background="var(--accent)";btn.style.color="var(--bg)";}else{container.className="cv-split-container";prev.style.display="none";btn.style.background="";btn.style.color="";}}
function renderMd(t){var h=t;h=h.replace(/```(\w*)\n([\s\S]*?)```/g,function(m,l,c){return'<pre class="language-'+(l||"plaintext")+'"><code>'+esc(c)+"</code></pre>";});h=h.replace(/^### (.+)$/gm,"<h3>$1</h3>");h=h.replace(/^## (.+)$/gm,"<h2>$1</h2>");h=h.replace(/^# (.+)$/gm,"<h1>$1</h1>");h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");h=h.replace(/\*([^*]+)\*/g,"<em>$1</em>");h=h.replace(/`([^`]+)`/g,"<code>$1</code>");h=h.replace(/\n\n/g,"</p><p>");h="<p>"+h+"</p>";setTimeout(function(){document.querySelectorAll("#cvPrevInner pre code").forEach(function(b){if(window.Prism)Prism.highlightElement(b);});},10);return h;}
var acDropdown=document.getElementById("autocompleteDropdown"),acIdx=-1;
function cvHandleKeydown(e){if(e.key===" "&&e.ctrlKey){showAutocomplete();return;}if(acDropdown.style.display==="block"){if(e.key==="ArrowDown"){e.preventDefault();acIdx=Math.min(acIdx+1,acDropdown.children.length-1);updateAcSel();}else if(e.key==="ArrowUp"){e.preventDefault();acIdx=Math.max(acIdx-1,0);updateAcSel();}else if(e.key==="Enter"&&acIdx>=0){e.preventDefault();applyAcSug();}else if(e.key==="Escape"){acDropdown.style.display="none";}}}
function showAutocomplete(){var ta=document.getElementById("cvTa"),pos=ta.selectionStart,text=ta.value,start=pos;while(start>0&&/[a-zA-Z_]/.test(text[start-1]))start--;var word=text.substring(start,pos);if(word.length<2){acDropdown.style.display="none";return;}var words=AC_WORDS[G.cvLanguage]||[];var matches=words.filter(function(w){return w.toLowerCase().startsWith(word.toLowerCase());});if(!matches.length){acDropdown.style.display="none";return;}acDropdown.innerHTML="";matches.slice(0,10).forEach(function(m,i){var d=document.createElement("div");d.className="autocomplete-item"+(i===0?" selected":"");d.textContent=m;d.onclick=function(){applyAcWord(m);};acDropdown.appendChild(d);});var rect=ta.getBoundingClientRect();acDropdown.style.left=(rect.left+10)+"px";acDropdown.style.top=(rect.bottom-10)+"px";acDropdown.style.display="block";acIdx=0;}
function updateAcSel(){var items=acDropdown.children;for(var i=0;i<items.length;i++)items[i].classList.toggle("selected",i===acIdx);}
function applyAcSug(){var items=acDropdown.children;if(acIdx>=0&&acIdx<items.length)applyAcWord(items[acIdx].textContent);}
function applyAcWord(word){var ta=document.getElementById("cvTa"),pos=ta.selectionStart,text=ta.value,start=pos;while(start>0&&/[a-zA-Z_]/.test(text[start-1]))start--;ta.setRangeText(word,start,pos,"end");acDropdown.style.display="none";ta.focus();cvStats();cvUpdateLineNumbers();cvPushHistory();}
var cvResizeActive=false,cvStartX=0,cvStartWidth=0;
function initCanvasResize(){var panel=document.getElementById("cvPanel");var saved=localStorage.getItem("nomad_canvas_width");if(saved){G.cvWidth=parseInt(saved);panel.style.width=G.cvWidth+"px";}panel.addEventListener("mousedown",function(e){if(e.offsetX<8){cvResizeActive=true;cvStartX=e.clientX;cvStartWidth=panel.offsetWidth;document.body.style.cursor="ew-resize";document.body.style.userSelect="none";e.preventDefault();}});document.addEventListener("mousemove",function(e){if(!cvResizeActive||!G.cvOpen)return;var newW=Math.min(900,Math.max(400,cvStartWidth+(cvStartX-e.clientX)));G.cvWidth=newW;panel.style.width=newW+"px";document.getElementById("chatPanel").style.marginRight=newW+"px";localStorage.setItem("nomad_canvas_width",newW);});document.addEventListener("mouseup",function(){if(cvResizeActive){cvResizeActive=false;document.body.style.cursor="";document.body.style.userSelect="";}});}
document.addEventListener("keydown",function(e){if(!G.cvOpen)return;if(e.ctrlKey&&e.key==="s"){e.preventDefault();cvDl();}if(e.ctrlKey&&e.key==="f"){e.preventDefault();cvFind();}if(e.ctrlKey&&!e.shiftKey&&e.key==="z"){e.preventDefault();cvUndo();}if((e.ctrlKey&&e.shiftKey&&e.key==="Z")||(e.ctrlKey&&e.key==="y")){e.preventDefault();cvRedo();}if(e.key==="Escape"){toggleCanvas(true);}});
function cvDetectLanguage(c){if(!c)return"plaintext";var l=c.toLowerCase();if(l.indexOf("def ")!==-1||l.indexOf("import ")!==-1)return"python";if(l.indexOf("function")!==-1||l.indexOf("const ")!==-1||l.indexOf("let ")!==-1)return"javascript";if(l.indexOf("<!doctype")!==-1||l.indexOf("<html")!==-1)return"html";if(l.indexOf("#!/bin/bash")!==-1||l.indexOf("#!/bin/sh")!==-1)return"bash";return"plaintext";}
function cvSetLanguage(lang){G.cvLanguage=lang;if(G.cvTabs[G.cvActiveTab])G.cvTabs[G.cvActiveTab].language=lang;var ln=document.getElementById("cvLn");if(ln)ln.textContent=lang;var sel=document.getElementById("cvLangSelect");if(sel)sel.value=lang;renderTabs();updateMdToolbar();}
function cvHasContent(){return document.getElementById("cvTa").value.trim().length>0;}
function cvGetContent(){return document.getElementById("cvTa").value;}
function cvUpdateContextState(){var has=cvHasContent(),open=G.cvOpen;document.getElementById("cvInputBadge").className="cv-input-badge"+(open&&has?" visible":"");document.getElementById("cvCtxBar").className="cv-ctx-bar"+(open&&has?" visible":"");}
function toggleCanvas(forceClose){if(forceClose===true)G.cvOpen=false;else G.cvOpen=!G.cvOpen;var panel=document.getElementById("cvPanel");panel.className="canvas-panel"+(G.cvOpen?" open":"");panel.style.width=G.cvWidth+"px";document.getElementById("chatPanel").className="chat-panel"+(G.cvOpen?" shifted":"");document.getElementById("chatPanel").style.marginRight=G.cvOpen?G.cvWidth+"px":"";cvUpdateContextState();if(G.cvOpen){cvUpdateLineNumbers();cvUpdateMinimap();}}
function cvStats(){var t=document.getElementById("cvTa").value;var w=t.trim()?t.trim().split(/\s+/).length:0;document.getElementById("cvSt").textContent=w+" words \xb7 "+t.length+" chars";var det=cvDetectLanguage(t);if(det!==G.cvLanguage&&t.length>10)cvSetLanguage(det);updateGoalProgress();}
function cvDl(){var t=document.getElementById("cvTa").value,n=G.cvTabs[G.cvActiveTab].name;var ext={python:"py",javascript:"js",html:"html",css:"css",bash:"sh",json:"json",markdown:"md",sql:"sql"};if(!n.includes("."))n+="."+(ext[G.cvLanguage]||"txt");var b=new Blob([t],{type:"text/plain"}),a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=n;a.click();}
function cvBeautify(){
  var ta=document.getElementById("cvTa");
  var text=ta.value;
  if(!text.trim()){showToast("Canvas is empty");return;}
  var lang=G.cvLanguage;
  // Client-side for code languages
  if(lang==="javascript"&&window.js_beautify){
    ta.value=js_beautify(text,{indent_size:2,space_in_empty_paren:true});
    cvAfterBeautify();return;
  }
  if(lang==="html"&&window.html_beautify){
    ta.value=html_beautify(text,{indent_size:2,wrap_line_length:100});
    cvAfterBeautify();return;
  }
  if(lang==="css"&&window.css_beautify){
    ta.value=css_beautify(text,{indent_size:2});
    cvAfterBeautify();return;
  }
  if(lang==="json"){
    try{ta.value=JSON.stringify(JSON.parse(text),null,2);cvAfterBeautify();return;}
    catch(e){showToast("Invalid JSON: "+e.message,3000);return;}
  }
  // LLM-based for Python, Bash, Markdown, plaintext
  cvBeautifyViaLLM(text,lang);
}
function cvAfterBeautify(){
  cvStats();cvUpdateLineNumbers();cvUpdateMinimap();cvPushHistory();
  showToast("Beautified!");
  if(G.cvSplit)document.getElementById("cvPrevInner").innerHTML=renderMd(document.getElementById("cvTa").value);
}
function cvBeautifyViaLLM(text,lang){
  var prompts={
    python:"Format this Python code with PEP8 style: proper indentation (4 spaces), blank lines between functions/classes, consistent spacing. Output ONLY the formatted code, no explanation.",
    bash:"Format this shell script: consistent indentation (2 spaces), proper spacing around operators, align comments. Output ONLY the formatted code.",
    markdown:"Clean up this markdown: fix heading levels, consistent list style, proper spacing between sections, fix any formatting issues. Output ONLY the improved markdown.",
    plaintext:"Reformat this text for readability: proper paragraphs, consistent spacing, clean up any formatting issues. Output ONLY the reformatted text.",
    sql:"Format this SQL: uppercase keywords, proper indentation, one clause per line. Output ONLY the formatted SQL."
  };
  var prompt=prompts[lang]||prompts.plaintext;
  // Show loading state
  document.getElementById("cvWritingIndicator").className="cv-writing-indicator visible";
  document.getElementById("cvTa").className="writing";
  showToast("Beautifying via LLM...");
  // Stream directly into canvas
  var canvasContent=text;
  G.streaming=true;G.sendBtn.disabled=true;
  var buf="",cvFn=G.cvTabs[G.cvActiveTab].name;
  fetch("/canvas-generate",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question:prompt+"\n\n```\n"+text+"\n```",canvas_content:null})
  }).then(async function(r){
    var reader=r.body.getReader(),decoder=new TextDecoder(),lineBuf="";
    cvStreamBuffer="";
    document.getElementById("cvTa").value="";
    while(true){
      var rd=await reader.read();if(rd.done)break;
      lineBuf+=decoder.decode(rd.value,{stream:true});
      var lines=lineBuf.split("\n");lineBuf=lines.pop();
      for(var line of lines){
        if(!line.startsWith("data: "))continue;
        var d=line.substring(6);if(d==="[DONE]")continue;
        try{var p=JSON.parse(d);
          if(p.type==="canvas_token"){cvStreamToken(p.token);}
          else if(p.type==="canvas_done"||p.type==="done"){
            // Strip any accidental markdown fences the LLM added
            var val=document.getElementById("cvTa").value;
            val=val.replace(/^```[a-zA-Z]*\n?/,"").replace(/\n?```\s*$/,"").trim();
            document.getElementById("cvTa").value=val;
            cvStreamEnd(cvFn);
            cvAfterBeautify();
          }
        }catch(e){}
      }
    }
    G.streaming=false;G.sendBtn.disabled=false;
  }).catch(function(){
    document.getElementById("cvTa").className="";
    document.getElementById("cvWritingIndicator").className="cv-writing-indicator";
    showToast("Beautify failed",2000);
    G.streaming=false;G.sendBtn.disabled=false;
  });
}
function writeToCv(text,fn){if(!G.cvOpen)toggleCanvas();document.getElementById("cvTa").value=text;if(fn){G.cvTabs[G.cvActiveTab].name=fn;document.getElementById("cvName").textContent=fn;}cvStats();cvUpdateLineNumbers();cvUpdateMinimap();cvUpdateContextState();G.cvHistory=[text];G.cvHistoryIndex=0;saveActiveTab();renderTabs();if(G.cvSplit){document.getElementById("cvPrevInner").innerHTML=renderMd(text);}}
var cvStreamBuffer="";
function cvStreamStart(){cvStreamBuffer="";if(!G.cvOpen)toggleCanvas();document.getElementById("cvTa").className="writing";document.getElementById("cvWritingIndicator").className="cv-writing-indicator visible";}
function cvStreamToken(token){cvStreamBuffer+=token;var ta=document.getElementById("cvTa");ta.value=cvStreamBuffer;ta.scrollTop=ta.scrollHeight;cvStats();}
function cvStreamEnd(filename){document.getElementById("cvTa").className="";document.getElementById("cvWritingIndicator").className="cv-writing-indicator";if(filename){G.cvTabs[G.cvActiveTab].name=filename;document.getElementById("cvName").textContent=filename;renderTabs();}cvUpdateContextState();if(G.cvSplit)document.getElementById("cvPrevInner").innerHTML=renderMd(cvStreamBuffer);}
function fuzzyFind(haystack,needle){if(!needle)return{index:-1,score:0};var idx=haystack.indexOf(needle);if(idx!==-1)return{index:idx,score:1.0};var nt=needle.trim();idx=haystack.indexOf(nt);if(idx!==-1)return{index:idx,score:0.97};var firstLine=nt.split("\n")[0].trim();if(firstLine.length>10){idx=haystack.indexOf(firstLine);if(idx!==-1)return{index:idx,score:0.85};}var best={index:-1,score:0};var step=Math.max(1,Math.floor(needle.length/4));for(var i=0;i<=haystack.length-needle.length;i+=step){var win=haystack.substr(i,needle.length);var sim=strSim(win,needle);if(sim>best.score)best={index:i,score:sim};}return best.score>0.7?best:{index:-1,score:0};}
function strSim(a,b){if(!a||!b)return 0;var len=Math.max(a.length,b.length),matches=0,min=Math.min(a.length,b.length);for(var i=0;i<min;i++){if(a[i]===b[i])matches++;}return matches/len;}
function applyOp(text,op){if(op.op==="replace"){var f=fuzzyFind(text,op.old);if(f.index===-1)return null;return text.substring(0,f.index)+op.new+text.substring(f.index+op.old.length);}if(op.op==="delete"){var f=fuzzyFind(text,op.text);if(f.index===-1)return null;return text.substring(0,f.index)+text.substring(f.index+op.text.length);}if(op.op==="insert_after"){var f=fuzzyFind(text,op.after);if(f.index===-1)return null;var at=f.index+op.after.length;return text.substring(0,at)+"\n"+op.new+text.substring(at);}if(op.op==="insert_before"){var f=fuzzyFind(text,op.before);if(f.index===-1)return null;return text.substring(0,f.index)+op.new+"\n"+text.substring(f.index);}if(op.op==="append"){return text+"\n"+op.new;}return null;}
function cvShowDiff(){document.getElementById("cvDiff").className="cv-diff visible";document.getElementById("cvEdit").style.display="none";}
function cvHideDiff(){document.getElementById("cvDiff").className="cv-diff";document.getElementById("cvEdit").style.display="flex";document.getElementById("cvDiffTab").style.display="none";}
function showDiffOps(ops){G_diff.ops=ops;G_diff.resolved=ops.map(function(){return null;});var body=document.getElementById("diffBody");body.innerHTML="";var cur=document.getElementById("cvTa").value,valid=0;ops.forEach(function(op,i){var el=document.createElement("div");el.className="diff-op";el.id="diffop-"+i;var opType=op.op==="replace"?"replace":(op.op==="delete"?"delete":"insert");var findIn=op.old||op.text||op.after||op.before||"";var found=findIn?fuzzyFind(cur,findIn):{index:0,score:1};if(found.index===-1){el.innerHTML='<div class="diff-op-head"><span class="diff-op-label delete">'+opType+'</span><span style="font-size:9px;color:var(--err);margin-left:6px">location not found</span></div>';body.appendChild(el);G_diff.resolved[i]=false;return;}var fuzzy=found.score<1.0;valid++;var h='<div class="diff-op-head"><span class="diff-op-label '+opType+'">'+opType+"</span>";if(fuzzy)h+='<span class="diff-fuzzy-warn">~fuzzy '+Math.round(found.score*100)+'%</span>';h+='<div class="diff-op-acts"><button class="diff-op-act acc" onclick="diffAcceptOne('+i+')">&#10003;</button><button class="diff-op-act rej" onclick="diffRejectOne('+i+')">&#10007;</button></div></div>';var b='<div class="diff-op-body">';if(op.op==="replace"){b+='<span class="diff-line-del">'+esc(op.old)+"</span>";b+='<span class="diff-line-add">'+esc(op.new)+"</span>";}else if(op.op==="delete"){b+='<span class="diff-line-del">'+esc(op.text)+"</span>";}else{b+='<span style="font-size:9px;color:var(--t3);display:block">'+esc((op.after||op.before||"").substring(0,50))+"</span>";b+='<span class="diff-line-add">'+esc(op.new)+"</span>";}b+="</div>";el.innerHTML=h+b;body.appendChild(el);});document.getElementById("diffSummary").textContent=valid+" change"+(valid!==1?"s":"");document.getElementById("diffCount").textContent=valid;document.getElementById("cvDiffTab").style.display="";cvShowDiff();}
function diffAcceptOne(i){G_diff.resolved[i]=true;var el=document.getElementById("diffop-"+i);if(el){el.querySelectorAll(".diff-op-act").forEach(function(a){a.className="diff-op-act done";});el.style.opacity="0.5";}updateDiffSummary();checkDiffDone();}
function diffRejectOne(i){G_diff.resolved[i]=false;var el=document.getElementById("diffop-"+i);if(el){el.querySelectorAll(".diff-op-act").forEach(function(a){a.className="diff-op-act done";});el.style.opacity="0.3";}updateDiffSummary();checkDiffDone();}
function diffAcceptAll(){G_diff.ops.forEach(function(_,i){if(G_diff.resolved[i]===null)diffAcceptOne(i);});}
function diffRejectAll(){G_diff.ops.forEach(function(_,i){if(G_diff.resolved[i]===null)diffRejectOne(i);});}
function updateDiffSummary(){var p=G_diff.resolved.filter(function(r){return r===null;}).length,a=G_diff.resolved.filter(function(r){return r===true;}).length,rej=G_diff.resolved.filter(function(r){return r===false;}).length;var parts=[];if(p)parts.push(p+" pending");if(a)parts.push(a+" accepted");if(rej)parts.push(rej+" rejected");document.getElementById("diffSummary").textContent=parts.join(" \xb7 ")||"done";}
function checkDiffDone(){if(G_diff.resolved.filter(function(r){return r===null;}).length===0)applyDiff();}
function applyDiff(){var text=document.getElementById("cvTa").value;for(var i=0;i<G_diff.ops.length;i++){if(!G_diff.resolved[i])continue;var r=applyOp(text,G_diff.ops[i]);if(r!==null)text=r;}document.getElementById("cvTa").value=text;cvStats();cvUpdateLineNumbers();cvUpdateMinimap();cvUpdateContextState();cvHideDiff();G_diff.ops=[];G_diff.resolved=[];var ta=document.getElementById("cvTa");ta.style.background="#1a2a1e";setTimeout(function(){ta.style.background="";},600);}
function setMode(m){G.mode=m;document.getElementById("bRag").className="mbtn"+(m==="rag"?" ar":"");document.getElementById("bChat").className="mbtn"+(m==="chat"?" ac":"");document.getElementById("bAgent").className="mbtn"+(m==="agent"?" aa":"");if(m==="rag")G.inp.placeholder="Ask your knowledge base...";else if(m==="agent")G.inp.placeholder="Give NOMAD a task...";else G.inp.placeholder="Chat freely...";}
function clearChat(){if(G.history.length>1)historySave(G.history);G.history=[];G.chat.innerHTML="";var e=document.createElement("div");e.className="empty";e.id="empty";e.innerHTML='<div class="ei">&#10022;</div><div class="et">Ask anything or open the canvas to collaborate.</div>';G.chat.appendChild(e);G.empty=e;}
function addMsg(role,content){if(G.empty)G.empty.style.display="none";var m=document.createElement("div");m.className="msg";var l=document.createElement("div");l.className="ml"+(role==="user"?" u":"");l.textContent=role==="user"?"You":"N.O.M.A.D";m.appendChild(l);var b=document.createElement("div");b.className="mb"+(role==="user"?" ut":"");if(role==="user")b.textContent=content;else b.innerHTML=fmt(content);m.appendChild(b);G.chat.appendChild(m);G.chat.scrollTop=G.chat.scrollHeight;return b;}
function addActs(el,text,isFb,fbQ){var a=document.createElement("div");a.className="ma";var cb=document.createElement("button");cb.className="mab";cb.innerHTML="&#128196; to canvas";var ct=text;cb.onclick=function(){writeToCv(ct);};a.appendChild(cb);if(isFb&&fbQ){var sb=document.createElement("button");sb.className="mab";sb.innerHTML="&#10003; save to kb";var cq=fbQ,ca=text;sb.onclick=function(){saveKB(sb,cq,ca);};a.appendChild(sb);}el.parentElement.appendChild(a);}
function showS(t){if(G.empty)G.empty.style.display="none";rmS();var e=document.createElement("div");e.className="srch";e.id="srch";e.innerHTML='<div class="dots"><span></span><span></span><span></span></div><span>'+esc(t)+"</span>";G.chat.appendChild(e);G.chat.scrollTop=G.chat.scrollHeight;}
function rmS(){var e=document.getElementById("srch");if(e)e.remove();}
function saveKB(btn,q,a){btn.disabled=true;btn.innerHTML="saving...";fetch("/save-to-kb",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q,answer:a})}).then(function(r){return r.json();}).then(function(d){if(d.status==="saved"){btn.className="mab saved";btn.innerHTML="&#10003; saved";}else{btn.innerHTML=d.message||"rejected";btn.disabled=false;}}).catch(function(){btn.innerHTML="error";btn.disabled=false;});}
var mRec=null,aCh=[];
function toggleRec(){if(G.streaming)return;var b=document.getElementById("micBtn");if(b.className.indexOf("rec")!==-1){if(mRec&&mRec.state!=="inactive")mRec.stop();b.className="ib";}else{navigator.mediaDevices.getUserMedia({audio:true}).then(function(s){mRec=new MediaRecorder(s,{mimeType:"audio/webm"});aCh=[];mRec.ondataavailable=function(e){aCh.push(e.data);};mRec.onstop=function(){var bl=new Blob(aCh,{type:"audio/webm"});s.getTracks().forEach(function(t){t.stop();});doSTT(bl);};mRec.start();b.className="ib rec";}).catch(function(){showToast("Mic access denied");});}}
function doSTT(blob){showS("Transcribing...");var fd=new FormData();fd.append("audio",blob,"r.webm");fetch("/stt",{method:"POST",body:fd}).then(function(r){return r.json();}).then(function(d){rmS();var t=d.text||"";if(t){G.inp.value=t;sendMsg();}else addMsg("assistant","Could not understand.");}).catch(function(){rmS();addMsg("assistant","STT unavailable.");});}
function sendMsg(){var text=G.inp.value.trim();if(!text||G.streaming)return;G.streaming=true;G.sendBtn.disabled=true;G.inp.value="";ar(G.inp);addMsg("user",text);G.history.push({role:"user",content:text});var canvasContent=(G.cvOpen&&cvHasContent())?cvGetContent():null;var ep=G.mode==="rag"?"/ask":G.mode==="agent"?"/agent":"/chat";showS(G.mode==="rag"?"Searching...":G.mode==="agent"?"Agent working...":"Thinking...");var ft="",fbt="",inFb=false,src=[],bEl=null,fbQ="",isFb=false,cvFn="";fetch(ep,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:text,history:G.history.slice(0,-1),canvas_content:canvasContent,image_data:G_file.data,image_type:G_file.type,image_name:G_file.name})}).then(async function(r){var reader=r.body.getReader(),decoder=new TextDecoder(),buf="";while(true){var rd=await reader.read();if(rd.done)break;buf+=decoder.decode(rd.value,{stream:true});var lines=buf.split("\n");buf=lines.pop();for(var line of lines){if(!line.startsWith("data: "))continue;var d=line.substring(6);if(d==="[DONE]")continue;try{var p=JSON.parse(d);if(p.type==="search_status"){rmS();showS(p.message);}else if(p.type==="sources"){src=p.sources;}else if(p.type==="canvas_start"){cvFn=p.filename||"";cvStreamStart();rmS();showS("Writing to canvas...");}else if(p.type==="canvas_token"){cvStreamToken(p.token);}else if(p.type==="canvas_done"){cvStreamEnd(cvFn||p.filename||"generated");rmS();}else if(p.type==="canvas_content"){writeToCv(p.content,p.filename||"generated");}else if(p.type==="canvas_patches"){showDiffOps(p.ops);rmS();}else if(p.type==="token"){if(!bEl){rmS();bEl=addMsg("assistant","");bEl.innerHTML='<span class="cur"></span>';}ft+=p.token;if(inFb)fbt+=p.token;bEl.innerHTML=fmt(ft)+'<span class="cur"></span>';G.chat.scrollTop=G.chat.scrollHeight;}else if(p.type==="fallback_start"){fbt="";inFb=true;}else if(p.type==="fallback_done"){inFb=false;isFb=true;fbQ=p.question;}else if(p.type==="done"){if(bEl){bEl.innerHTML=fmt(ft);if(src.length>0){var sd=document.createElement("div");sd.className="sources";var sh='<div class="sl">Sources</div>';for(var j=0;j<src.length;j++)sh+='<span class="st">'+esc(src[j])+"</span>";sd.innerHTML=sh;bEl.parentElement.appendChild(sd);}addActs(bEl,isFb?fbt:ft,isFb,fbQ);}G.history.push({role:"assistant",content:ft});while(G.history.length>20)G.history.shift();}else if(p.type==="error"){rmS();addMsg("assistant","Error: "+p.message);}}catch(e){}}}clearAttachment();G.streaming=false;G.sendBtn.disabled=false;G.inp.focus();}).catch(function(){rmS();addMsg("assistant","Connection error.");G.streaming=false;G.sendBtn.disabled=false;});}
function checkH(){fetch("/health").then(function(r){return r.json();}).then(function(d){document.getElementById("sQ").className="sd"+(d.qdrant?"":" off");document.getElementById("sL").className="sd"+(d.llm?"":" off");if(d.points!==undefined){document.getElementById("sP").style.display="flex";document.getElementById("sPn").textContent=d.points.toLocaleString();}}).catch(function(){});}
function toggleStats(){var p=document.getElementById("statsPanel");if(p.classList.contains("open")){p.classList.remove("open");}else{p.classList.add("open");loadStats();}}
function loadStats(){
  fetch("/pi-stats").then(r=>r.json()).then(renderPiStats).catch(function(){document.getElementById("piStats").innerHTML='<div class="stat-row"><span class="stat-label">Offline</span></div>';document.getElementById("sdPi").className="sd off";});
  fetch("/desktop-stats").then(r=>r.json()).then(renderDesktopStats).catch(function(){document.getElementById("nomadStats").innerHTML='<div class="stat-row"><span class="stat-label">Offline</span></div>';document.getElementById("sdNomad").className="sd off";});
  fetch("/xps13-stats").then(r=>r.json()).then(renderXpsStats).catch(function(){document.getElementById("xpsStats").innerHTML='<div class="stat-row"><span class="stat-label">Offline</span></div>';document.getElementById("sdXps").className="sd off";});
  fetch("/health").then(r=>r.json()).then(renderKbStats).catch(function(){});
  fetch("/service-status").then(r=>r.json()).then(renderSvcStats).catch(function(){});
}
function statBar(pct){var c=pct<60?"ok":pct<80?"warn":"err";return '<div class="stat-bar-wrap"><div class="stat-bar '+c+'" style="width:'+pct+'%"></div></div>';}
function renderMachineStats(data,elId,sdId){
  if(data.error){document.getElementById(elId).innerHTML='<div class="stat-row"><span class="stat-label">'+(data.error||"Offline")+"</span></div>";document.getElementById(sdId).className="sd off";return;}
  document.getElementById(sdId).className="sd";
  var ramPct=data.ram_total?Math.round((1-data.ram_available/data.ram_total)*100):0;
  var diskPct=data.disk_total?Math.round((1-data.disk_free/data.disk_total)*100):0;
  var h="";
  h+='<div class="stat-row"><span class="stat-label">Hostname</span><span class="stat-val">'+esc(data.hostname||"?")+'</span></div>';
  h+='<div class="stat-row"><span class="stat-label">RAM</span><span class="stat-val">'+(data.ram_total-data.ram_available)+" / "+data.ram_total+' MB</span></div>'+statBar(ramPct);
  h+='<div class="stat-row"><span class="stat-label">Disk</span><span class="stat-val">'+(data.disk_total-data.disk_free)+" / "+data.disk_total+' GB</span></div>'+statBar(diskPct);
  if(data.cpu_temp)h+='<div class="stat-row"><span class="stat-label">CPU Temp</span><span class="stat-val">'+data.cpu_temp+'&deg;C</span></div>';
  if(data.load)h+='<div class="stat-row"><span class="stat-label">Load</span><span class="stat-val">'+data.load.join(" / ")+'</span></div>';
  if(data.uptime)h+='<div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-val">'+esc(data.uptime)+'</span></div>';
  document.getElementById(elId).innerHTML=h;
}
function renderPiStats(d){renderMachineStats(d,"piStats","sdPi");}
function renderDesktopStats(d){
  renderMachineStats(d,"nomadStats","sdNomad");
  if(d.containers&&d.containers.length){var h='<div style="margin-top:8px;font-family:DM Mono,monospace;font-size:9px;color:var(--t3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px">Containers</div>';d.containers.forEach(function(c){h+='<div class="svc"><span class="sd"></span>'+esc(c)+"</div>";});document.getElementById("nomadStats").innerHTML+=h;}
}
function renderXpsStats(d){renderMachineStats(d,"xpsStats","sdXps");}
function renderKbStats(d){var h='<div class="stat-row"><span class="stat-label">Qdrant</span><span class="stat-val">'+(d.qdrant?"Online":"Offline")+'</span></div>';h+='<div class="stat-row"><span class="stat-label">Vectors</span><span class="stat-val">'+(d.points||0).toLocaleString()+'</span></div>';h+='<div class="stat-row"><span class="stat-label">LLM</span><span class="stat-val">'+(d.llm?"Online":"Offline")+'</span></div>';document.getElementById("kbStats").innerHTML=h;}
function renderSvcStats(svcs){
  var desktop=[],xps=[];
  svcs.forEach(function(s){
    var ok=s.ok?"":"  off";
    var el='<div class="svc"><span class="sd'+ok+'"></span>'+esc(s.name)+'<span class="svc-machine">'+(s.machine||"")+'</span></div>';
    if(s.machine==="xps13")xps.push(el);else desktop.push(el);
  });
  var h='<div class="svc-grid">';
  h+='<div><div style="font-family:DM Mono,monospace;font-size:9px;color:var(--t3);text-transform:uppercase;padding:4px 0 6px">Desktop</div>'+desktop.join("")+"</div>";
  h+='<div><div style="font-family:DM Mono,monospace;font-size:9px;color:var(--t3);text-transform:uppercase;padding:4px 0 6px">XPS13</div>'+xps.join("")+"</div>";
  h+="</div>";
  document.getElementById("svcStats").innerHTML=h;
}

// ── File attachment state ──
var G_file = {data: null, name: null, type: null};

// ── Canvas file loading (drag-drop + button) ──
function initCanvasDrop(){
  var panel=document.getElementById("cvPanel");
  var overlay=document.getElementById("cvDropOverlay");
  panel.addEventListener("dragover",function(e){e.preventDefault();overlay.classList.add("active");});
  panel.addEventListener("dragleave",function(e){if(!panel.contains(e.relatedTarget))overlay.classList.remove("active");});
  panel.addEventListener("drop",function(e){
    e.preventDefault();overlay.classList.remove("active");
    var f=e.dataTransfer.files[0];if(f)handleCanvasFile(f);
  });
}
function cvLoadFile(input){var f=input.files[0];if(f)handleCanvasFile(f);input.value="";}
function handleCanvasFile(file){
  var name=file.name;var type=file.type;
  showToast("Loading "+name+"...",2000);
  if(type==="application/pdf"){
    // Send to backend for text extraction
    var fd=new FormData();fd.append("file",file);
    fetch("/extract-file",{method:"POST",body:fd})
      .then(r=>r.json()).then(function(d){
        if(d.text){
          writeToCv(d.text, name.replace(/\.pdf$/i,".txt"));
          showToast("PDF loaded: "+d.pages+" pages");
        } else showToast("PDF extraction failed: "+(d.error||"unknown"),3000);
      }).catch(function(){showToast("Upload failed",3000);});
  } else if(type.startsWith("image/")){
    // Images: attach to next message for LLM vision
    var reader=new FileReader();
    reader.onload=function(e){
      G_file.data=e.target.result.split(",")[1];
      G_file.name=name;G_file.type=type;
      document.getElementById("fileBadgeName").textContent=name;
      document.getElementById("fileBadge").className="file-badge visible";
      showToast("Image attached — send a message to analyze it");
    };
    reader.readAsDataURL(file);
  } else {
    // Text/code files: load directly into canvas
    var reader=new FileReader();
    reader.onload=function(e){
      writeToCv(e.target.result, name);
      showToast(name+" loaded into canvas");
    };
    reader.readAsText(file);
  }
}
function clearAttachment(){
  G_file={data:null,name:null,type:null};
  document.getElementById("fileBadge").className="file-badge";
  document.getElementById("fileBadgeName").textContent="";
}

// ── Chat History (localStorage) ──
var HIST_KEY="nomad_chat_history";
var HIST_MAX=50;
function historySave(messages){
  if(!messages||messages.length<2)return;
  try{
    var sessions=historyLoad();
    var first=messages.find(function(m){return m.role==="user";});
    var preview=first?first.content.substring(0,120):"(empty)";
    sessions.unshift({
      id:Date.now(),
      date:new Date().toISOString(),
      preview:preview,
      count:messages.length,
      messages:messages.slice(-40)
    });
    if(sessions.length>HIST_MAX)sessions=sessions.slice(0,HIST_MAX);
    localStorage.setItem(HIST_KEY,JSON.stringify(sessions));
  }catch(e){}
}
function historyLoad(){
  try{return JSON.parse(localStorage.getItem(HIST_KEY)||"[]");}catch(e){return [];}
}
function toggleHistory(){
  var p=document.getElementById("historyPanel");
  if(p.classList.contains("open")){p.classList.remove("open");}
  else{renderHistoryList();p.classList.add("open");}
}
function renderHistoryList(){
  var sessions=historyLoad();
  var list=document.getElementById("historyList");
  if(!sessions.length){list.innerHTML='<div class="history-empty">No saved conversations yet.<br>Conversations are auto-saved when you clear chat.</div>';return;}
  list.innerHTML="";
  sessions.forEach(function(s){
    var d=document.createElement("div");d.className="history-item";
    var date=new Date(s.date).toLocaleString();
    d.innerHTML='<div class="history-item-date">'+esc(date)+'</div>'
             +'<div class="history-item-preview">'+esc(s.preview)+'</div>'
             +'<div class="history-item-meta">'+s.count+' messages</div>';
    d.onclick=function(){historyRestore(s);};
    list.appendChild(d);
  });
}
function historyRestore(session){
  toggleHistory();
  G.history=session.messages;
  G.chat.innerHTML="";
  if(G.empty)G.empty.style.display="none";
  session.messages.forEach(function(m){addMsg(m.role,m.content);});
  showToast("Conversation restored ("+session.messages.length+" messages)");
}
function historyClear(){
  if(!confirm("Clear all saved conversations?"))return;
  localStorage.removeItem(HIST_KEY);
  renderHistoryList();
  showToast("History cleared");
}

function init(){initCanvasResize();initCanvasDrop();renderTabs();loadActiveTab();checkH();setInterval(checkH,30000);G.inp.focus();}
init();
</script>
</body>
</html>
"""
HTML_PAGE = HTML_PAGE.replace("ACTUAL_DOZZLE", DOZZLE_URL).replace("ACTUAL_NOMAD", f"http://{NOMAD_HOST}:8080")
HTML_PAGE = HTML_PAGE.replace("DOZZLE_PLACEHOLDER", DOZZLE_URL).replace("NOMAD_PLACEHOLDER", f"http://{NOMAD_HOST}:8080")

try:
    VOICE_PAGE = open(os.path.expanduser("~/nomad-static/voice.html")).read()
except:
    VOICE_PAGE = "<h1>Voice page not found</h1>"

# ═══ Helpers ══════════════════════════════════════════════
def sse(tp, **kw):
    return "data: " + json.dumps({"type": tp, **kw}) + "\n\n"

HDRS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
NO_ANS = ["not in the context","does not contain","no relevant","not mentioned","cannot find","no information","doesn't contain","not found in the","the context does not","not present in","geen relevante","niet in de context"]

def stream_llm(msgs, max_tokens=3000):
    try:
        r = req.post(LLAMA_URL+"/v1/chat/completions", json={
            "messages": msgs,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False}
        }, stream=True, timeout=120)
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "): line = line[6:]
                if line == "[DONE]": break
                try:
                    d = json.loads(line)
                    tk = d.get("choices",[{}])[0].get("delta",{}).get("content","")
                    if tk: yield sse("token", token=tk)
                except: pass
    except Exception as e:
        yield sse("error", message="LLM: "+str(e))

def stream_llm_canvas(msgs, max_tokens=3000):
    """Stream LLM output that goes to canvas instead of chat."""
    try:
        r = req.post(LLAMA_URL+"/v1/chat/completions", json={
            "messages": msgs,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False}
        }, stream=True, timeout=120)
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "): line = line[6:]
                if line == "[DONE]": break
                try:
                    d = json.loads(line)
                    tk = d.get("choices",[{}])[0].get("delta",{}).get("content","")
                    if tk: yield sse("canvas_token", token=tk)
                except: pass
    except Exception as e:
        yield sse("error", message="LLM: "+str(e))

def helper_llm(messages, max_tokens=100):
    try:
        r = req.post(HELPER_URL + "/api/chat", json={
            "model": HELPER_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "keep_alive": "60m"}
        }, timeout=20)
        return r.json().get("message", {}).get("content", "").strip()
    except:
        return ""

def contextualize_question(question, history):
    if not history:
        return question
    recent = history[-6:]
    conv = ""
    for m in recent:
        role = "User" if m["role"] == "user" else "Assistant"
        conv += role + ": " + m["content"][:200] + "\n"
    rewritten = helper_llm([
        {"role": "system", "content": "Given a conversation and a follow-up question, rewrite the follow-up into a standalone question. Return ONLY the rewritten question. If already standalone, return as-is."},
        {"role": "user", "content": "Conversation:\n" + conv + "\nFollow-up: " + question + "\nStandalone:"}
    ], max_tokens=100)
    return rewritten if len(rewritten) > 5 else question

def validate_and_index(question, answer):
    try:
        chunk = "Question: "+question+"\nAnswer: "+answer
        emb = get_embedding(chunk)                                     # <-- Aangepast
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        try:
            ex = client.query_points(collection_name=COLLECTION, query=emb, limit=1)
            if ex.points and ex.points[0].score > 0.85:
                return False, "Duplicate (score:"+str(round(ex.points[0].score,2))+")"
        except: pass
        vt = helper_llm([
            {"role": "system", "content": "Is this answer factual and useful? Reply ONLY YES or NO."},
            {"role": "user", "content": "Q:"+question+"\nA:"+answer}
        ], max_tokens=10).upper()
        if not vt.startswith("YES"): return False, "Quality: "+vt
        pid = abs(int(hashlib.md5(chunk.encode()).hexdigest(),16)) % (2**63)
        client.upsert(collection_name=COLLECTION, points=[models.PointStruct(
            id=pid, vector=emb,
            payload={"source":"llm_generated","content_type":"llm_generated","article_title":"Q: "+question[:80],"content":chunk,"generated_at":time.strftime("%Y-%m-%d %H:%M:%S"),"validated":True}
        )])
        return True, "Saved"
    except Exception as e:
        return False, str(e)

def get_pi_stats():
    s = {}
    try:
        with open("/proc/meminfo") as f: mi = f.read()
        for l in mi.split("\n"):
            if l.startswith("MemTotal:"): s["ram_total"] = int(l.split()[1])//1024
            elif l.startswith("MemAvailable:"): s["ram_available"] = int(l.split()[1])//1024
    except: pass
    try:
        st = os.statvfs("/"); s["disk_total"]=(st.f_blocks*st.f_frsize)//(1024**3); s["disk_free"]=(st.f_bavail*st.f_frsize)//(1024**3)
    except: pass
    try: s["load"] = [round(l,2) for l in os.getloadavg()]
    except: pass
    try:
        with open("/proc/uptime") as f: up = float(f.read().split()[0])
        s["uptime"] = f"{int(up//86400)}d {int((up%86400)//3600)}h {int((up%3600)//60)}m"
    except: pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f: s["cpu_temp"] = round(int(f.read().strip())/1000,1)
    except: pass
    s["hostname"] = os.uname().nodename
    return s

def build_canvas_context(canvas_content):
    if not canvas_content or not canvas_content.strip():
        return None
    return (
        "The user has a document open in the canvas:\n"
        "```\n"
        + canvas_content.strip()[:4000] +
        "\n```\n"
        "You can read and reference this document. "
        "If the user asks you to edit, fix, improve, update, rewrite or otherwise change the canvas, "
        "respond with a brief acknowledgement in chat AND use [CANVAS_UPDATE filename.ext] on its own line, "
        "followed by the complete updated content, then [/CANVAS_UPDATE] on its own line. "
        "Choose an appropriate filename extension (e.g. .py .js .md .sh .html). "
        "Do NOT include the [CANVAS_UPDATE] block in your chat response."
    )

def detect_canvas_update(text):
    pattern = r'\[CANVAS_UPDATE(?:\s+([^\]]+))?\]([\s\S]*?)\[/CANVAS_UPDATE\]'
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return text, None, None
    filename = (m.group(1) or "").strip() or "updated"
    canvas_content = m.group(2).strip()
    chat_text = text[:m.start()].strip() + ("\n\n" + text[m.end():].strip() if text[m.end():].strip() else "")
    return chat_text.strip(), canvas_content, filename

def canvas_edit_gen(question, canvas):
    fn = guess_filename(canvas or "", question)

    if is_small_edit(question, canvas):
        yield sse("search_status", message="Generating patch...")
        try:
            doc = (canvas or "")[:5000]
            r = req.post(LLAMA_URL+"/v1/chat/completions", json={
                "messages": [
                    {"role":"system","content":PATCH_SYSTEM},
                    {"role":"user","content":"Document:\n```\n"+doc+"\n```\n\nInstruction: "+question+"\n\nJSON array of ops:"}
                ],
                "max_tokens":1200,"stream":False,
                "chat_template_kwargs":{"enable_thinking":False}
            }, timeout=60)
            raw = r.json().get("choices",[{}])[0].get("message",{}).get("content","").strip()
            raw = re.sub(r"^```[a-zA-Z]*\n?","",raw).rstrip("`").strip()
            ops = json.loads(raw)
            if not isinstance(ops, list): raise ValueError("not a list")
            valid = [op for op in ops if isinstance(op,dict) and "op" in op]
            if not valid: raise ValueError("empty ops")
            yield sse("canvas_patches", ops=valid)
            n = len(valid)
            yield sse("token", token="\u2713 "+str(n)+" change"+(("s" if n!=1 else "")+" ready \u2014 review in the diff tab."))
            yield sse("done")
            return
        except Exception:
            yield sse("search_status", message="Patch failed, rewriting...")

    yield sse("search_status", message="Rewriting canvas...")
    sys_prompt = ("You are a precise code and text editor. "
        "Output ONLY the complete updated document \u2014 no explanation, no preamble, "
        "no markdown fences unless the document itself uses them.")
    msgs = [
        {"role":"system","content":sys_prompt},
        {"role":"user","content":"Document:\n```\n"+(canvas or "")+"\n```\n\nInstruction: "+question+"\n\nOutput the complete updated document now:"}
    ]
    yield sse("canvas_start", filename=fn)
    for c in stream_llm_canvas(msgs, max_tokens=3000):
        yield c
    yield sse("canvas_done", filename=fn)
    yield sse("token", token="\u2713 Canvas updated.")
    yield sse("done")

# ═══ Routes ═══════════════════════════════════════════════
@app.route("/")
def index(): return HTML_PAGE

@app.route("/voice")
def voice_page(): return VOICE_PAGE

@app.route("/voice-proxy", methods=["POST"])
def voice_proxy():
    if "audio" not in request.files:
        return Response("data: "+json.dumps({"type":"error","message":"No audio"})+"\n\n", content_type="text/event-stream")
    audio = request.files["audio"]
    voice = request.form.get("voice", "lessac")
    try:
        files = {"audio": (audio.filename, audio.stream, audio.content_type)}
        resp = req.post(VOICE_URL+"/voice-chat", files=files, data={"voice":voice}, stream=True, timeout=60)
        def relay():
            for line in resp.iter_lines():
                if line: yield line.decode("utf-8") + "\n"
        return Response(relay(), content_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    except Exception as e:
        return Response("data: "+json.dumps({"type":"error","message":str(e)})+"\n\n", content_type="text/event-stream")

@app.route("/voice-tts", methods=["POST"])
def voice_tts():
    text = request.json.get("text",""); voice = request.json.get("voice","lessac")
    if not text: return jsonify({"error":"No text"}), 400
    try:
        r = req.post(VOICE_URL+"/tts", json={"text":text,"voice":voice}, timeout=30)
        return jsonify(r.json())
    except Exception as e: return jsonify({"error":str(e)}), 500

@app.route("/voice-clear-proxy", methods=["POST"])
def voice_clear_proxy():
    try: return jsonify(req.post(VOICE_URL+"/voice-clear", timeout=5).json())
    except: return jsonify({"status":"error"})

@app.route("/health")
def health():
    s = {"qdrant":False,"llm":False,"points":0}
    try:
        r = req.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION}", timeout=3)
        s["qdrant"] = True; s["points"] = r.json()["result"]["points_count"]
    except: pass
    try: s["llm"] = req.get(f"{LLAMA_URL}/health", timeout=3).status_code == 200
    except: pass
    return jsonify(s)

@app.route("/pi-stats")
def pi_stats(): return jsonify(get_pi_stats())

@app.route("/desktop-stats")
def desktop_stats():
    try: return jsonify(req.get(f"{STATS_URL}/stats", timeout=5).json())
    except: return jsonify({"error":"offline"}), 503

@app.route("/xps13-stats")
def xps13_stats():
    import subprocess as sp, base64
    try:
        r = req.get("http://192.168.2.20:8083/stats", timeout=3)
        if r.status_code == 200:
            return jsonify(r.json())
    except: pass
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
        key = os.path.expanduser("~/.ssh/id_ed25519")
        if not os.path.exists(key):
            key = os.path.expanduser("~/.ssh/id_rsa")
        result = sp.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
             "-o", "BatchMode=yes", "-i", key, "ioncap@192.168.2.20", ssh_cmd],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0 and result.stdout.strip():
            return jsonify(json.loads(result.stdout.strip()))
        return jsonify({"error": "SSH failed", "detail": result.stderr[:300]}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 503

@app.route("/service-status")
def service_status():
    svcs = [
        {"name":"LLM (Qwen3 4B)","url":f"{NOMAD_HOST}:8081","machine":"desktop"},
        {"name":"Qdrant","url":f"{NOMAD_HOST}:6333","machine":"desktop"},
        {"name":"Whisper (STT)","url":f"{NOMAD_HOST}:8082","machine":"desktop"},
        {"name":"Ollama Desktop","url":f"{NOMAD_HOST}:11434","machine":"desktop"},
        {"name":"Stats","url":f"{NOMAD_HOST}:8083","machine":"desktop"},
        {"name":"Dozzle","url":f"{NOMAD_HOST}:9999","machine":"desktop"},
        {"name":"Ollama XPS13 (embed)","url":"192.168.2.20:11434","machine":"xps13"},
        {"name":"Voice server","url":"192.168.2.20:8085","machine":"xps13"},
        {"name":"Grafana","url":"192.168.2.20:3000","machine":"xps13"},
        {"name":"Prometheus","url":"192.168.2.20:9090","machine":"xps13"},
    ]
    for s in svcs:
        try: s["ok"] = req.get(f"http://{s['url']}/", timeout=2).status_code < 500
        except: s["ok"] = False
    return jsonify(svcs)

@app.route("/tts", methods=["POST"])
def tts():
    text = request.json.get("text","")
    if not text: return jsonify({"error":"No text"}), 400
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t: tp = t.name
        subprocess.run([PIPER_BIN,"--model",PIPER_MODEL,"--output_file",tp], input=text, capture_output=True, text=True, timeout=30)
        with open(tp,"rb") as f: audio = base64.b64encode(f.read()).decode("utf-8")
        os.unlink(tp); return jsonify({"audio":audio})
    except Exception as e: return jsonify({"error":str(e)}), 500

@app.route("/stt", methods=["POST"])
def stt():
    if "audio" not in request.files: return jsonify({"error":"No audio"}), 400
    a = request.files["audio"]
    try:
        files = {"file":(a.filename,a.stream,a.content_type)}
        return jsonify(req.post(WHISPER_URL+"/inference", files=files, data={"response_format":"json","language":"en"}, timeout=30).json())
    except Exception as e: return jsonify({"error":str(e)}), 500

@app.route("/save-to-kb", methods=["POST"])
def save_to_kb():
    q = request.json.get("question",""); a = request.json.get("answer","")
    if not q or not a or len(a) < 50: return jsonify({"status":"error","message":"Too short"})
    ok, msg = validate_and_index(q, a)
    return jsonify({"status":"saved" if ok else "rejected","message":msg})

# ═══════════════════════════════════════════════════
# CHAT endpoint
# ═══════════════════════════════════════════════════
@app.route("/extract-file", methods=["POST"])
def extract_file():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    fname = f.filename.lower()
    try:
        if fname.endswith(".pdf"):
            try:
                from pdfminer.high_level import extract_text_to_fp
                from pdfminer.layout import LAParams
                import io
                f.stream.seek(0)
                out = io.StringIO()
                extract_text_to_fp(f.stream, out, laparams=LAParams(), output_type='text', codec='utf-8')
                text = out.getvalue().strip()
                f.stream.seek(0)
                pages = f.stream.read().count(b"/Page ")
                return jsonify({"text": text[:50000], "pages": pages, "truncated": len(text) > 50000})
            except ImportError:
                try:
                    import pypdf, io
                    f.stream.seek(0)
                    reader = pypdf.PdfReader(f.stream)
                    text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
                    return jsonify({"text": text[:50000], "pages": len(reader.pages), "truncated": len(text) > 50000})
                except ImportError:
                    return jsonify({"error": "No PDF library. Install: pip install pdfminer.six --break-system-packages"}), 500
        else:
            text = f.read().decode("utf-8", errors="replace")
            return jsonify({"text": text[:100000], "pages": 1, "truncated": len(text) > 100000})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat_ep():
    q = request.json.get("question","")
    h = request.json.get("history",[])
    canvas = request.json.get("canvas_content", None)
    image_data = request.json.get("image_data", None)
    image_type = request.json.get("image_type", "image/jpeg")
    if not q: return Response(sse("error",message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(q, canvas):
            for ev in canvas_edit_gen(q, canvas): yield ev
            return

        yield sse("search_status", message="Thinking...")
        sys_prompt = "You are N.O.M.A.D, a helpful AI assistant running locally. Be friendly, concise, thoughtful."
        canvas_ctx = build_canvas_context(canvas)
        if canvas_ctx:
            sys_prompt += "\n\n" + canvas_ctx

        msgs = [{"role":"system","content":sys_prompt}]
        for m in h[-MAX_HISTORY:]: msgs.append({"role":m["role"],"content":m["content"]})

        if image_data:
            msgs.append({"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:{image_type};base64,{image_data}"}},
                {"type":"text","text":q}
            ]})
        else:
            msgs.append({"role":"user","content":q})

        for c in stream_llm(msgs):
            yield c
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)

# ═══════════════════════════════════════════════════
# ASK (RAG) endpoint
# ═══════════════════════════════════════════════════
@app.route("/ask", methods=["POST"])
def ask():
    question = request.json.get("question","")
    history = request.json.get("history",[])
    canvas = request.json.get("canvas_content", None)
    image_data = request.json.get("image_data", None)
    image_type = request.json.get("image_type", "image/jpeg")
    if not question: return Response(sse("error",message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(question, canvas):
            for ev in canvas_edit_gen(question, canvas): yield ev
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
                emb = get_embedding(search_question)                     # <-- Aangepast
            except:
                yield sse("error", message="Embedding failed"); return

            for col in client.get_collections().collections:
                try:
                    res = client.query_points(collection_name=col.name, query=emb, limit=MAX_RESULTS)
                    for r in res.points:
                        if r.score > SCORE_THRESHOLD and r.id not in seen:
                            seen.add(r.id)
                            pl = r.payload or {}
                            title = pl.get("article_title","?")
                            cont = pl.get("content", pl.get("text", str(pl)))
                            ctx.append("["+title+"]\n"+cont[:MAX_CHUNK_LEN])
                            if title not in sources: sources.append(title)
                except: pass
            ctx = ctx[:6]; sources = sources[:6]
        except Exception as e:
            yield sse("error", message="Search: "+str(e)); return

        yield sse("sources", sources=sources)

        sys_prompt = "You are N.O.M.A.D, a knowledgeable AI assistant. Answer using the provided reference material. Synthesize from multiple sources when possible. Be accurate and clear. If the material doesn't cover the question, say what you can and indicate what's missing."
        canvas_ctx = build_canvas_context(canvas)
        if canvas_ctx:
            sys_prompt += "\n\n" + canvas_ctx

        if not ctx:
            yield sse("token", token="No relevant documents found.\n\n---\n*Answering from my own knowledge...*\n\n")
            yield sse("fallback_start")
            msgs = [{"role":"system","content":sys_prompt},{"role":"user","content":question}]
            full = []
            for c in stream_llm(msgs):
                yield c
                try:
                    d = json.loads(c.replace("data: ","").strip())
                    if d.get("type") == "token": full.append(d["token"])
                except: pass
            _, cv_content, cv_fn = detect_canvas_update("".join(full))
            if cv_content: yield sse("canvas_content", content=cv_content, filename=cv_fn)
            yield sse("fallback_done", question=question)
            yield sse("done"); return

        yield sse("search_status", message=f"Generating from {len(ctx)} sources...")
        context = "\n\n---\n\n".join(ctx)
        msgs = [{"role":"system","content":sys_prompt}]
        for m in history[-4:]: msgs.append({"role":m["role"],"content":m["content"][:300]})
        msgs.append({"role":"user","content":"Reference material:\n"+context+"\n\nQuestion: "+question})

        collected = []
        for c in stream_llm(msgs):
            yield c
            try:
                d = json.loads(c.replace("data: ","").strip())
                if d.get("type") == "token": collected.append(d["token"])
            except: pass

        full = "".join(collected)
        _, cv_content, cv_fn = detect_canvas_update(full)
        if cv_content: yield sse("canvas_content", content=cv_content, filename=cv_fn)

        if any(p in full.lower() for p in NO_ANS):
            yield sse("token", token="\n\n---\n*Searching my own knowledge...*\n\n")
            yield sse("fallback_start")
            fb_msgs = [{"role":"system","content":"You are N.O.M.A.D. The knowledge base didn't have a good answer. Answer using your own knowledge. Be concise and helpful."},{"role":"user","content":question}]
            fb_full = []
            for c in stream_llm(fb_msgs):
                yield c
                try:
                    d = json.loads(c.replace("data: ","").strip())
                    if d.get("type") == "token": fb_full.append(d["token"])
                except: pass
            _, cv_content2, cv_fn2 = detect_canvas_update("".join(fb_full))
            if cv_content2: yield sse("canvas_content", content=cv_content2, filename=cv_fn2)
            yield sse("fallback_done", question=question)

        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)

# ═══════════════════════════════════════════════════
# CANVAS GENERATE endpoint
# ═══════════════════════════════════════════════════
PATCH_SYSTEM = """You are a precise text editor. Given a document and an edit instruction, output ONLY a JSON array of patch operations. No explanation, no markdown, just the JSON array.

Each operation must be one of:
{"op":"replace","old":"exact text to find","new":"replacement text"}
{"op":"delete","text":"exact text to remove"}
{"op":"insert_after","after":"text to find","new":"text to insert after it"}
{"op":"insert_before","before":"text to find","new":"text to insert before it"}
{"op":"append","new":"text to add at end"}

Rules:
- "old", "text", "after", "before" must be exact verbatim substrings from the document
- Keep each change minimal — only touch what needs changing
- Use multiple ops if needed
- Output ONLY the JSON array, nothing else"""

def is_small_edit(question, canvas):
    if not canvas: return False
    if len(canvas) < 200 or len(canvas) > 6000: return False
    q = question.lower()
    big_ops = ['rewrite','herschrij','overschrij','translate','vertaal','format',
               'restructure','simplify','vereenvoudig','converteer','zet om']
    if any(w in q for w in big_ops): return False
    small_ops = ['fix','correct','rename','change','update','add','remove','delete',
                 'insert','replace','typo','bug','error',
                 'verander','wijzig','voeg toe','verwijder','verbeter de',
                 'functie','regel','variabele']
    return any(w in q for w in small_ops)

@app.route("/canvas-patch", methods=["POST"])
def canvas_patch():
    question = request.json.get("question","")
    canvas = request.json.get("canvas_content","")
    if not question or not canvas:
        return jsonify({"error":"Missing question or canvas"}), 400

    doc = canvas[:5000]
    try:
        r = req.post(LLAMA_URL+"/v1/chat/completions", json={
            "messages": [
                {"role":"system","content":PATCH_SYSTEM},
                {"role":"user","content":f"Document:\n```\n{doc}\n```\n\nInstruction: {question}\n\nJSON array of ops:"}
            ],
            "max_tokens": 1200,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking":False}
        }, timeout=60)
        raw = r.json().get("choices",[{}])[0].get("message",{}).get("content","").strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?","",raw).rstrip("`").strip()
        ops = json.loads(raw)
        if not isinstance(ops, list): raise ValueError("Not a list")
        valid = [op for op in ops if isinstance(op,dict) and "op" in op]
        return jsonify({"ops": valid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/canvas-generate", methods=["POST"])
def canvas_gen():
    question = request.json.get("question","")
    canvas = request.json.get("canvas_content", None)
    if not question: return Response(sse("error",message="No question"), content_type="text/event-stream")

    match = re.match(r"^(?:write to canvas|canvas write|generate|create):\s*([\s\S]+)", question, re.IGNORECASE)
    prompt = match.group(1) if match else question

    def gen():
        fn = "generated.md"
        pl = prompt.lower()
        if any(x in pl for x in ["python","script","def ","class "]): fn="generated.py"
        elif any(x in pl for x in ["javascript","node","react","function"]): fn="generated.js"
        elif any(x in pl for x in ["html","webpage","website"]): fn="generated.html"
        elif any(x in pl for x in ["bash","shell","#!/"]): fn="generated.sh"

        sys_prompt = "Write the requested content directly. No preamble. Clean, well-formatted text or code. Use markdown where appropriate."
        if canvas:
            sys_prompt += f"\n\nThe user currently has this in the canvas:\n```\n{canvas[:2000]}\n```\nIf asked to update/improve it, write the complete updated version."

        msgs = [
            {"role":"system","content":sys_prompt},
            {"role":"user","content":prompt}
        ]

        yield sse("canvas_start", filename=fn)
        for c in stream_llm_canvas(msgs):
            yield c
        yield sse("canvas_done", filename=fn)
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)

# ═══════════════════════════════════════════════════
# AGENT endpoint
# ═══════════════════════════════════════════════════
AGENT_SYSTEM = """You are N.O.M.A.D Agent — direct, efficient, sharp. Complete tasks with minimal words.

Tools available (call with JSON on its own line):
{"tool": "search_kb", "args": {"query": "..."}}
{"tool": "search_web", "args": {"query": "..."}}
{"tool": "run_command", "args": {"machine": "pi|desktop|xps13", "command": "..."}}
{"tool": "save_note", "args": {"title": "...", "content": "..."}}
{"tool": "network_scan", "args": {}}
{"tool": "system_status", "args": {}}
{"tool": "read_url", "args": {"url": "..."}}
{"tool": "weather", "args": {"city": "..."}}
{"tool": "dutch_temperatures", "args": {}}
{"tool": "crypto", "args": {}}
{"tool": "public_ip", "args": {}}
{"tool": "wikipedia", "args": {"query": "..."}}
{"tool": "exchange_rates", "args": {"base": "EUR"}}
{"tool": "news_headlines", "args": {}}

Rules:
- One short line explaining what you're doing, then the JSON tool call
- After tool results: 2-3 sentence summary max
- Chain tools when needed"""

CANVAS_EDIT_PATTERNS = re.compile(
    r'\b(fix|rewrit|improv|updat|edit|refactor|clean|optimis|optimiz|extend|'
    r'translat|simplif|\badd\b|remov|delet|chang|modif|correct|format|renam|'
    r'replac|insert|append|overschrij|herschrij|verbeter|aanpass|'
    r'voeg\s+\w+\s+toe|verwijder|vertaal|vereenvoudig|verander|wijzig|'
    r'schrijf|genereer|zet\s+om|converteer)',
    re.IGNORECASE
)

SAFE_COMMANDS = ["ls","cat","head","tail","grep","find","wc","df","free","uptime","hostname","uname","whoami","date","ps","top","ip","ping","nmap","arp","ss","netstat","curl","wget","docker","systemctl","journalctl","sensors","lsblk","lscpu","du","file","stat","which","echo","sort","uniq","awk","sed","tr","cut","tee","nproc","lsusb","lspci"]
MACHINE_MAP = {
    "pi": {"host":"localhost","user":"ioncap"},
    "desktop": {"host":"nomad.home","user":"ioncap"},
    "xps13": {"host":"192.168.2.20","user":"ioncap"},
}

def agent_search_kb(query):
    try:
        emb = get_embedding(query)                                     # <-- Aangepast
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        results = client.query_points(collection_name=COLLECTION, query=emb, limit=5)
        output = []
        for r in results.points:
            pl = r.payload or {}
            output.append(f"[{pl.get('article_title','?')}] (score:{r.score:.2f})\n{pl.get('content','')[:300]}")
        return "\n\n---\n".join(output) if output else "No results found."
    except Exception as e: return f"Search error: {e}"

def agent_run_command(machine, command):
    cmd_parts = command.strip().split()
    if not cmd_parts: return "Empty command"
    if cmd_parts[0] not in SAFE_COMMANDS:
        return f"Command '{cmd_parts[0]}' not allowed."
    machine = machine.lower().strip()
    if machine not in MACHINE_MAP: return f"Unknown machine: {machine}"
    try:
        import subprocess as sp
        if machine == "pi":
            result = sp.run(command, shell=True, capture_output=True, text=True, timeout=15)
        else:
            m = MACHINE_MAP[machine]
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {m['user']}@{m['host']} '{command}'"
            result = sp.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if result.stderr.strip(): output += "\nSTDERR: " + result.stderr.strip()
        return output[:2000] if output else "(no output)"
    except Exception as e: return f"Command error: {e}"

def agent_network_scan():
    try:
        import subprocess as sp
        result = sp.run("arp -a", shell=True, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        nmap = sp.run("which nmap", shell=True, capture_output=True, text=True)
        if nmap.returncode == 0:
            scan = sp.run("nmap -sn 192.168.2.0/24 2>/dev/null | grep -E 'scan report|MAC'", shell=True, capture_output=True, text=True, timeout=30)
            if scan.stdout.strip(): output += "\n\nNmap:\n" + scan.stdout.strip()
        return output if output else "No devices found"
    except Exception as e: return f"Scan error: {e}"

def agent_system_status():
    stats = {}
    try: stats["pi"] = get_pi_stats()
    except: stats["pi"] = {"error":"unavailable"}
    try: stats["desktop"] = req.get(f"{STATS_URL}/stats", timeout=5).json()
    except: stats["desktop"] = {"error":"unavailable"}
    try:
        r = req.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION}", timeout=3)
        d = r.json()["result"]
        stats["qdrant"] = {"vectors":d["points_count"],"status":d["status"]}
    except: stats["qdrant"] = {"error":"unavailable"}
    return json.dumps(stats, indent=2)

def agent_read_url(url):
    try:
        r = req.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
        text = re.sub(r'<script[^>]*>.*?</script>','',r.text,flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>','',text,flags=re.DOTALL)
        text = re.sub(r'<[^>]+>',' ',text)
        text = re.sub(r'\s+',' ',text).strip()
        return text[:3000]
    except Exception as e: return f"Fetch error: {e}"

def agent_save_note(title, content):
    try:
        chunk = f"Note: {title}\n{content}"
        emb = get_embedding(chunk)                                     # <-- Aangepast
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        pid = abs(int(hashlib.md5(chunk.encode()).hexdigest(),16)) % (2**63)
        client.upsert(collection_name=COLLECTION, points=[models.PointStruct(
            id=pid, vector=emb,
            payload={"source":"agent_note","content_type":"agent_note","article_title":title,"content":chunk,"generated_at":time.strftime("%Y-%m-%d %H:%M:%S")}
        )])
        return f"Saved: {title}"
    except Exception as e: return f"Save error: {e}"

def agent_weather(city="Amsterdam"):
    try:
        geo = req.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1", timeout=10).json()
        if not geo.get("results"): return f"City not found: {city}"
        r = geo["results"][0]
        lat,lon,name,country = r["latitude"],r["longitude"],r["name"],r.get("country","")
        w = req.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,apparent_temperature,precipitation&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code&timezone=auto&forecast_days=3", timeout=10).json()
        cur = w["current"]; daily = w["daily"]
        codes = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Foggy",51:"Light drizzle",61:"Slight rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Thunderstorm"}
        desc = codes.get(cur.get("weather_code",0),"?")
        result = f"{name}, {country}: {desc}, {cur['temperature_2m']}°C (feels {cur['apparent_temperature']}°C), wind {cur['wind_speed_10m']} km/h\n"
        result += "Forecast:\n"
        for i in range(min(3,len(daily["time"]))):
            d_desc = codes.get(daily["weather_code"][i],"?")
            result += f"  {daily['time'][i]}: {d_desc}, {daily['temperature_2m_min'][i]}-{daily['temperature_2m_max'][i]}°C\n"
        return result
    except Exception as e: return f"Weather error: {e}"

def agent_dutch_temperatures():
    cities = ["Amsterdam","Rotterdam","Utrecht","Den Haag","Eindhoven","Groningen","Maastricht","Leeuwarden"]
    results = []
    codes = {0:"☀️",1:"🌤",2:"⛅",3:"☁️",51:"🌦",61:"🌧",80:"🌦",95:"⛈"}
    for city in cities:
        try:
            geo = req.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&country=NL", timeout=5).json()
            if geo.get("results"):
                lat,lon = geo["results"][0]["latitude"],geo["results"][0]["longitude"]
                w = req.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code", timeout=5).json()
                icon = codes.get(w["current"]["weather_code"],"?")
                results.append(f"  {icon} {city}: {w['current']['temperature_2m']}°C")
        except: results.append(f"  ? {city}: unavailable")
    return "NL temperatures:\n" + "\n".join(results)

def agent_crypto_prices():
    try:
        r = req.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,cardano,dogecoin&vs_currencies=eur,usd&include_24hr_change=true", timeout=10)
        data = r.json()
        names = {"bitcoin":"BTC","ethereum":"ETH","solana":"SOL","cardano":"ADA","dogecoin":"DOGE"}
        result = "Crypto:\n"
        for coin,sym in names.items():
            if coin in data:
                d = data[coin]; ch = d.get("eur_24h_change",0); arrow = "↑" if ch>0 else "↓"
                result += f"  {sym}: €{d.get('eur',0):,.0f} / ${d.get('usd',0):,.0f} ({arrow}{abs(ch):.1f}%)\n"
        return result
    except Exception as e: return f"Crypto error: {e}"

def agent_public_ip():
    try:
        d = req.get("https://ipinfo.io/json", timeout=10).json()
        return f"IP: {d.get('ip')} | {d.get('city')}, {d.get('region')}, {d.get('country')} | {d.get('org')}"
    except Exception as e: return f"IP error: {e}"

def agent_wikipedia(query):
    try:
        r = req.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ','_')}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            return f"{d.get('title','')}\n{d.get('extract','No content.')[:500]}"
        s = req.get(f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&format=json", timeout=10).json()
        if len(s)>1 and s[1]: return "Results: " + ", ".join(s[1][:5])
        return f"Nothing found: {query}"
    except Exception as e: return f"Wikipedia error: {e}"

def agent_exchange_rates(base="EUR"):
    try:
        d = req.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10).json()
        if d.get("result")=="success":
            rates = d["rates"]
            important = ["USD","GBP","JPY","CHF","CAD","AUD","SEK","NOK","DKK","PLN","TRY"]
            result = f"1 {base} =\n"
            for cur in important:
                if cur in rates: result += f"  {cur}: {rates[cur]:.4f}\n"
            return result
        return "Exchange rate API error"
    except Exception as e: return f"Exchange error: {e}"

def agent_news_headlines():
    try:
        import feedparser
        headlines = []
        for name,url in [("BBC","http://feeds.bbci.co.uk/news/rss.xml"),("Reuters","https://feeds.reuters.com/reuters/worldNews")]:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]: headlines.append(f"[{name}] {entry.get('title','?')}")
            except: pass
        return "Headlines:\n" + "\n".join("  "+h for h in headlines[:10]) if headlines else "No headlines available"
    except Exception as e: return f"News error: {e}"

AGENT_TOOLS = {
    "search_kb":         lambda args: agent_search_kb(args.get("query","")),
    "search_web":        lambda args: agent_read_url(f"https://news.google.com/search?q={args.get('query','').replace(' '+'+')}"),
    "run_command":       lambda args: agent_run_command(args.get("machine","pi"),args.get("command","")),
    "network_scan":      lambda args: agent_network_scan(),
    "system_status":     lambda args: agent_system_status(),
    "read_url":          lambda args: agent_read_url(args.get("url","")),
    "save_note":         lambda args: agent_save_note(args.get("title","Untitled"),args.get("content","")),
    "weather":           lambda args: agent_weather(args.get("city","Amsterdam")),
    "dutch_temperatures":lambda args: agent_dutch_temperatures(),
    "crypto":            lambda args: agent_crypto_prices(),
    "public_ip":         lambda args: agent_public_ip(),
    "wikipedia":         lambda args: agent_wikipedia(args.get("query","")),
    "exchange_rates":    lambda args: agent_exchange_rates(args.get("base","EUR")),
    "news_headlines":    lambda args: agent_news_headlines(),
}

def is_canvas_edit_intent(question, canvas):
    if not canvas or not canvas.strip():
        return False
    return bool(CANVAS_EDIT_PATTERNS.search(question))

def guess_filename(canvas_content, hint=""):
    c = (hint + canvas_content).lower()
    if "def " in c or "import " in c or c.strip().startswith("#!"): return "script.py"
    if "function" in c or "const " in c or "let " in c or "=>" in c: return "script.js"
    if "<!doctype" in c or "<html" in c: return "index.html"
    if "#!/bin/bash" in c or "#!/bin/sh" in c: return "script.sh"
    return "document.md"

@app.route("/agent", methods=["POST"])
def agent():
    question = request.json.get("question","")
    history = request.json.get("history",[])
    canvas = request.json.get("canvas_content", None)
    if not question:
        return Response(sse("error",message="No question"), content_type="text/event-stream")

    def gen():
        if is_canvas_edit_intent(question, canvas):
            for ev in canvas_edit_gen(question, canvas): yield ev
            return

        sys_content = AGENT_SYSTEM
        if canvas:
            sys_content += (
                f"\n\nCanvas context (user's open document):\n```\n{canvas[:3000]}\n```"
            )

        msgs = [{"role":"system","content":sys_content}]
        for m in history[-MAX_HISTORY:]: msgs.append({"role":m["role"],"content":m["content"][:500]})
        msgs.append({"role":"user","content":question})

        for iteration in range(6):
            yield sse("search_status", message=f"Agent thinking... (step {iteration+1})")
            try:
                r = req.post(LLAMA_URL+"/v1/chat/completions", json={
                    "messages": msgs,
                    "max_tokens": 700,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking":False}
                }, timeout=60)
                response_text = r.json().get("choices",[{}])[0].get("message",{}).get("content","").strip()
            except Exception as e:
                yield sse("error", message=f"LLM error: {e}"); return

            tool_match = re.search(r'\{\s*"tool"\s*:', response_text)

            if tool_match:
                try:
                    json_start = response_text.index('{', tool_match.start())
                    brace_count = 0; json_end = json_start
                    for ci, ch in enumerate(response_text[json_start:]):
                        if ch=='{': brace_count+=1
                        elif ch=='}': brace_count-=1
                        if brace_count==0: json_end=json_start+ci+1; break

                    tool_json = json.loads(response_text[json_start:json_end])
                    tool_name = tool_json.get("tool","")
                    tool_args = tool_json.get("args",{})

                    before = response_text[:json_start].strip()
                    if before: yield sse("token", token=before+"\n\n")

                    if tool_name in AGENT_TOOLS:
                        yield sse("search_status", message=f"Running {tool_name}...")
                        tool_result = AGENT_TOOLS[tool_name](tool_args)
                        if len(tool_result) > 600 and tool_name in ("network_scan","system_status","search_kb","news_headlines"):
                            fn_map = {"network_scan":"network_scan.md","system_status":"system_status.md","search_kb":"search_results.md","news_headlines":"headlines.md"}
                            yield sse("canvas_content", content=tool_result, filename=fn_map.get(tool_name,"output.md"))
                            yield sse("token", token=f"*Results written to canvas.*\n\n")
                            tool_result = f"(written to canvas, {len(tool_result)} chars)"
                    else:
                        tool_result = f"Unknown tool: {tool_name}"

                    msgs.append({"role":"assistant","content":response_text})
                    msgs.append({"role":"user","content":f"Tool result for {tool_name}:\n{tool_result}"})

                except (json.JSONDecodeError, ValueError):
                    for token in response_text.split(): yield sse("token", token=token+" ")
                    yield sse("done"); return
            else:
                for token in response_text.split():
                    yield sse("token", token=token+" ")
                yield sse("done"); return

        yield sse("token", token="\n\n*Max iterations reached.*")
        yield sse("done")

    return Response(gen(), content_type="text/event-stream", headers=HDRS)

if __name__ == "__main__":
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
Public
