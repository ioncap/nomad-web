import hashlib
import time

from qdrant_client import QdrantClient, models
from config import QDRANT_HOST, QDRANT_PORT, COLLECTION
from modules.embeddings import get_embedding
from modules.llm import helper_llm


def validate_and_index(question, answer):
    try:
        chunk = "Question: " + question + "\nAnswer: " + answer
        emb   = get_embedding(chunk)
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        try:
            ex = client.query_points(collection_name=COLLECTION, query=emb, limit=1)
            if ex.points and ex.points[0].score > 0.85:
                return False, "Duplicate (score:" + str(round(ex.points[0].score, 2)) + ")"
        except Exception:
            pass

        vt = helper_llm(
            [
                {"role": "system", "content": "Is this answer factual and useful? Reply ONLY YES or NO."},
                {"role": "user",   "content": "Q:" + question + "\nA:" + answer},
            ],
            max_tokens=10,
        ).upper()
        if not vt.startswith("YES"):
            return False, "Quality: " + vt

        pid = abs(int(hashlib.md5(chunk.encode()).hexdigest(), 16)) % (2 ** 63)
        client.upsert(
            collection_name=COLLECTION,
            points=[
                models.PointStruct(
                    id=pid,
                    vector=emb,
                    payload={
                        "source":        "llm_generated",
                        "content_type":  "llm_generated",
                        "article_title": "Q: " + question[:80],
                        "content":       chunk,
                        "generated_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
                        "validated":     True,
                    },
                )
            ],
        )
        return True, "Saved"
    except Exception as e:
        return False, str(e)
