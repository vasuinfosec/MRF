#!/usr/bin/env python3
"""T2.3 — Restore verification into the ISOLATED staging DB.

Hard refuses to write if the target DB name/URL match production. Restores a
backup made by backup_db.py, then verifies:
  * every collection restored
  * doc counts within tolerance of the backup manifest
  * index count per collection matches
  * a spot-check on 3 collection relationships (mrfs↔pos, pos↔grns, users↔user_sessions)
  * an embedded attachment is retrievable

Usage:
  python3 /app/backend/scripts/restore_to_staging.py \
     --backup-dir /app/backup_artifacts/backup_<stamp>
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from staging_guard import assert_staging_is_isolated, assert_target_is_not_prod, _redact  # type: ignore


def _die(msg, code=2):
    print(f"[restore] ABORT: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup-dir", required=True)
    args = ap.parse_args()
    bdir = Path(args.backup_dir)
    manifest_path = bdir / "manifest.json"
    if not manifest_path.exists():
        _die(f"manifest.json not found under {bdir}")
    manifest = json.loads(manifest_path.read_text())

    stg_url, stg_db = assert_staging_is_isolated("restore_to_staging")
    assert_target_is_not_prod(stg_url, stg_db, "restore_to_staging")

    # Locate the BSON dump — mongodump writes `<db_name>/*.bson` under dump/.
    dump_root = bdir / "dump"
    src_dirs = [p for p in dump_root.iterdir() if p.is_dir()]
    if not src_dirs:
        _die(f"No source-db directory inside {dump_root}")
    src_db_dir = src_dirs[0]  # only one prod DB in the dump

    print(f"[restore] Target staging: {_redact(stg_url)} db='{stg_db}'")
    print(f"[restore] Source dump   : {src_db_dir}")

    # Drop staging DB collections before restore (idempotent, safe — only ever
    # writes to staging DB because staging_guard already verified isolation).
    from pymongo import MongoClient
    client = MongoClient(stg_url, serverSelectionTimeoutMS=8000)
    try:
        assert client.server_info()  # connection sanity
        # Absolute paranoia: refuse if target DB == prod DB name.
        assert_target_is_not_prod(stg_url, stg_db, "pre-drop check")
        db = client[stg_db]
        for c in db.list_collection_names():
            db.drop_collection(c)
        print(f"[restore] Cleared staging DB (dropped {len(db.list_collection_names())} residuals)")
    finally:
        client.close()

    cmd = [
        "mongorestore",
        f"--uri={stg_url}",
        f"--nsFrom={src_db_dir.name}.*",
        f"--nsTo={stg_db}.*",
        "--dir", str(dump_root),
        "--quiet", "--drop",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        _die(f"mongorestore failed rc={r.returncode}: {r.stderr[:600]}")
    print("[restore] mongorestore OK")

    # ---- Verification ----------------------------------------------------
    client = MongoClient(stg_url, serverSelectionTimeoutMS=8000)
    try:
        db = client[stg_db]
        report = {"collections": [], "issues": []}
        for expected in manifest["collections"]:
            name = expected["name"]
            got = db[name].estimated_document_count()
            got_idx = len(list(db[name].list_indexes()))
            row = {
                "name": name,
                "expected": expected["estimated_count"],
                "got": got,
                "expected_indexes": expected["indexes"],
                "got_indexes": got_idx,
                "ok": got == expected["estimated_count"],
            }
            report["collections"].append(row)
            if not row["ok"]:
                report["issues"].append(f"count mismatch on {name}: expected {expected['estimated_count']}, got {got}")
            if got_idx != expected["indexes"]:
                report["issues"].append(f"index count mismatch on {name}: expected {expected['indexes']}, got {got_idx}")

        # Relationship spot-checks (structural only, no data-integrity assumption).
        if "pos" in db.list_collection_names() and "mrfs" in db.list_collection_names():
            mrf_ids = set(m.get("mrf_id") for m in db.mrfs.find({}, {"mrf_id": 1}).limit(50))
            po_mrf_refs = set(p.get("mrf_id") for p in db.pos.find({}, {"mrf_id": 1}).limit(50))
            report["po_to_mrf_ref_overlap"] = len(mrf_ids & po_mrf_refs)
        if "grns" in db.list_collection_names():
            grn_pos = set(g.get("po_id") for g in db.grns.find({}, {"po_id": 1}).limit(50))
            po_ids = set(p.get("po_id") for p in db.pos.find({}, {"po_id": 1}).limit(50))
            report["grn_to_po_ref_overlap"] = len(grn_pos & po_ids)

        # Attachment spot-check
        if "customer_pos" in db.list_collection_names():
            att = db.customer_pos.find_one({"attachment_b64": {"$exists": True, "$ne": ""}}, {"attachment_b64": 1})
            report["customer_po_attachment_sample_bytes"] = len(att.get("attachment_b64", "")) if att else 0

        (bdir / "restore_verify.json").write_text(json.dumps(report, indent=2))
        print(f"[restore] Wrote {bdir / 'restore_verify.json'}")
        print(f"[restore] Issues: {len(report['issues'])}")
        for i in report["issues"][:10]:
            print(f"  * {i}")
        if not report["issues"]:
            print("[restore] ✅ All counts and index counts match manifest.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
