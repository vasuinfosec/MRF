#!/usr/bin/env python3
"""T2.1 — Backup capability.

Creates a reusable, verifiable, off-tree MongoDB backup of the CURRENT production
database. Read-only against prod. Does not upload to any external destination.

Outputs to /app/backup_artifacts/backup_<UTCstamp>/ containing:
  * dump/                       — BSON files (one directory per collection)
  * manifest.json               — timestamp, prod_db name hash, collection counts,
                                  index counts, sizes, embedded-attachment sizes
  * checksums.sha256            — SHA-256 of every dump file
  * backup_<UTCstamp>.tar.gz    — single-file tarball for secure export
  * backup_<UTCstamp>.tar.gz.sha256 — top-level checksum of the tarball

Usage:
  python3 /app/backend/scripts/backup_db.py
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Load .env so this script works when invoked directly.
try:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
except Exception:
    pass

ARTIFACT_ROOT = Path("/app/backup_artifacts")


def _die(msg: str, code: int = 2):
    print(f"[backup] ABORT: {msg}", file=sys.stderr)
    sys.exit(code)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collection_counts_and_sizes(mongo_url: str, db_name: str) -> dict:
    """Ask Mongo for per-collection stats. Read-only."""
    from pymongo import MongoClient
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=8000)
    try:
        db = client[db_name]
        colls = sorted(db.list_collection_names())
        rows = []
        for c in colls:
            n = db[c].estimated_document_count()
            # Attachment/base64 size (heuristic) — sum length of any large string field.
            att_bytes = 0
            try:
                for doc in db[c].find({}, projection=None).limit(500):
                    for v in doc.values():
                        if isinstance(v, str) and len(v) > 5000:
                            att_bytes += len(v)
            except Exception:
                pass
            idx_count = len(list(db[c].list_indexes()))
            rows.append({
                "name": c,
                "estimated_count": int(n),
                "indexes": idx_count,
                "attachment_bytes_sampled": int(att_bytes),
            })
        return {"collections": rows}
    finally:
        client.close()


def main():
    mongo_url = (os.environ.get("MONGO_URL") or "").strip()
    db_name = (os.environ.get("DB_NAME") or "").strip()
    if not mongo_url or not db_name:
        _die("MONGO_URL or DB_NAME not set in environment.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACT_ROOT / f"backup_{stamp}"
    dump_dir = out_dir / "dump"
    dump_dir.mkdir(parents=True, exist_ok=False)

    print(f"[backup] Starting UTC={stamp}")
    print(f"[backup] Target: prod (read-only). Output: {out_dir}")

    # 1. Gather counts BEFORE dump so we can compare after restore.
    print("[backup] Snapshotting collection stats (read-only)…")
    stats = _collection_counts_and_sizes(mongo_url, db_name)

    # 2. mongodump (BSON) — read-only against prod.
    print("[backup] Running mongodump…")
    cmd = [
        "mongodump",
        f"--uri={mongo_url}",
        f"--db={db_name}",
        f"--out={dump_dir}",
        "--quiet",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        _die("mongodump timed out after 600s.")
    if r.returncode != 0:
        _die(f"mongodump failed rc={r.returncode}: {r.stderr[:400]}")

    # 3. SHA-256 every file in the dump.
    print("[backup] Computing SHA-256 of dump files…")
    checksums = {}
    total_bytes = 0
    for p in dump_dir.rglob("*"):
        if p.is_file():
            checksums[str(p.relative_to(dump_dir))] = _sha256(p)
            total_bytes += p.stat().st_size
    (out_dir / "checksums.sha256").write_text(
        "\n".join(f"{v}  {k}" for k, v in sorted(checksums.items())) + "\n"
    )

    # 4. Manifest.
    manifest = {
        "vasu_mrf_backup_version": "1.0.0",
        "created_utc": stamp,
        "tool": "mongodump",
        "source": {
            "prod_db_name_sha256": hashlib.sha256(db_name.encode()).hexdigest()[:16],
            "prod_db_name_length": len(db_name),
            "mongo_host": urlparse(mongo_url).hostname,
        },
        "totals": {
            "collections": len(stats["collections"]),
            "estimated_documents": sum(c["estimated_count"] for c in stats["collections"]),
            "indexes": sum(c["indexes"] for c in stats["collections"]),
            "attachment_bytes_sampled": sum(c["attachment_bytes_sampled"] for c in stats["collections"]),
            "dump_bytes": total_bytes,
            "files": len(checksums),
        },
        "collections": stats["collections"],
        "safeguards": {
            "prod_write_operations": 0,
            "external_uploads": 0,
            "secrets_in_manifest": False,
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # 5. Tarball for secure export.
    tarball = out_dir.parent / f"backup_{stamp}.tar.gz"
    print(f"[backup] Creating tarball {tarball.name}…")
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(out_dir, arcname=out_dir.name)
    tar_sha = _sha256(tarball)
    (tarball.parent / f"{tarball.name}.sha256").write_text(f"{tar_sha}  {tarball.name}\n")

    print()
    print("[backup] ✅ Complete.")
    print(f"  dir       : {out_dir}")
    print(f"  tarball   : {tarball}")
    print(f"  tar sha256: {tar_sha}")
    print(f"  colls     : {manifest['totals']['collections']}")
    print(f"  docs      : {manifest['totals']['estimated_documents']}")
    print(f"  dump size : {manifest['totals']['dump_bytes']} bytes")


if __name__ == "__main__":
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    main()
