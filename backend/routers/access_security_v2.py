"""Task 3A.1 — Access-Security V2 (secure by default, feature-flagged).

Active unless env `ACCESS_SECURITY_V2=0` explicitly selects the legacy flow.

Corrected staging behaviour when flag=1 (post T3A.1 review):
  * Uninvited Google sign-in → records into `pending_access_requests` ONLY,
    NEVER inserts a row into `users`. HTTP 403 access_pending.
  * Invited Google sign-in → creates an active user with the Access Admin's
    assigned role and records the invitation as consumed.
  * `count==0 → admin` bootstrap: REMOVED.
  * OWNER_EMAILS: IGNORED (no auto-Director).
  * dev-login: HARD-DISABLED (returns 404 regardless of host).
  * Every activation/deactivation/role-change writes to audit_logs.
  * GUARDRAILS:
      - An operator MUST NOT activate/elevate/deactivate themselves.
      - The last active Director MUST NOT be deactivated or have Director
        removed from their `roles` list.
  * Multi-role storage: `roles: list[str]` is authoritative. Legacy `role`
    is dual-written (roles[0]) for BC and rolled back cleanly when needed.

All review and mutation endpoints under /api/admin/access/* are restricted to
the single email-bound Access Admin. /permissions/me remains available to any
authenticated user.
"""
from __future__ import annotations
import os
import uuid
from datetime import timedelta
from typing import Optional, List
from fastapi import Header, HTTPException, Body
from pydantic import BaseModel, EmailStr, Field

from server import (
    api, db, get_current_user, audit, now_utc, ROLES, UserOut,
    _ensure_roles_shape, ACCESS_ADMIN_EMAIL, FIXED_ROLE_EMAILS,
)

CANONICAL_ROLES = set(ROLES)
ASSIGNABLE_ROLES = CANONICAL_ROLES - {"admin"}


def _flag_on() -> bool:
    return os.environ.get("ACCESS_SECURITY_V2", "1") == "1"


async def _count_active_directors(exclude_uid: Optional[str] = None) -> int:
    q = {
        "is_active": True,
        "$or": [{"role": "director"}, {"roles": "director"}],
    }
    if exclude_uid:
        q["user_id"] = {"$ne": exclude_uid}
    return await db.users.count_documents(q)


def _requires_v2():
    if not _flag_on():
        raise HTTPException(404, "Not found")


def _requires_mgmt(u: UserOut):
    if (u.email or "").strip().lower() != ACCESS_ADMIN_EMAIL:
        raise HTTPException(403, "Only the Access Admin can manage users and roles")


# ---------------------- Models ----------------------
class InvitationIn(BaseModel):
    email: EmailStr
    role: str = Field(..., description="Canonical role at activation time")
    expires_in_hours: int = 72
    note: Optional[str] = ""

class InvitationUpdate(BaseModel):
    email: EmailStr
    role: str
    expires_in_hours: int = 72
    note: Optional[str] = ""


class ActivateIn(BaseModel):
    role: str
    note: Optional[str] = ""


class RolesIn(BaseModel):
    roles: List[str]
    note: Optional[str] = ""


class InviteFromRequestIn(BaseModel):
    role: str
    expires_in_hours: int = 72
    note: Optional[str] = ""


# ---------------------- Invitations ----------------------
@api.post("/admin/access/invitations")
async def create_invitation(body: InvitationIn,
                            authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ASSIGNABLE_ROLES)}")
    email = str(body.email).strip().lower()
    fixed_role = FIXED_ROLE_EMAILS.get(email)
    if fixed_role and body.role != fixed_role:
        raise HTTPException(400, f"This account has the fixed role: {fixed_role}")
    if await db.users.find_one({"email": email, "is_active": True}, {"_id": 1}):
        raise HTTPException(409, "This email already belongs to an active user")
    if await db.invitations.find_one(
        {"email": email, "consumed": False, "expires_at": {"$gt": now_utc()}},
        {"_id": 1},
    ):
        raise HTTPException(409, "An active access entry already exists for this email")
    iid = f"inv_{uuid.uuid4().hex[:12]}"
    doc = {
        "invitation_id": iid,
        "email": email,
        "role": body.role,
        "note": body.note or "",
        "issued_by": u.user_id,
        "issued_at": now_utc(),
        "expires_at": now_utc() + timedelta(hours=max(1, int(body.expires_in_hours))),
        "consumed": False,
    }
    await db.invitations.insert_one(doc)
    await audit("invitation", iid, "create", u,
                {"email": email, "role": body.role})
    return {k: v for k, v in doc.items() if k != "_id"}

