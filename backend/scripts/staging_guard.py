"""Safety helpers to guarantee staging code never targets the production DB.

Used by:
  * backup_db.py       — read-only from prod, so guard is advisory.
  * restore_to_staging.py — refuses to write if target DB == prod DB.
  * regression_baseline.py — refuses to run if API points at prod DB.

Exit code 2 on any guard failure. Never raises silently.
"""
from __future__ import annotations
import os
import sys
from urllib.parse import urlparse
from typing import Tuple


def _redact(url: str) -> str:
    """Return a redacted mongo URL safe to print — hides credentials & host tail."""
    if not url:
        return "(unset)"
    try:
        p = urlparse(url)
        host = p.hostname or "?"
        scheme = p.scheme or "?"
        return f"{scheme}://***:***@{host[:4]}...:{p.port or '?'}"
    except Exception:
        return "(unparseable)"


def load_prod_and_staging() -> Tuple[str, str, str, str]:
    prod_url = (os.environ.get("MONGO_URL") or "").strip()
    prod_db = (os.environ.get("DB_NAME") or "").strip()
    stg_url = (os.environ.get("STAGING_MONGO_URL") or "").strip()
    stg_db = (os.environ.get("STAGING_DB_NAME") or "").strip()
    return prod_url, prod_db, stg_url, stg_db


def assert_staging_is_isolated(context: str) -> Tuple[str, str]:
    """Refuse to proceed unless STAGING_* variables are set AND different from prod.

    Returns (staging_url, staging_db) on success. Exits(2) on failure.
    """
    prod_url, prod_db, stg_url, stg_db = load_prod_and_staging()
    problems = []
    if not stg_url:
        problems.append("STAGING_MONGO_URL is unset.")
    if not stg_db:
        problems.append("STAGING_DB_NAME is unset.")
    if stg_db and prod_db and stg_db == prod_db:
        problems.append(
            f"STAGING_DB_NAME must be DIFFERENT from DB_NAME. "
            f"Both currently resolve to the same name."
        )
    if stg_url and prod_url and stg_url == prod_url and (not stg_db or stg_db == prod_db):
        problems.append(
            "Staging URL identical to production and DB names not clearly separated."
        )
    # Extra paranoia: staging DB name must contain 'stag' or 'test' or 'scratch'.
    if stg_db and not any(k in stg_db.lower() for k in ("stag", "test", "scratch", "_qa", "_staging")):
        problems.append(
            f"STAGING_DB_NAME='{stg_db}' does not contain a recognisable staging marker "
            "('stag'/'test'/'scratch'/'_qa'). Refusing to write to avoid accidental prod hit."
        )
    if problems:
        print(f"[staging-guard] ABORT ({context}):", file=sys.stderr)
        for p in problems:
            print(f"  * {p}", file=sys.stderr)
        print(f"  prod_url={_redact(prod_url)}  prod_db_len={len(prod_db)}", file=sys.stderr)
        print(f"  stg_url={_redact(stg_url)}   stg_db='{stg_db}'", file=sys.stderr)
        sys.exit(2)
    return stg_url, stg_db


def assert_target_is_not_prod(target_url: str, target_db: str, context: str) -> None:
    """Called just before ANY write. Aborts if target matches prod."""
    prod_url, prod_db, _, _ = load_prod_and_staging()
    if prod_db and target_db and prod_db == target_db:
        print(
            f"[staging-guard] REFUSED ({context}): target DB name equals production. "
            "Aborting to protect prod data.",
            file=sys.stderr,
        )
        sys.exit(2)
    if prod_url and target_url and prod_url == target_url and prod_db == target_db:
        print(
            f"[staging-guard] REFUSED ({context}): full URL+DB matches production.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    # Diagnostic: print isolation status without leaking secrets.
    prod_url, prod_db, stg_url, stg_db = load_prod_and_staging()
    print("prod_url:", _redact(prod_url))
    print("prod_db :", f"len={len(prod_db)} (name hidden)")
    print("stg_url :", _redact(stg_url))
    print("stg_db  :", stg_db or "(unset)")
    print("isolated:", bool(stg_db and stg_db != prod_db))
