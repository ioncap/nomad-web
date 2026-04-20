"""
Autonomous background agent that periodically scans the Qdrant knowledge base,
evaluates each document for technical relevance, and removes irrelevant ones.
"""
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from config import COLLECTION
from modules.llm import helper_llm

logger = logging.getLogger(__name__)

_RELEVANCE_PROMPT = """\
Evaluate if this document belongs in a technical knowledge base.

RELEVANT if about:
- Programming, algorithms, data structures, design patterns, debugging, testing, CI/CD, software architecture
- Programming languages, frameworks, libraries (Python, JS, React, Django, etc.)
- Sysadmin, networking, containers (Docker/K8s), databases, cloud, security, hardware, embedded, home automation
- Math/physics for engineers, productivity tools, technical writing, project management (Agile/Scrum)

IRRELEVANT if purely about:
- Entertainment, gossip, celebrities, sports results (unless data-analysis context)
- Recipes, fashion, interior design (unless IoT/programming context)
- Political opinions, religious texts, philosophy without a technical angle

Document:
{text}

Reply with exactly one word: RELEVANT or IRRELEVANT."""

# Documents shorter than this (title + content combined) are skipped as likely noise.
_MIN_TEXT_LENGTH = 100


class KBCleaner:
    def __init__(
        self,
        client: QdrantClient,
        dry_run: bool = True,
        interval_hours: int = 24,
    ):
        self.client = client
        self.dry_run = dry_run
        self.interval = interval_hours * 3600
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_stats: Dict[str, Any] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(
            "KB Cleaner started (dry_run=%s, interval=%dh)",
            self.dry_run,
            self.interval // 3600,
        )

    def stop(self) -> None:
        self.running = False

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while self.running:
            try:
                self.clean()
            except Exception as exc:
                logger.error("KB Cleaner run failed: %s", exc, exc_info=True)
            time.sleep(self.interval)

    # ── Main clean pass ───────────────────────────────────────────────────────

    def clean(self) -> Dict[str, Any]:
        """Scan all documents, evaluate relevance, delete/log irrelevant ones.

        Returns a stats dict with counts for monitoring/manual triggers.
        """
        logger.info("KB Cleaner: starting scan of collection '%s'...", COLLECTION)
        points = self._scroll_all()
        total = len(points)

        protected = skipped = evaluated = 0
        irrelevant_ids: List = []

        for point in points:
            if self._is_protected(point):
                protected += 1
                continue

            payload = point.payload or {}
            title = payload.get("article_title") or payload.get("question") or ""
            content = payload.get("content") or payload.get("answer") or ""
            combined = title + content

            if len(combined) < _MIN_TEXT_LENGTH:
                skipped += 1
                continue

            evaluated += 1
            if not self._is_relevant(title, content):
                irrelevant_ids.append(point.id)

        relevant = evaluated - len(irrelevant_ids)
        stats = {
            "total": total,
            "evaluated": evaluated,
            "relevant": relevant,
            "irrelevant": len(irrelevant_ids),
            "protected": protected,
            "skipped": skipped,
            "dry_run": self.dry_run,
        }
        self.last_stats = stats

        logger.info(
            "KB Cleaner: total=%d evaluated=%d relevant=%d irrelevant=%d "
            "protected=%d skipped=%d",
            total, evaluated, relevant, len(irrelevant_ids), protected, skipped,
        )

        if irrelevant_ids:
            if self.dry_run:
                logger.info(
                    "KB Cleaner DRY RUN — would delete %d doc(s): %s",
                    len(irrelevant_ids),
                    irrelevant_ids,
                )
            else:
                self._delete_batch(irrelevant_ids)
                logger.info("KB Cleaner: deleted %d document(s).", len(irrelevant_ids))
        else:
            logger.info("KB Cleaner: nothing to delete.")

        return stats

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _scroll_all(self) -> list:
        """Retrieve every point from the collection via cursor-based pagination."""
        points = []
        offset = None
        while True:
            batch, next_offset = self.client.scroll(
                collection_name=COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points.extend(batch)
            if next_offset is None:
                break
            offset = next_offset
        return points

    def _is_protected(self, point) -> bool:
        """Return True for documents that must never be auto-deleted."""
        payload = point.payload or {}
        # Manually validated entries are sacred.
        if payload.get("validated") is True:
            return True
        # User-uploaded sources are always kept.
        if payload.get("source") == "user_upload":
            return True
        return False

    def _is_relevant(self, title: str, content: str) -> bool:
        """Ask the helper LLM whether this document is technically relevant."""
        text = f"Title: {title}\nContent: {content[:1000]}"
        response = helper_llm(
            messages=[
                {
                    "role": "system",
                    "content": "You are a content classifier for a technical knowledge base.",
                },
                {
                    "role": "user",
                    "content": _RELEVANCE_PROMPT.format(text=text),
                },
            ],
            max_tokens=10,
        )
        return response.strip().upper().startswith("RELEVANT")

    def _delete_batch(self, ids: List) -> None:
        self.client.delete(
            collection_name=COLLECTION,
            points_selector=qdrant_models.PointIdsList(points=ids),
        )


# ── Module-level singleton so agent tools can reach the running cleaner ───────

_instance: Optional["KBCleaner"] = None


def set_instance(cleaner: "KBCleaner") -> None:
    global _instance
    _instance = cleaner


def get_instance() -> Optional["KBCleaner"]:
    return _instance
