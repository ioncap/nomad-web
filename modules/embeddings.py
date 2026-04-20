import functools
import requests as req
from config import EMBED_URL


@functools.lru_cache(maxsize=128)
def get_embedding(text: str):
    r = req.post(
        f"{EMBED_URL}/api/embed",
        json={"model": "nomic-embed-text:v1.5", "input": text},
        timeout=30,
    )
    return r.json()["embeddings"][0]
