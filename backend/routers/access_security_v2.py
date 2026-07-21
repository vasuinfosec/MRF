"""Task 3A — Access-Security V2 (staging-only, feature-flagged).

Activated only when env `ACCESS_SECURITY_V2=1`. When OFF, the module is not
mounted and the legacy auth flow in auth.py is used unchanged (prod path).

Staging behaviour when flag=1:
  * Google sign-in of a NEW email → checks `invitations` collection:
      - matching un-consumed invite → user created with is_active=True and
        invited role, invitation marked consumed.
      - no invite → user created is_active=False, role=None, redirected to
        a "Pending approval" screen.
  * `count==0 → admin` bootstrap: DELETED.
  * OWNER_EMAILS: IGNORED (no auto-Director).
  * dev-login: HARD-DISABLED (returns 404 regardless of host).
  * Every activation/deactivation/role-change/invitation writes to

Endpoints exposed under /api/admin/access/*:
  POST   /invitations                – admin/director
  GET    /invitations                – admin/director
  DELETE /invitations/{iid}          – admin/director
  GET    /pending-users              – admin/director
  POST   /users/{uid}/activate       – admin/director  (body: {role})
  POST   /users/{uid}/deactivate     – admin/director
  GET    /permissions/me             – any authenticated user
"""
from __future__ import annotations
import os, uuid, secrets
from datetime import timedelta
from typing import Optional, List
from fastapi import Header, HTTPException, Body
from pydantic import BaseModel, EmailStr, Field

from server import api, db, get_current_user, audit, now_utc, ROLES, UserOut

CANONICAL_ROLES = set(ROLES)
MANAGEMENT_ROLES = {"admin", "director"}


def _flag_on() -> bool:
    return os.environ.get("ACCESS_SECURITY_V2", "0") == "1"


# ---------------------- Models ----------------------
class InvitationIn(BaseModel):
    email: EmailStr
    role: str = Field(..., description="Canonical role at activation time")
    expires_in_hours: int = 72
    note: Optional[str] = ""


class ActivateIn(BaseModel):
    role: str
    note: Optional[str] = ""


# ---------------------- Invitations ----------------------
@api.post("/admin/access/invitations")
async def create_invitation(body: InvitationIn,
                              authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    if body.role not in CANONICAL_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(CANONICAL_ROLES)}")
    email = str(body.email).strip().lower()
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
    await audit(entity="invitation", entity_id=iid, action="create",
                 user=u, details={"email": email, "role": body.role})
    return {k: v for k, v in doc.items() if k != "_id"}


@api.get("/admin/access/invitations")
async def list_invitations(authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    rows = await db.invitations.find({}, {"_id": 0}).sort("issued_at", -1).to_list(500)
    return rows


@api.delete("/admin/access/invitations/{iid}")
async def revoke_invitation(iid: str,
                              authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    r = await db.invitations.delete_one({"invitation_id": iid, "consumed": False})
    if r.deleted_count == 0:
        raise HTTPException(404, "invitation not found or already consumed")
    await audit(entity="invitation", entity_id=iid, action="revoke",
                 user=u)
    return {"deleted": True}


# ---------------------- Pending users & activation ----------------------
@api.get("/admin/access/pending-users")
async def list_pending_users(authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    rows = await db.users.find(
        {"$or": [{"is_active": False}, {"role": None}, {"role": ""}]},
        {"_id": 0, "user_id": 1, "email": 1, "name": 1, "created_at": 1,
         "role": 1, "is_active": 1, "pending_since": 1},
    ).sort("created_at", -1).to_list(500)
    return rows


@api.post("/admin/access/users/{uid}/activate")
async def activate_user(uid: str, body: ActivateIn,
                          authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    if body.role not in CANONICAL_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(CANONICAL_ROLES)}")
    target = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "user not found")
    await db.users.update_one({"user_id": uid},
                                {"$set": {"is_active": True, "role": body.role,
                                            "activated_by": u.user_id,
                                            "activated_at": now_utc()}})
    await audit(entity="user", entity_id=uid, action="activate",
                 user=u, details={"role": body.role, "note": body.note or ""})
    return {"user_id": uid, "is_active": True, "role": body.role}


@api.post("/admin/access/users/{uid}/deactivate")
async def deactivate_user(uid: str,
                            reason: str = Body(..., embed=True),
                            authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    if u.role not in MANAGEMENT_ROLES:
        raise HTTPException(403, "Admin or Director only")
    if uid == u.user_id:
        raise HTTPException(400, "Cannot deactivate yourself")
    r = await db.users.update_one(
        {"user_id": uid},
        {"$set": {"is_active": False, "deactivated_by": u.user_id,
                    "deactivated_at": now_utc(),
                    "deactivation_reason": reason or ""}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "user not found")
    # Kill all live sessions for that user
    await db.user_sessions.delete_many({"user_id": uid})
    await audit(entity="user", entity_id=uid, action="deactivate",
                 user=u, details={"reason": reason})
    return {"user_id": uid, "is_active": False}


@api.get("/admin/access/permissions/me")
async def my_permissions(authorization: Optional[str] = Header(None)):
    if not _flag_on():
        raise HTTPException(404, "Not found")
    u = await get_current_user(authorization)
    return {"user_id": u.user_id, "role": u.role, "is_active": True}
