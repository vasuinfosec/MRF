"""Settings router — Purchase Order approval thresholds.

Extracted from server.py in Phase 9C. Read-only for everyone; write locked to
Director/Admin.
"""
from __future__ import annotations

from typing import Optional
from fastapi import Header, HTTPException

from server import api, db, get_current_user, get_thresholds, audit, now_utc


@api.get("/settings/thresholds")
async def get_settings_thresholds(authorization: Optional[str] = Header(None)):
    """Any authenticated user can read thresholds (UI needs it to show approval hints)."""
    await get_current_user(authorization)
    return await get_thresholds()


@api.put("/settings/thresholds")
async def update_settings_thresholds(body: dict,
                                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("director", "admin"):
        raise HTTPException(403, "Only Director/Admin can change purchase thresholds")
    gm = body.get("gm")
    dr = body.get("director")
    if gm is None or dr is None:
        raise HTTPException(400, "Both 'gm' and 'director' threshold values required")
    try:
        gm = float(gm); dr = float(dr)
    except Exception:
        raise HTTPException(400, "Thresholds must be numeric")
    if gm < 0 or dr < 0:
        raise HTTPException(400, "Thresholds must be non-negative")
    if dr < gm:
        raise HTTPException(400, "Director threshold must be >= GM threshold")
    await db.settings.update_one(
        {"_id": "thresholds"},
        {"$set": {"gm": gm, "director": dr,
                  "updated_by": u.user_id, "updated_at": now_utc()}},
        upsert=True,
    )
    await audit("settings", "thresholds", "update", u, {"gm": gm, "director": dr})
    return {"gm": gm, "director": dr}
