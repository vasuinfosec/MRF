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
import uuid
from datetime import timedelta
from typing import Optional, List
from fastapi import Header, HTTPException

import httpx

from server import (
    api, db, get_current_user, audit, now_utc,
    SessionRequest, UserOut, RoleUpdate,
    ROLES, LEGACY_ROLE_MAP,
)


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
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        role = existing.get("role", "site_engineer")
        if role in LEGACY_ROLE_MAP:
            role = LEGACY_ROLE_MAP[role]
            await db.users.update_one({"email": email}, {"$set": {"role": role}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        count = await db.users.count_documents({})
        # First user becomes admin; subsequent unknown users default to site_engineer.
        role = "admin" if count == 0 else "site_engineer"
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
async def dev_login(body: dict):
    """Dev-only endpoint. Disabled in production via ENABLE_DEV_LOGIN env flag."""
    if os.environ.get("ENABLE_DEV_LOGIN", "0") != "1":
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
