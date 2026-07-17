"""Comparative Statement (CS) router — extracted from server.py in Phase 9C round 4.

Imports/creates/manages externally-prepared Comparative Statements (Excel/PDF)
that are stored inline as base64. Independent approval flow: PM/GM/Director
approves; Admin/Director can override or delete.
"""
from __future__ import annotations

import io
import base64 as _b64
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, Body
from fastapi.responses import StreamingResponse

from server import (
    api, db, get_current_user, audit, now_utc,
    _strip_oids, _log_export, next_cs_number,
    ComparativeStatementCreate, ComparativeStatement,
    CS_APPROVER_ROLES,
)


CS_ROLES_UPLOAD = {"purchase", "admin"}  # Purchase (and Admin/Accounts) upload/edit CS
CS_ROLES_VIEW = {"purchase", "pm", "gm", "director", "admin", "site_engineer"}


# ---------------------- Comparative Statement CRUD ----------------------
@api.post("/comparative-statement")
async def create_cs(body: ComparativeStatementCreate,
                     authorization: Optional[str] = Header(None)):
    """Import a Comparative Statement prepared outside the app (Excel/PDF).
    File stored inline as base64. Metadata (L1/L2/L3, selected vendor, remarks)
    accepted alongside. Attach via mrf_id or po_id (or both)."""
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_UPLOAD:
        raise HTTPException(403, "Not allowed to upload Comparative Statement")
    if not body.file_base64:
        raise HTTPException(400, "file_base64 is required")
    if not (body.mrf_id or body.po_id):
        raise HTTPException(400, "Attach to either mrf_id or po_id")

    try:
        raw = _b64.b64decode((body.file_base64.split(",", 1)[-1]).encode("utf-8"),
                              validate=False)
        size = len(raw)
    except Exception:
        size = 0
    if size > 15 * 1024 * 1024:
        raise HTTPException(413, "File exceeds 15 MB")

    # Resolve project/customer from attached record if not supplied
    project_id = body.project_id
    customer_id = body.customer_id
    if body.mrf_id and not project_id:
        m = await db.mrfs.find_one({"mrf_id": body.mrf_id},
                                    {"_id": 0, "project_id": 1, "customer_id": 1})
        if m:
            project_id = m.get("project_id") or project_id
            customer_id = m.get("customer_id") or customer_id
    if body.po_id and not project_id:
        p = await db.pos.find_one({"po_id": body.po_id},
                                    {"_id": 0, "project_id": 1, "customer_id": 1})
        if p:
            project_id = p.get("project_id") or project_id
            customer_id = p.get("customer_id") or customer_id

    cs_number = await next_cs_number()
    cs = ComparativeStatement(
        **body.model_dump(exclude={"project_id", "customer_id"}),
        project_id=project_id or "",
        customer_id=customer_id or "",
        cs_number=cs_number,
        uploaded_by=u.user_id,
        uploaded_by_name=u.name,
        file_size=size,
    )
    doc = cs.model_dump()
    await db.comparative_statements.insert_one(dict(doc))
    await audit("comparative_statement", cs.cs_id, "upload", u,
                 {"cs_number": cs.cs_number, "record_number": cs.cs_number,
                  "old_value": None,
                  "new_value": {"mrf_id": cs.mrf_id, "po_id": cs.po_id,
                                 "title": cs.title, "file_name": cs.file_name,
                                 "l1_vendor": cs.l1_vendor,
                                 "selected_vendor": cs.selected_vendor,
                                 "size": size},
                  "reason": body.remarks or ""})
    out = await db.comparative_statements.find_one(
        {"cs_id": cs.cs_id}, {"_id": 0, "file_base64": 0}
    )
    return _strip_oids(out)


@api.get("/comparative-statement")
async def list_cs(mrf_id: Optional[str] = None,
                   po_id: Optional[str] = None,
                   project_id: Optional[str] = None,
                   customer_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    q: Dict[str, Any] = {"deleted": {"$ne": True}}
    if mrf_id: q["mrf_id"] = mrf_id
    if po_id: q["po_id"] = po_id
    if project_id: q["project_id"] = project_id
    if customer_id: q["customer_id"] = customer_id
    if u.role == "site_engineer":
        mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
            {"created_by": u.user_id}, {"_id": 0, "mrf_id": 1}).to_list(5000)]
        q["mrf_id"] = {"$in": mrf_ids}
    rows = await db.comparative_statements.find(q, {"_id": 0, "file_base64": 0}).sort("uploaded_at", -1).to_list(500)
    return rows


