"""Vendors router — extracted from server.py in Phase 9C round 5 (Batch C).

Consolidates the four scattered /vendors endpoints (list, create, update,
deactivate) into a single self-contained module. Admin/purchase/director
required for mutations; any authenticated user can list.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, audit, master_audit,
    Vendor,
)


@api.get("/vendors")
async def list_vendors(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    return await db.vendors.find({"active": True}, {"_id": 0}).to_list(500)


@api.post("/vendors")
async def add_vendor(v: Vendor, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    await db.vendors.insert_one(v.model_dump())
    await audit("vendor", v.vendor_id, "create", u, v.model_dump())
    return v


@api.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    existing = await db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Vendor not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")
    updates: Dict[str, Any] = {}
    for k in ("name", "address", "gstin", "contact", "email"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.vendors.update_one({"vendor_id": vendor_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit("vendor", vendor_id, "update", u, reason, old_snap, updates)
    return await db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})


@api.delete("/vendors/{vendor_id}")
async def deactivate_vendor(vendor_id: str, reason: str = "Deactivated",
                              authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    r = await db.vendors.update_one({"vendor_id": vendor_id},
                                       {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Vendor not found")
    await master_audit("vendor", vendor_id, "deactivate", u, reason,
                        {"active": True}, {"active": False})
    return {"ok": True}
