"""Auth + Users router — extracted from server.py in Phase 9C round 5 (Batch C).

Endpoints:
  - POST /api/auth/session      (Emergent-managed Google OAuth callback → JWT)
  - GET  /api/auth/me           (current user from Bearer token)
  - POST /api/auth/logout       (revoke session)
  - POST /api/auth/dev-login    (dev-only, gated by ENABLE_DEV_LOGIN=1)
  - GET  /api/users             (admin sees full; others get lightweight directory)
  - POST /api/users/role        (admin-only role change)

All auth-critical logic (bcrypt / OAuth handshake / role canonicalisation) is
preserved byte-identical from the pre-refactor server.py.
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import timedelta
from typing import Optional, List
from fastapi import Header, HTTPException, Request

import httpx

from server import (
    api, db, get_current_user, audit, now_utc,
    SessionRequest, UserOut, RoleUpdate,
    ROLES, LEGACY_ROLE_MAP,
)


def _is_dev_login_host_allowed(host: str) -> bool:
    """Whitelist of hostnames from which the dev-login backdoor may be used.

    Emergent's cloud passes TWO relevant headers:
      * `Host`             = internal K8s cluster hostname (`*.preview.emergentcf.cloud`)
      * `X-Forwarded-Host` = public preview hostname       (`*.preview.emergentagent.com`)
    Production custom domains show up in NEITHER match pattern, so this
    check remains safe.

    Allowed suffixes/exacts:
      * .preview.emergentagent.com
      * .preview.emergentcf.cloud
      * localhost / 127.0.0.1 / 0.0.0.0
    """
    h = (host or "").split(":", 1)[0].lower().strip()
    if not h:
        return False
    if h in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    if h.endswith(".preview.emergentagent.com"):
        return True
    if h.endswith(".preview.emergentcf.cloud"):
        return True
    return False


@api.post("/auth/session")
async def create_session(body: SessionRequest):
    """Exchange an Emergent session_id for a long-lived Bearer session_token."""
    async with httpx.AsyncClient(timeout=15) as client_http:
        r = await client_http.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": body.session_id},
        )
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session_id")
        data = r.json()

    email = data["email"]
    email_norm = (email or "").strip().lower()

    # ─── Access-Security V2 gate (Task 3A) ─────────────────────────────
    # When ACCESS_SECURITY_V2=1 (staging only), retire all automatic role
    # assignment: OWNER_EMAILS ignored, first-user auto-admin retired, new
    # signups require an active invitation OR land inactive+role-free.
    v2 = os.environ.get("ACCESS_SECURITY_V2", "0") == "1"

    if v2:
        existing = await db.users.find_one({"email": email}, {"_id": 0})
        if existing:
            user_id = existing["user_id"]
            role = existing.get("role")
            # Legacy remap still applied for prior-provisioned accounts
            if role in LEGACY_ROLE_MAP:
                role = LEGACY_ROLE_MAP[role]
                await db.users.update_one({"email": email}, {"$set": {"role": role}})
            if not existing.get("is_active", False):
                raise HTTPException(403, {
                    "error": "access_pending",
                    "message": "Your access is pending Director approval.",
                    "user_id": user_id,
                })
        else:
            # New signup path — check invitations
            invite = await db.invitations.find_one({
                "email": email_norm, "consumed": False,
                "expires_at": {"$gt": now_utc()},
            })
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            if invite:
                role = invite["role"]
                await db.users.insert_one({
                    "user_id": user_id, "email": email,
                    "name": data.get("name", email), "picture": data.get("picture", ""),
                    "role": role, "is_active": True,
                    "created_at": now_utc(),
                    "activated_via_invitation": invite["invitation_id"],
                })
                await db.invitations.update_one(
                    {"invitation_id": invite["invitation_id"]},
                    {"$set": {"consumed": True, "consumed_by": user_id,
                                "consumed_at": now_utc()}},
                )
            else:
                # Role-free, inactive by default
                role = None
                await db.users.insert_one({
                    "user_id": user_id, "email": email,
                    "name": data.get("name", email), "picture": data.get("picture", ""),
                    "role": None, "is_active": False,
                    "created_at": now_utc(),
                    "pending_since": now_utc(),
                })
                # Anonymous audit entry for the pending signup
                await db.audit_logs.insert_one({
                    "audit_id": f"aud_{uuid.uuid4().hex[:12]}",
                    "entity": "user", "entity_id": user_id,
                    "action": "pending_signup",
                    "user_id": user_id, "user_name": data.get("name", email),
                    "user_role": "pending", "severity": "critical",
                    "details": {"email": email},
                    "timestamp": now_utc(),
                })
                raise HTTPException(403, {
                    "error": "access_pending",
                    "message": "Access requires Director approval. You have been added to the pending list.",
                    "user_id": user_id,
                })
    else:
        # ───────── Legacy prod path (unchanged) ─────────
        # Owner allowlist and first-user bootstrap kept for prod compatibility.
        owner_list = {
            e.strip().lower()
            for e in (os.environ.get("OWNER_EMAILS", "") or "").split(",")
            if e.strip()
        }
        trusted_domains = {
            d.strip().lower().lstrip("@")
            for d in (os.environ.get("TRUSTED_DOMAINS", "") or "").split(",")
            if d.strip()
        }
        is_owner = email_norm in owner_list
        domain = email_norm.rsplit("@", 1)[-1] if "@" in email_norm else ""
        is_trusted_domain = domain in trusted_domains

        existing = await db.users.find_one({"email": email}, {"_id": 0})
        if existing:
            user_id = existing["user_id"]
            role = existing.get("role", "site_engineer")
            if role in LEGACY_ROLE_MAP:
                role = LEGACY_ROLE_MAP[role]
                await db.users.update_one({"email": email}, {"$set": {"role": role}})
            if is_owner and role != "director":
                role = "director"
                await db.users.update_one({"email": email}, {"$set": {"role": role}})
            elif is_trusted_domain and role == "site_engineer":
                role = "pm"
                await db.users.update_one({"email": email}, {"$set": {"role": role}})
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            count = await db.users.count_documents({})
            if is_owner:
                role = "director"
            elif count == 0:
                role = "admin"
            elif is_trusted_domain:
                role = "pm"
            else:
                role = "site_engineer"
            await db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "name": data.get("name", email),
                "picture": data.get("picture", ""),
                "role": role,
                "is_active": True,
                "created_at": now_utc(),
            })

    session_token = data["session_token"]
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": now_utc() + timedelta(days=7),
            "created_at": now_utc(),
        }},
        upsert=True,
    )
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    try:
        await audit("auth", user_id, "login", UserOut(**user),
                    {"method": "emergent", "email": email})
    except Exception:
        pass
    return {"session_token": session_token, "user": UserOut(**user).model_dump()}


@api.get("/auth/me", response_model=UserOut)
async def me(authorization: Optional[str] = Header(None)):
    return await get_current_user(authorization)


@api.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        if sess:
            u = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
            if u:
                try:
                    await audit("auth", u["user_id"], "logout", UserOut(**u), {})
                except Exception:
                    pass
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


@api.post("/auth/dev-login")
async def dev_login(body: dict, request: Request):
    """Dev-only endpoint. Two independent guards must BOTH pass:

    1. `ENABLE_DEV_LOGIN=1` environment flag is set.
    2. The inbound request's Host header is on an allowed dev/preview hostname
       (`*.preview.emergentagent.com` or localhost). Even if the env flag
       accidentally leaks into a production image, an external attacker on the
       production hostname cannot reach this endpoint.

    On any failure we return 404 (not 403) so the endpoint appears absent.
    """
    if os.environ.get("ENABLE_DEV_LOGIN", "0") != "1":
        raise HTTPException(404, "Not found")
    # Task 3A: Access-Security V2 disables dev-login regardless of host.
    if os.environ.get("ACCESS_SECURITY_V2", "0") == "1":
        raise HTTPException(404, "Not found")
    host_direct = request.headers.get("host") or ""
    host_fwd = request.headers.get("x-forwarded-host") or ""
    # Allow the request if EITHER the internal Host or the public
    # X-Forwarded-Host is on the whitelist. Production custom domains match
    # neither, so they're safely rejected.
    if not (_is_dev_login_host_allowed(host_direct)
             or _is_dev_login_host_allowed(host_fwd)):
        # Log the block so ops has a signal if someone attempts to abuse it.
        try:
            await db.audit_logs.insert_one({
                "audit_id": f"aud_{uuid.uuid4().hex[:12]}",
                "entity": "auth", "entity_id": "dev-login-blocked",
                "action": "dev_login_blocked", "user_id": "anonymous",
                "user_name": "anonymous", "user_role": "anonymous",
                "details": {"host": host_direct,
                             "x_forwarded_host": host_fwd,
                             "email": (body or {}).get("email"),
                             "role": (body or {}).get("role")},
                "timestamp": now_utc(),
            })
        except Exception:
            pass
        raise HTTPException(404, "Not found")
    email = body.get("email")
    role = body.get("role", "pm")
    name = body.get("name", email.split("@")[0] if email else "Dev User")
    if not email:
        raise HTTPException(400, "email required")
    if role not in ROLES:
        raise HTTPException(400, "invalid role")
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one({"user_id": user_id},
                                    {"$set": {"role": role, "name": name}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": email, "name": name, "picture": "",
            "role": role, "is_active": True, "created_at": now_utc(),
        })
    session_token = f"dev_{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "session_token": session_token, "user_id": user_id,
        "expires_at": now_utc() + timedelta(days=7), "created_at": now_utc(),
    })
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    try:
        await audit("auth", user_id, "login", UserOut(**user),
                    {"method": "dev-login", "email": email, "role": role})
    except Exception:
        pass
    return {"session_token": session_token, "user": UserOut(**user).model_dump()}


@api.post("/auth/download-token")
async def create_download_token(authorization: Optional[str] = Header(None)):
    """SEC-003: Mint a short-lived (5-minute), single-use download token.

    Browser file downloads have to embed the auth in the URL because native
    `<a>` / `window.open` cannot set headers. Instead of exposing the long-
    lived 7-day session token via `?token=`, the frontend calls this endpoint
    first, gets a `dt_*` token, and passes THAT as `?token=`. The download
    endpoint recognises the `dt_` prefix in `get_current_user`, validates the
    token, marks it used atomically, and rejects any subsequent reuse.
    """
    u = await get_current_user(authorization)
    token = f"dt_{secrets.token_urlsafe(24)}"
    await db.download_tokens.insert_one({
        "token": token,
        "user_id": u.user_id,
        "expires_at": now_utc() + timedelta(minutes=5),
        "used": False,
        "created_at": now_utc(),
    })
    return {"token": token, "expires_in": 300}


# ---------------------- Users / Roles ----------------------
@api.get("/users", response_model=List[UserOut])
async def list_users(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        # Non-admin: return only lightweight directory info (name/role) without emails
        users = await db.users.find({}, {"_id": 0}).to_list(1000)
        return [UserOut(**{**x, "email": ""}) for x in users]
    users = await db.users.find({}, {"_id": 0}).to_list(1000)
    return [UserOut(**u2) for u2 in users]


@api.post("/users/role", response_model=UserOut)
async def set_role(body: RoleUpdate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin can change roles")
    if body.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    r = await db.users.update_one({"user_id": body.user_id},
                                     {"$set": {"role": body.role}})
    if r.matched_count == 0:
        raise HTTPException(404, "User not found")
    user = await db.users.find_one({"user_id": body.user_id}, {"_id": 0})
    return UserOut(**user)