@api.get("/comparative-statement/{cs_id}")
async def get_cs(cs_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})
    if not cs:
        raise HTTPException(404, "CS not found")
    return cs


@api.get("/comparative-statement/{cs_id}/download")
async def download_cs(cs_id: str, token: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    """Return the original imported file as an attachment."""
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id}, {"_id": 0})
    if not cs:
        raise HTTPException(404, "CS not found")
    b64 = cs.get("file_base64") or ""
    if not b64:
        raise HTTPException(404, "No file attached to this CS")
    try:
        raw = _b64.b64decode((b64.split(",", 1)[-1]).encode("utf-8"), validate=False)
    except Exception:
        raise HTTPException(500, "Corrupt attachment")
    fname = cs.get("file_name") or f"{cs.get('cs_number','CS').replace('/', '_')}.bin"
    mime = cs.get("mime_type") or "application/octet-stream"
    await _log_export(u, "comparative_statement", cs_id,
                       "download", cs.get("cs_number", ""))
    return StreamingResponse(io.BytesIO(raw), media_type=mime,
                              headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.put("/comparative-statement/{cs_id}")
async def update_cs(cs_id: str, body: Dict[str, Any] = Body(...),
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_UPLOAD:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})
    if not cs:
        raise HTTPException(404, "CS not found")
    if cs.get("status") == "approved" and u.role not in ("admin", "director"):
        raise HTTPException(400, "CS is approved and locked")
    ALLOWED = {"title", "remarks", "vendors", "l1_vendor", "l1_amount",
               "selected_vendor", "selection_reason"}
    updates = {k: v for k, v in body.items() if k in ALLOWED}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    old_snap = {k: cs.get(k) for k in updates.keys()}
    await db.comparative_statements.update_one({"cs_id": cs_id}, {"$set": updates})
    await audit("comparative_statement", cs_id, "edit", u,
                 {"cs_number": cs.get("cs_number"),
                  "old_value": old_snap,
                  "new_value": updates,
                  "reason": body.get("reason") or ""})
    return await db.comparative_statements.find_one({"cs_id": cs_id},
                                                      {"_id": 0, "file_base64": 0})


@api.post("/comparative-statement/{cs_id}/approve")
async def approve_cs(cs_id: str, body: Dict[str, Any] = Body(default={}),
                      authorization: Optional[str] = Header(None)):
    """PM/GM/Director approves or rejects a Comparative Statement."""
    u = await get_current_user(authorization)
    if u.role not in CS_APPROVER_ROLES:
        raise HTTPException(403, "Only pm/gm/director can approve Comparative Statement")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})
    if not cs:
        raise HTTPException(404, "CS not found")
    action = (body.get("action") or "approve").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    current = cs.get("status") or "pending_approval"
    if current not in ("pending_approval", "rejected", "active"):
        raise HTTPException(400, f"Cannot {action}: CS is '{current}'")
    new_status = "approved" if action == "approve" else "rejected"
    hist = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": body.get("comment") or "",
        "timestamp": now_utc().isoformat(),
    }
    await db.comparative_statements.update_one(
        {"cs_id": cs_id},
        {"$set": {"status": new_status},
         "$push": {"approval_history": hist}},
    )
    await audit("comparative_statement", cs_id, f"cs_{action}", u,
                 {"cs_number": cs.get("cs_number"),
                  "record_number": cs.get("cs_number"),
                  "old_value": {"status": current},
                  "new_value": {"status": new_status},
                  "reason": body.get("comment") or ""})
    return await db.comparative_statements.find_one({"cs_id": cs_id},
                                                      {"_id": 0, "file_base64": 0})


@api.delete("/comparative-statement/{cs_id}")
async def delete_cs(cs_id: str, reason: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can delete CS")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})
    if not cs:
        raise HTTPException(404, "CS not found")
    await db.comparative_statements.update_one({"cs_id": cs_id},
                                                 {"$set": {"deleted": True,
                                                            "status": "cancelled"}})
    await audit("comparative_statement", cs_id, "delete", u,
                 {"cs_number": cs.get("cs_number"),
                  "old_value": {"status": cs.get("status"), "deleted": False},
                  "new_value": {"status": "cancelled", "deleted": True},
                  "reason": reason or ""})
    return {"ok": True}
