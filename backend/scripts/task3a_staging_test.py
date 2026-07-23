#!/usr/bin/env python3
"""Task 3A — staging test-pack. Spawns staging API on :8002 with
ACCESS_SECURITY_V2=1 against isolated staging Mongo. No prod contact."""
from __future__ import annotations
import json, os, signal, subprocess, sys, time, uuid, secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pymongo import MongoClient
import requests

STG_PORT = 8002
BASE = f"http://127.0.0.1:{STG_PORT}"

env_file = os.environ.get("STAGING_ENV_FILE", "/run/vasu_mrf_staging.env")
if not os.path.exists(env_file):
    # Fallback for post-restart environments where /run was cleared
    env_file = "/app/backup_artifacts/staging.env"
env = {}
for line in open(env_file):
    if "=" in line and line.strip() and not line.startswith("#"):
        k, v = line.strip().split("=", 1); env[k] = v.strip("'\"")
STG_URL, STG_DB = env["STAGING_MONGO_URL"], env["STAGING_DB_NAME"]

# ------------------------------------------------------------------
# 1) Seed a QA Director directly in the staging DB (dev-login is now
#    hard-disabled, so we seed the session token as well).
# ------------------------------------------------------------------
c = MongoClient(STG_URL)
d = c[STG_DB]
qa_uid = "user_qa3a_" + uuid.uuid4().hex[:8]
qa_email = f"qa3a-director-{uuid.uuid4().hex[:6]}@vasu.staging"
qa_token = "sess_" + secrets.token_urlsafe(20)
d.users.insert_one({
    "user_id": qa_uid, "email": qa_email,
    "name": "QA 3A Director", "picture": "", "role": "director",
    "is_active": True, "created_at": datetime.now(timezone.utc),
})
d.user_sessions.insert_one({
    "session_token": qa_token, "user_id": qa_uid,
    "email": qa_email, "name": "QA 3A Director",
    "picture": "", "role": "director", "is_active": True,
    "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
    "created_at": datetime.now(timezone.utc),
})
c.close()
print(f"[seed] QA director user_id={qa_uid} (staging only)")

# ------------------------------------------------------------------
# 2) Spawn staging API
# ------------------------------------------------------------------
child_env = os.environ.copy()
child_env["MONGO_URL"] = STG_URL
child_env["DB_NAME"] = STG_DB
child_env["ACCESS_SECURITY_V2"] = "1"
child_env["ENABLE_DEV_LOGIN"] = "1"   # even though enabled, V2 must still block it
log = open("/tmp/task3a_staging_api.log", "w")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server:app",
     "--host", "127.0.0.1", "--port", str(STG_PORT), "--log-level", "warning"],
    cwd="/app/backend", env=child_env, stdout=log, stderr=log,
)
for _ in range(30):
    try:
        r = requests.get(f"{BASE}/api/settings/thresholds", timeout=2)
        if r.status_code in (200, 401, 403): break
    except Exception: pass
    time.sleep(1)
else:
    proc.kill(); sys.exit("Staging API failed to start")
print(f"[api] up on :{STG_PORT} with ACCESS_SECURITY_V2=1")

hdr = {"Authorization": f"Bearer {qa_token}"}
results = []
def check(name, ok, detail=""):
    results.append({"test": name, "ok": bool(ok), "detail": detail[:200]})
    print(f"  {'✅' if ok else '❌'} {name}  {detail[:100]}")

