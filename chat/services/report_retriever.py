"""
services/report_retriever.py
-----------------------------
RAG retriever for historical, LLM-generated station reports.

Reports are free-text narrative (executive summary, stock status, alert
analysis, forecast/recommendations) — unlike alerts, they don't fit a small
fixed taxonomy, so semantic search genuinely adds value here: an operator can
ask "what did past reports say about SansPlomb consumption spikes?" and get
relevant history back even if the exact wording differs.

Indexing strategy: rather than a separate background sync job, the
search_past_reports tool (see agent_tools.py) re-fetches reports from the
backend and upserts them into the index on every call, right before
querying. This keeps the index self-healing and always fresh with no extra
process to keep running, at the cost of a small amount of repeated work per
search — an acceptable trade-off given expected report volumes.
"""

from __future__ import annotations
import logging

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "reports_rag"


def _report_to_doc(report: dict) -> str:
    # Full report content is the document itself — it's already well-structured
    # Markdown written by the LLM, so no reformatting is needed for embedding.
    return report.get("content", "") or ""


class ReportRetriever:
    def __init__(self, persist_dir: str = "./chroma_reports_db"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=DefaultEmbeddingFunction(),
        )

    def index_reports(self, reports: list[dict]) -> int:
        """Upsert reports into the vector index. Returns number of docs indexed."""
        if not reports:
            return 0
        docs, ids, metas = [], [], []
        for report in reports:
            doc = _report_to_doc(report)
            if not doc.strip():
                continue
            uid = str(report.get("id"))
            docs.append(doc)
            ids.append(uid)
            metas.append({
                "station_id": str(report.get("station_id", "")),
                "timestamp": str(report.get("timestamp", "")),
            })
        if not docs:
            return 0
        self._collection.upsert(documents=docs, ids=ids, metadatas=metas)
        logger.info("RAG: upserted %d reports (index total=%d)", len(docs), self.count())
        return len(docs)

    def retrieve(self, query: str, station_id: str | None = None, k: int = 3) -> str:
        """
        Return a formatted context string of the k most relevant past reports.
        Falls back to unfiltered search if station-specific query fails.
        Returns empty string if the index is empty or retrieval fails.
        """
        total = self.count()
        if total == 0:
            return ""
        n = min(k, total)
        where = {"station_id": station_id} if station_id else None
        try:
            results = self._collection.query(query_texts=[query], n_results=n, where=where)
        except Exception:
            if not where:
                return ""
            # Station filter may fail if no docs exist for that station yet
            try:
                results = self._collection.query(query_texts=[query], n_results=n)
            except Exception as exc:
                logger.warning("RAG retrieval failed: %s", exc)
                return ""

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        if not docs:
            return ""

        lines = []
        for doc, meta in zip(docs, metas):
            ts = str(meta.get("timestamp", ""))[:16]
            sid = meta.get("station_id", "")
            lines.append(f"--- Report for {sid} at {ts} ---\n{doc}")
        return "\n\n".join(lines)

    def count(self) -> int:
        return self._collection.count()


# Module-level singleton shared by agent_tools
report_retriever = ReportRetriever()