@api.put("/admin/access/invitations/{iid}")
async def update_invitation(iid: str, body: InvitationUpdate,
                            authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ASSIGNABLE_ROLES)}")
    current = await db.invitations.find_one(
        {"invitation_id": iid, "consumed": False}, {"_id": 0}
    )
    if not current:
        raise HTTPException(404, "Access entry not found or already used")
    email = str(body.email).strip().lower()
    fixed_role = FIXED_ROLE_EMAILS.get(email)
    if fixed_role and body.role != fixed_role:
        raise HTTPException(400, f"This account has the fixed role: {fixed_role}")
    if await db.users.find_one({"email": email, "is_active": True}, {"_id": 1}):
        raise HTTPException(409, "This email already belongs to an active user")
    duplicate = await db.invitations.find_one(
        {
            "invitation_id": {"$ne": iid},
            "email": email,
            "consumed": False,
            "expires_at": {"$gt": now_utc()},
        },
        {"_id": 1},
    )
    if duplicate:
        raise HTTPException(409, "An active access entry already exists for this email")
    changes = {
        "email": email,
        "role": body.role,
        "note": body.note or "",
        "expires_at": now_utc() + timedelta(hours=max(1, int(body.expires_in_hours))),
        "updated_by": u.user_id,
        "updated_at": now_utc(),
    }
    await db.invitations.update_one({"invitation_id": iid}, {"$set": changes})
    await audit("invitation", iid, "update", u, {
        "old_email": current.get("email"),
        "new_email": email,
        "old_role": current.get("role"),
        "new_role": body.role,
    })
    updated = await db.invitations.find_one({"invitation_id": iid}, {"_id": 0})
    return updated


@api.get("/admin/access/invitations")
async def list_invitations(authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    rows = await db.invitations.find({}, {"_id": 0}).sort("issued_at", -1).to_list(500)
    return rows


@api.delete("/admin/access/invitations/{iid}")
async def revoke_invitation(iid: str,
                            authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    r = await db.invitations.delete_one({"invitation_id": iid, "consumed": False})
    if r.deleted_count == 0:
        raise HTTPException(404, "invitation not found or already consumed")
    await audit("invitation", iid, "revoke", u)
    return {"deleted": True}


# ---------------------- Pending users / pending access requests ----------------------
@api.get("/admin/access/pending-users")
async def list_pending_users(authorization: Optional[str] = Header(None)):
    """Users who accepted an invitation but haven't been activated yet."""
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    rows = await db.users.find(
        {"$or": [{"is_active": False}, {"role": None}, {"role": ""}]},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "created_at": 1,
         "role": 1, "roles": 1, "is_active": 1, "pending_since": 1,
         "invited_role": 1, "invited_by": 1},
    ).sort("created_at", -1).to_list(500)
    return rows


@api.get("/admin/access/pending-requests")
async def list_pending_requests(authorization: Optional[str] = Header(None)):
    """Uninvited sign-in attempts — Access Admin may promote to invitation."""
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    rows = await db.pending_access_requests.find({}, {"_id": 0}).sort(
        "last_attempt_at", -1).to_list(500)
    return rows


@api.post("/admin/access/pending-requests/{rid}/invite")
async def invite_from_request(rid: str, body: InviteFromRequestIn,
                              authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ASSIGNABLE_ROLES)}")
    req = await db.pending_access_requests.find_one({"request_id": rid}, {"_id": 0})
    if not req:
        raise HTTPException(404, "pending request not found")
    email = str(req["email"]).strip().lower()
    fixed_role = FIXED_ROLE_EMAILS.get(email)
    if fixed_role and body.role != fixed_role:
        raise HTTPException(400, f"This account has the fixed role: {fixed_role}")
    iid = f"inv_{uuid.uuid4().hex[:12]}"
    doc = {
        "invitation_id": iid,
        "email": email,
        "role": body.role,
        "note": body.note or f"promoted from request {rid}",
        "issued_by": u.user_id,
        "issued_at": now_utc(),
        "expires_at": now_utc() + timedelta(hours=max(1, int(body.expires_in_hours))),
        "consumed": False,
        "from_request_id": rid,
    }
    await db.invitations.insert_one(doc)
    await db.pending_access_requests.update_one(
        {"request_id": rid},
        {"$set": {"promoted_to_invitation": iid, "promoted_at": now_utc(),
                  "promoted_by": u.user_id}},
    )
    await audit("invitation", iid, "create_from_request", u,
                {"email": email, "role": body.role, "request_id": rid})
    return {k: v for k, v in doc.items() if k != "_id"}


