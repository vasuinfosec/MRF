"""Task 3A.1 — Protected Existing-User Access Review Report Generator.

READ-ONLY. Executes against the STAGING MongoDB only (port 27018 by default).

Emits two artifacts in /app/backup_artifacts/:
  * access_review_<timestamp>.json      — full evidence for audit
  * access_review_<timestamp>.md        — Director-friendly summary

Both artifacts MASK session tokens, download tokens, and any secret-like values
before writing to disk. No user or role state is modified.

Usage:
    STAGING_MONGO_URL='...' STAGING_DB_NAME='vasu_mrf_staging_qa' \
        python /app/backend/scripts/access_review_report.py

If STAGING_MONGO_URL is not set, the script FAILS FAST — production DB
(:27017) MUST NEVER be touched by this report.
"""
from __future__ import annotations
import os
import re
import sys
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

ARTIFACT_DIR = Path("/app/backup_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _mask(v):
    if not isinstance(v, str):
        return v
    if len(v) <= 8:
        return "***"
    return f"{v[:4]}…{v[-2:]}"


SECRET_KEYS = re.compile(
    r"(token|password|secret|api[_-]?key|session)", re.IGNORECASE
)


def _redact(doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        if SECRET_KEYS.search(k):
            out[k] = _mask(str(v)) if v is not None else None
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def _to_json(v):
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


async def _run(mongo_url: str, db_name: str) -> dict:
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[db_name]

    users = await db.users.find({}, {"_id": 0}).to_list(5000)
    invitations = await db.invitations.find({}, {"_id": 0}).to_list(1000)
    pending_reqs = await db.pending_access_requests.find(
        {}, {"_id": 0}).to_list(1000)
    sessions_count = await db.user_sessions.count_documents({})

    # Classify
    now = datetime.now(timezone.utc)
    total_users = len(users)
    active_users = [u for u in users if u.get("is_active", False)]
    inactive_users = [u for u in users if not u.get("is_active", False)]
    directors = [
        u for u in active_users
        if u.get("role") == "director" or "director" in (u.get("roles") or [])
    ]
    admins = [
        u for u in active_users
        if u.get("role") == "admin" or "admin" in (u.get("roles") or [])
    ]
    single_role_users = [
        u for u in users if not u.get("roles") and u.get("role")
    ]
    users_with_no_roles = [
        u for u in users
        if not u.get("role") and not (u.get("roles") or [])
    ]
    legacy_roles_used = set()
    for u in users:
        r = u.get("role") or ""
        if r in {"project_manager", "billing"}:
            legacy_roles_used.add(r)

    open_invitations = [
        i for i in invitations
        if not i.get("consumed") and (
            not i.get("expires_at")
            or (i.get("expires_at") and _as_utc(i["expires_at"]) > now)
        )
    ]
    expired_invitations = [
        i for i in invitations
        if not i.get("consumed") and i.get("expires_at")
        and _as_utc(i["expires_at"]) <= now
    ]

    findings = []
    if not directors:
        findings.append({
            "severity": "critical",
            "code": "NO_ACTIVE_DIRECTOR",
            "message": "No active Director in the environment; deactivation guardrail cannot re-enable one.",
        })
    if len(directors) == 1:
        findings.append({
            "severity": "warning",
            "code": "SINGLE_DIRECTOR",
            "message": "Only one active Director. Consider adding a second Director for resiliency.",
        })
    if legacy_roles_used:
        findings.append({
            "severity": "info",
            "code": "LEGACY_ROLE_NAMES_PRESENT",
            "message": f"Legacy role aliases still in DB: {sorted(legacy_roles_used)}. "
                       f"Auto-migrated on read via LEGACY_ROLE_MAP.",
        })
    if users_with_no_roles:
        findings.append({
            "severity": "warning",
            "code": "USERS_WITHOUT_ROLE",
            "message": f"{len(users_with_no_roles)} user(s) have neither `role` nor `roles`. "
                       f"Likely pending-activation records.",
        })
    if expired_invitations:
        findings.append({
            "severity": "info",
            "code": "EXPIRED_INVITATIONS",
            "message": f"{len(expired_invitations)} un-consumed invitation(s) already expired.",
        })

    return {
        "generated_at_utc": now.isoformat(),
        "database": db_name,
        "connection_host": _extract_host(mongo_url),
        "counts": {
            "total_users": total_users,
            "active_users": len(active_users),
            "inactive_users": len(inactive_users),
            "active_directors": len(directors),
            "active_admins": len(admins),
            "users_single_role_only": len(single_role_users),
            "users_no_role_at_all": len(users_with_no_roles),
            "open_invitations": len(open_invitations),
            "expired_open_invitations": len(expired_invitations),
            "consumed_invitations": sum(
                1 for i in invitations if i.get("consumed")),
            "pending_access_requests": len(pending_reqs),
            "live_sessions": sessions_count,
        },
        "findings": findings,
        "users": [_redact(u) for u in users],
        "invitations": [_redact(i) for i in invitations],
        "pending_access_requests": [_redact(p) for p in pending_reqs],
    }


def _as_utc(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return v


def _extract_host(url: str) -> str:
    m = re.search(r"@([^/?]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"//([^/?]+)", url)
    return m.group(1) if m else "unknown"


def _write_markdown(rep: dict, path: Path):
    lines = []
    lines.append("# Access Review Report — Task 3A.1 (Staging)")
    lines.append("")
    lines.append(f"* Generated: `{rep['generated_at_utc']}`")
    lines.append(f"* Database: `{rep['database']}`")
    lines.append(f"* Host:     `{rep['connection_host']}`")
    lines.append("")
    lines.append("## Counts")
    for k, v in rep["counts"].items():
        lines.append(f"* **{k}**: {v}")
    lines.append("")
    lines.append("## Findings")
    if not rep["findings"]:
        lines.append("_No issues detected._")
    else:
        for f in rep["findings"]:
            lines.append(f"* **[{f['severity'].upper()}] {f['code']}** — {f['message']}")
    lines.append("")
    lines.append("## Active Directors (should be ≥ 1)")
    directors = [
        u for u in rep["users"]
        if u.get("is_active")
        and (u.get("role") == "director" or "director" in (u.get("roles") or []))
    ]
    if not directors:
        lines.append("_NONE — CRITICAL._")
    for u in directors:
        lines.append(
            f"* `{u.get('user_id')}` — {u.get('name')} <{u.get('email')}> "
            f"role={u.get('role')} roles={u.get('roles')}"
        )
    lines.append("")
    lines.append("## Users Pending Activation")
    pending = [
        u for u in rep["users"]
        if not u.get("is_active") or not u.get("role")
    ]
    if not pending:
        lines.append("_None._")
    for u in pending:
        lines.append(
            f"* `{u.get('user_id')}` — {u.get('name')} <{u.get('email')}> "
            f"invited_role={u.get('invited_role')}"
        )
    lines.append("")
    lines.append("## Uninvited Access Requests")
    if not rep["pending_access_requests"]:
        lines.append("_None._")
    for p in rep["pending_access_requests"]:
        lines.append(
            f"* `{p.get('request_id')}` — <{p.get('email')}> "
            f"attempts={p.get('attempt_count')} last={p.get('last_attempt_at')}"
        )
    lines.append("")
    lines.append("---")
    lines.append("_Read-only report. No records were modified._")
    path.write_text("\n".join(lines))


async def main():
    mongo_url = os.environ.get("STAGING_MONGO_URL")
    db_name = os.environ.get("STAGING_DB_NAME", "vasu_mrf_staging_qa")
    if not mongo_url:
        print("FATAL: STAGING_MONGO_URL not set. Refusing to touch production DB.",
              file=sys.stderr)
        sys.exit(2)
    if ":27017" in mongo_url:
        print("FATAL: STAGING_MONGO_URL points at :27017 (prod). Aborting.",
              file=sys.stderr)
        sys.exit(2)
    rep = await _run(mongo_url, db_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    j_path = ARTIFACT_DIR / f"access_review_{ts}.json"
    m_path = ARTIFACT_DIR / f"access_review_{ts}.md"
    j_path.write_text(json.dumps(rep, indent=2, default=_to_json))
    _write_markdown(rep, m_path)
    print(f"OK  JSON     -> {j_path}")
    print(f"OK  Markdown -> {m_path}")


if __name__ == "__main__":
    asyncio.run(main())