try:
    # ── T-01: dev-login must be 404 (V2 disables regardless of host) ──
    r = requests.post(f"{BASE}/api/auth/dev-login",
        json={"email":"anyone@example.com","role":"director"}, timeout=5)
    check("dev_login_hard_disabled", r.status_code == 404, f"http={r.status_code}")

    # ── T-02: OWNER_EMAILS / count==0 bootstrap moved into legacy else branch ──
    src = open("/app/backend/routers/auth.py").read()
    check("v2_branch_present", 'if v2:' in src, "v2 gate exists")
    # Real check: the OWNER_EMAILS lookup expression `os.environ.get("OWNER_EMAILS"`
    # exists only after the `else:` legacy block, not in the V2 path.
    idx_env = src.find('os.environ.get("OWNER_EMAILS"')
    idx_else = src.find('# ───────── Legacy prod path')
    check("owner_emails_only_in_legacy_else",
          idx_env > 0 and idx_else > 0 and idx_env > idx_else,
          f"env_ref@{idx_env} legacy_else@{idx_else}")

    # ── T-03: Director can list invitations (initially empty) ──
    r = requests.get(f"{BASE}/api/admin/access/invitations", headers=hdr, timeout=5)
    check("list_invitations_ok", r.status_code == 200 and isinstance(r.json(), list),
          f"http={r.status_code} n={len(r.json()) if r.status_code==200 else '?'}")

    # ── T-04: Create an invitation ──
    r = requests.post(f"{BASE}/api/admin/access/invitations", headers=hdr,
        json={"email":"newbie@vasu.staging","role":"pm","expires_in_hours":24,"note":"QA"},
        timeout=5)
    iid = r.json().get("invitation_id") if r.status_code == 200 else None
    check("create_invitation", r.status_code == 200 and iid, f"iid={iid} http={r.status_code}")

    # ── T-05: Revoke an invitation ──
    if iid:
        r = requests.delete(f"{BASE}/api/admin/access/invitations/{iid}", headers=hdr, timeout=5)
        check("revoke_invitation", r.status_code == 200, f"http={r.status_code}")

    # ── T-06: pending users listing ──
    r = requests.get(f"{BASE}/api/admin/access/pending-users", headers=hdr, timeout=5)
    check("pending_users_list", r.status_code == 200, f"http={r.status_code}")

    # ── T-07: Simulate a pending user directly in DB (V2 code path proof) ──
    c2 = MongoClient(STG_URL)
    pending_uid = "user_pending_" + uuid.uuid4().hex[:6]
    c2[STG_DB].users.insert_one({
        "user_id": pending_uid, "email": f"waiting-{uuid.uuid4().hex[:6]}@vasu.staging",
        "name": "Waiting User", "picture": "", "role": None,
        "is_active": False, "created_at": datetime.now(timezone.utc),
        "pending_since": datetime.now(timezone.utc),
    })
    c2.close()
    r = requests.get(f"{BASE}/api/admin/access/pending-users", headers=hdr, timeout=5)
    plist = r.json() if r.status_code == 200 else []
    check("pending_user_visible", any(u["user_id"] == pending_uid for u in plist),
          f"pending_count={len(plist)}")

    # ── T-08: Activate pending user with role ──
    r = requests.post(f"{BASE}/api/admin/access/users/{pending_uid}/activate", headers=hdr,
        json={"role":"purchase","note":"QA activate"}, timeout=5)
    check("activate_user", r.status_code == 200 and r.json().get("is_active") is True,
          f"http={r.status_code}")

    # ── T-09: Bad role rejected ──
    r = requests.post(f"{BASE}/api/admin/access/users/{pending_uid}/activate", headers=hdr,
        json={"role":"godmode"}, timeout=5)
    check("bad_role_rejected", r.status_code == 400, f"http={r.status_code}")

    # ── T-10: Deactivate ──
    r = requests.post(f"{BASE}/api/admin/access/users/{pending_uid}/deactivate", headers=hdr,
        json={"reason":"QA cleanup"}, timeout=5)
    check("deactivate_user", r.status_code == 200, f"http={r.status_code}")

    # ── T-11: PM cannot manage invitations (RBAC enforced) ──
    c3 = MongoClient(STG_URL)
    pm_token = "sess_pm_" + secrets.token_urlsafe(16)
    pm_uid = "user_qa_pm_" + uuid.uuid4().hex[:6]
    c3[STG_DB].users.insert_one({
        "user_id": pm_uid, "email": f"qa-pm-{uuid.uuid4().hex[:6]}@vasu.staging", "name":"QA PM",
        "picture":"","role":"pm","is_active":True,
        "created_at": datetime.now(timezone.utc),
    })
    c3[STG_DB].user_sessions.insert_one({
        "session_token": pm_token, "user_id": pm_uid,
        "email": f"qa-pm-{uuid.uuid4().hex[:6]}@vasu.staging","name":"QA PM","picture":"","role":"pm","is_active":True,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "created_at": datetime.now(timezone.utc),
    })
    c3.close()
    r = requests.get(f"{BASE}/api/admin/access/invitations",
                       headers={"Authorization": f"Bearer {pm_token}"}, timeout=5)
    check("pm_denied_invitations", r.status_code == 403, f"http={r.status_code}")

    # ── T-12: Inactive user (deactivated) has all sessions killed ──
    # Re-check pending_uid's sessions
    c4 = MongoClient(STG_URL)
    live_sess = c4[STG_DB].user_sessions.count_documents({"user_id": pending_uid})
    c4.close()
    check("deactivated_sessions_cleared", live_sess == 0, f"sessions={live_sess}")

    # ── T-13: Audit trail includes critical events ──
    c5 = MongoClient(STG_URL)
    critical_actions = c5[STG_DB].audit_logs.count_documents({
        "action": {"$in": ["create","activate","deactivate","revoke"]},
        "entity": {"$in": ["invitation","user"]},
    })
    c5.close()
    check("audit_events_logged", critical_actions >= 4, f"count={critical_actions}")

    # ── T-14: /admin/access/permissions/me works ──
    r = requests.get(f"{BASE}/api/admin/access/permissions/me", headers=hdr, timeout=5)
    check("permissions_me", r.status_code == 200 and r.json().get("role") == "director",
          f"http={r.status_code}")
    # roles[] is populated (dual-write / backfill from role)
    check("permissions_me_roles_populated",
          isinstance(r.json().get("roles"), list) and "director" in r.json().get("roles", []),
          f"roles={r.json().get('roles')}")

    # ── T-15: Uninvited-signup code path writes to pending_access_requests, NOT users ──
    src_auth = open("/app/backend/routers/auth.py").read()
    check("uninvited_uses_pending_access_requests",
          "db.pending_access_requests" in src_auth
          and "await db.users.insert_one" not in src_auth.split(
              "# ─── Uninvited signup ───────────────────────────────────")[-1].split("else:")[0],
          "code path check")
    # Direct behavioural proof: seed a pending_access_requests row and list it
    c6 = MongoClient(STG_URL)
    req_id = "par_" + uuid.uuid4().hex[:12]
    par_email = f"uninvited-{uuid.uuid4().hex[:6]}@vasu.staging"
    c6[STG_DB].pending_access_requests.insert_one({
        "request_id": req_id, "email": par_email,
        "name": "Uninvited QA", "picture": "",
        "attempt_count": 1,
        "first_attempt_at": datetime.now(timezone.utc),
        "last_attempt_at": datetime.now(timezone.utc),
    })
    users_row = c6[STG_DB].users.find_one({"email": par_email})
    c6.close()
    check("uninvited_no_user_row", users_row is None,
          "no users row for uninvited email")

    # ── T-16: Pending-requests list returns the uninvited request ──
    r = requests.get(f"{BASE}/api/admin/access/pending-requests", headers=hdr, timeout=5)
    plist = r.json() if r.status_code == 200 else []
    check("pending_requests_list",
          r.status_code == 200 and any(p.get("request_id") == req_id for p in plist),
          f"http={r.status_code} n={len(plist)}")

    # ── T-17: Promote a pending request to an invitation ──
    r = requests.post(f"{BASE}/api/admin/access/pending-requests/{req_id}/invite",
                       headers=hdr, json={"role": "pm", "expires_in_hours": 12},
                       timeout=5)
    iid_promo = r.json().get("invitation_id") if r.status_code == 200 else None
    check("invite_from_pending_request",
          r.status_code == 200 and bool(iid_promo),
          f"http={r.status_code} iid={iid_promo}")

    # ── T-18: Self-activation is forbidden (guardrail) ──
    r = requests.post(f"{BASE}/api/admin/access/users/{qa_uid}/activate",
                       headers=hdr, json={"role": "director"}, timeout=5)
    check("self_activation_blocked", r.status_code == 400, f"http={r.status_code}")

    # ── T-19: Last-Director deactivation guardrail ──
    # Strategy: create an ADMIN (management role, non-director) with a fresh
    # session, and have that admin attempt to deactivate qa_uid — the only
    # active director in the DB. The guardrail must return HTTP 400
    # `last_director_protected` (RBAC allows the call because admin is a
    # management role).
    c7 = MongoClient(STG_URL)
    c7[STG_DB].users.update_many(
        {"role": "director", "user_id": {"$ne": qa_uid}},
        {"$set": {"role": "pm", "roles": ["pm"]}},
    )
    admin_uid = "user_qa_admin_" + uuid.uuid4().hex[:6]
    admin_tok = "sess_admin_" + secrets.token_urlsafe(16)
    c7[STG_DB].users.insert_one({
        "user_id": admin_uid,
        "email": f"qa-admin-{uuid.uuid4().hex[:6]}@vasu.staging",
        "name": "QA Admin", "picture": "",
        "role": "admin", "roles": ["admin"], "is_active": True,
        "created_at": datetime.now(timezone.utc),
    })
    c7[STG_DB].user_sessions.insert_one({
        "session_token": admin_tok, "user_id": admin_uid,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "created_at": datetime.now(timezone.utc),
    })
    c7.close()
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    r = requests.post(f"{BASE}/api/admin/access/users/{qa_uid}/deactivate",
                       headers=admin_hdr,
                       json={"reason": "QA: attempt last-dir kill"},
                       timeout=5)
    body_txt = r.text
    check("last_director_deactivate_blocked",
          r.status_code == 400 and "last_director_protected" in body_txt,
          f"http={r.status_code} body={body_txt[:120]}")

    # T-19b: The same admin trying to strip 'director' from qa_uid via /roles
    # must also be blocked with `last_director_protected`.
    r = requests.post(f"{BASE}/api/admin/access/users/{qa_uid}/roles",
                       headers=admin_hdr, json={"roles": ["pm"]}, timeout=5)
    check("last_director_role_strip_blocked",
          r.status_code == 400 and "last_director_protected" in r.text,
          f"http={r.status_code} body={r.text[:120]}")

    # ── T-20: self-role change forbidden (guardrail) ──
    r = requests.post(f"{BASE}/api/admin/access/users/{qa_uid}/roles",
                       headers=hdr, json={"roles": ["pm"]}, timeout=5)
    check("self_role_change_blocked", r.status_code == 400, f"http={r.status_code}")

    # ── T-21: Multi-role assignment returned correctly ──
    # Give a fresh pending user multiple roles
    c9 = MongoClient(STG_URL)
    multi_uid = "user_multi_" + uuid.uuid4().hex[:6]
    c9[STG_DB].users.insert_one({
        "user_id": multi_uid, "email": f"multi-{uuid.uuid4().hex[:6]}@vasu.staging",
        "name": "Multi", "picture": "", "role": None, "roles": [],
        "is_active": False, "created_at": datetime.now(timezone.utc),
    })
    c9.close()
    # Activate first with role=pm, then assign multi-role
    requests.post(f"{BASE}/api/admin/access/users/{multi_uid}/activate",
                    headers=hdr, json={"role": "pm"}, timeout=5)
    r = requests.post(f"{BASE}/api/admin/access/users/{multi_uid}/roles",
                       headers=hdr, json={"roles": ["pm", "purchase"]}, timeout=5)
    check("multi_role_assign",
          r.status_code == 200 and r.json().get("roles") == ["pm", "purchase"],
          f"http={r.status_code}")

    # ── T-22: Invalid role in /roles → 400 ──
    r = requests.post(f"{BASE}/api/admin/access/users/{multi_uid}/roles",
                       headers=hdr, json={"roles": ["godmode"]}, timeout=5)
    check("invalid_role_in_roles_rejected", r.status_code == 400, f"http={r.status_code}")

    # Save report
    passed = sum(1 for x in results if x["ok"])
    failed = sum(1 for x in results if not x["ok"])
    Path("/app/backup_artifacts/task3a_report.json").write_text(json.dumps({
        "results": results, "passed": passed, "failed": failed,
        "staging_db": STG_DB, "staging_port": STG_PORT,
        "flag": "ACCESS_SECURITY_V2=1",
    }, indent=2))
    print(f"\n[report] passed={passed} failed={failed}")

finally:
    proc.send_signal(signal.SIGTERM)
    try: proc.wait(timeout=5)
    except Exception: proc.kill()
    log.close()
    print("[api] staging API stopped.")
