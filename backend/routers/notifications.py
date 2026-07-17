"""Notifications router — extracted from server.py in Phase 9C.

Attaches /api/notifications endpoints to the shared APIRouter. Imported at the
bottom of server.py *for side effects*.
"""
from __future__ import annotations

from typing import Optional
from fastapi import Header

from server import api, db, get_current_user


@api.get("/notifications")
async def list_notifications(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    docs = await db.notifications.find(
        {"user_id": u.user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(50).to_list(50)
    return docs


@api.post("/notifications/{nid}/read")
async def read_notif(nid: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    await db.notifications.update_one(
        {"notification_id": nid, "user_id": u.user_id},
        {"$set": {"read": True}},
    )
    return {"ok": True}