# ---------------------- Activation / deactivation ----------------------
@api.post("/admin/access/users/{uid}/activate")
async def activate_user(uid: str, body: ActivateIn,
                        authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ASSIGNABLE_ROLES)}")
    # Guardrail: no self-elevation
    if uid == u.user_id:
        raise HTTPException(400, "Cannot activate or elevate yourself")
    target = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "user not found")
    fixed_role = FIXED_ROLE_EMAILS.get(
        (target.get("email") or "").strip().lower()
    )
    if fixed_role and body.role != fixed_role:
        raise HTTPException(400, f"This account has the fixed role: {fixed_role}")
    # Dual-write: role (BC) + roles (source of truth)
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {
            "is_active": True,
            "role": body.role,
            "roles": [body.role],
            "activated_by": u.user_id,
            "activated_at": now_utc(),
        }},
    )
    await audit("user", uid, "activate", u,
                {"role": body.role, "roles": [body.role],
                 "note": body.note or ""})
    return {"user_id": uid, "is_active": True, "role": body.role,
            "roles": [body.role]}


@api.post("/admin/access/users/{uid}/deactivate")
async def deactivate_user(uid: str,
                          reason: str = Body(..., embed=True),
                          authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if uid == u.user_id:
        raise HTTPException(400, "Cannot deactivate yourself")
    target = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "user not found")
    fixed_role = FIXED_ROLE_EMAILS.get(
        (target.get("email") or "").strip().lower()
    )
    if fixed_role:
        raise HTTPException(400, f"Cannot deactivate the fixed {fixed_role} account")
    # Guardrail: don't remove the last active Director
    target_roles = set(target.get("roles") or []) | (
        {target.get("role")} if target.get("role") else set()
    )
    if "director" in target_roles:
        remaining = await _count_active_directors(exclude_uid=uid)
        if remaining < 1:
            raise HTTPException(400, {
                "error": "last_director_protected",
                "message": "Refusing to deactivate the last active Director.",
            })
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {"is_active": False, "deactivated_by": u.user_id,
                  "deactivated_at": now_utc(),
                  "deactivation_reason": reason or ""}},
    )
    await db.user_sessions.delete_many({"user_id": uid})
    await audit("user", uid, "deactivate", u, {"reason": reason})
    return {"user_id": uid, "is_active": False}


# ---------------------- Multi-role assignment ----------------------
@api.post("/admin/access/users/{uid}/roles")
async def set_user_roles(uid: str, body: RolesIn,
                         authorization: Optional[str] = Header(None)):
    """Replace a user's `roles` list. Dual-writes `role = roles[0]` for BC.

    Guardrails:
      * Cannot modify your own roles (no self-elevation).
      * Cannot remove `director` from the last active Director.
      * Every role must be canonical.
    """
    _requires_v2()
    u = await get_current_user(authorization)
    _requires_mgmt(u)
    if uid == u.user_id:
        raise HTTPException(400, "Cannot modify your own roles")
    if not body.roles:
        raise HTTPException(400, "roles must be a non-empty list")
    # Canonicalise, dedupe (preserve order)
    seen, cleaned = set(), []
    for r in body.roles:
        if r not in ASSIGNABLE_ROLES:
            raise HTTPException(400, f"invalid role: {r}")
        if r not in seen:
            seen.add(r)
            cleaned.append(r)
    target = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "user not found")
    fixed_role = FIXED_ROLE_EMAILS.get(
        (target.get("email") or "").strip().lower()
    )
    if fixed_role and cleaned != [fixed_role]:
        raise HTTPException(400, f"This account has the fixed role: {fixed_role}")
    # Guardrail: don't strip Director from the last active Director
    old_roles = set(target.get("roles") or []) | (
        {target.get("role")} if target.get("role") else set()
    )
    was_director = "director" in old_roles and target.get("is_active", False)
    will_be_director = "director" in cleaned
    if was_director and not will_be_director:
        remaining = await _count_active_directors(exclude_uid=uid)
        if remaining < 1:
            raise HTTPException(400, {
                "error": "last_director_protected",
                "message": "Refusing to remove Director from the last active Director.",
            })
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {"roles": cleaned, "role": cleaned[0],
                  "roles_updated_by": u.user_id,
                  "roles_updated_at": now_utc()}},
    )
    await audit("user", uid, "roles_set", u,
                {"old": sorted(old_roles), "new": cleaned,
                 "note": body.note or ""})
    return {"user_id": uid, "roles": cleaned, "role": cleaned[0]}


@api.get("/admin/access/permissions/me")
async def my_permissions(authorization: Optional[str] = Header(None)):
    _requires_v2()
    u = await get_current_user(authorization)
    # Reload the full doc so we can return the authoritative roles list
    raw = await db.users.find_one({"user_id": u.user_id}, {"_id": 0}) or {}
    raw = _ensure_roles_shape(raw)
    return {
        "user_id": u.user_id,
        "role": raw.get("role", u.role),
        "roles": raw.get("roles", u.roles or ([u.role] if u.role else [])),
        "is_active": bool(raw.get("is_active", True)),
    }
