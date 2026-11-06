#!/usr/bin/env python3
"""Rebuild the Qdrant collection from the database (Phase 4).

Use after a payload-shape change, or when Qdrant has drifted from the
DB (upsert failures are logged, not fatal, so drift is possible).
Deletes and recreates the collection, then upserts every stored frame
with its owner id, caption provider, and detection labels.

Usage:
    cd backend && python ../scripts/reindex_qdrant.py
Requires QDRANT_URL set (e.g. http://localhost:6333).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.services.retrieval import reindex_qdrant  # noqa: E402

if __name__ == "__main__":
    if not os.environ.get("QDRANT_URL"):
        print("QDRANT_URL is not set — nothing to reindex.")
        sys.exit(1)
    db = SessionLocal()
    try:
        result = reindex_qdrant(db)
        print(f"Reindexed Qdrant: {result['upserted']} points upserted, "
              f"{result['skipped']} skipped (no video).")
    finally:
        db.close()
