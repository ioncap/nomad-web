import os
from dotenv import load_dotenv

load_dotenv()

NOMAD_HOST   = os.getenv("NOMAD_HOST", "nomad.home")
EMBED_URL    = os.getenv("EMBED_URL", "http://192.168.2.20:11434")
OLLAMA_URL   = f"http://{NOMAD_HOST}:11434"
HELPER_URL   = os.getenv("HELPER_URL", "http://192.168.2.20:11434")
HELPER_MODEL = os.getenv("HELPER_MODEL", "qwen2.5:1.5b")
LLAMA_URL    = f"http://{NOMAD_HOST}:8081"
QDRANT_HOST  = os.getenv("QDRANT_HOST", "nomad.home")
QDRANT_PORT  = int(os.getenv("QDRANT_PORT", "6333"))
WHISPER_URL  = f"http://{NOMAD_HOST}:8082"
STATS_URL    = f"http://{NOMAD_HOST}:8083"
DOZZLE_URL   = f"http://{NOMAD_HOST}:9999"
GRAFANA_URL  = os.getenv("GRAFANA_URL", "http://192.168.2.20:3000")
PIPER_MODEL  = os.getenv("PIPER_MODEL", os.path.expanduser("~/piper-voices/en_US-lessac-medium.onnx"))
PIPER_BIN    = os.getenv("PIPER_BIN", os.path.expanduser("~/tinybert-env/bin/piper"))
VOICE_URL    = os.getenv("VOICE_URL", "http://192.168.2.20:8085")
XPS13_HOST   = os.getenv("XPS13_HOST", "192.168.2.20")
XPS13_STATS_URL = f"http://{XPS13_HOST}:8083"
COLLECTION      = os.getenv("COLLECTION", "nomad_knowledge_base")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.15"))
MAX_RESULTS     = int(os.getenv("MAX_RESULTS", "6"))
MAX_CHUNK_LEN   = int(os.getenv("MAX_CHUNK_LEN", "500"))
MAX_HISTORY     = int(os.getenv("MAX_HISTORY", "20"))
