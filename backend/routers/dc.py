"""Delivery Challan (DC) router — extracted from server.py in Phase 9C round 4.

Handles the full DC lifecycle: create, list, view, update, approve/reject,
cancel, PDF & Excel exports, plus the bulk /export/dc endpoint.
DC-specific access helper `_check_dc_access` lives here (only DC routes use it).
"""
from __future__ import annotations

import io
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, Body
from fastapi.responses import StreamingResponse

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from server import (
    api, db, get_current_user, audit, now_utc,
    _validation_error, _log_export, _vasu_footer, _excel_response,
    _validate_dc_for_export, _dc_pdf_story, _dc_excel_workbook,
    next_dc_number,
    DCCreate, DC, UserOut,
    DC_ROLES, DC_APPROVER_ROLES,
    bearer_from_url_token,
)


# ---------------------- DC access helper ----------------------
async def _check_dc_access(u: UserOut, dc: dict) -> None:
    """Project-scoped for pm/site_engineer; open for purchase/store/director/admin/gm."""
    if u.role in ("director", "admin", "purchase", "gm"):
        return
    if u.role == "store":
        return
    if u.role == "pm":
        proj = await db.projects.find_one({"project_id": dc.get("project_id")},
                                            {"_id": 0, "project_managers": 1})
        if proj and u.user_id in (proj.get("project_managers") or []):
            return
    if u.role == "site_engineer":
        proj = await db.projects.find_one({"project_id": dc.get("project_id")},
                                            {"_id": 0, "site_engineers": 1})
        if proj and u.user_id in (proj.get("site_engineers") or []):
            return
    raise HTTPException(403, "Not authorised for this DC")


# ---------------------- DC lifecycle ----------------------
@api.post("/dc")
async def create_dc(body: DCCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in DC_ROLES:
        raise HTTPException(403, "Not allowed to create DC")
    if not body.items:
        raise HTTPException(400, "At least one line item required")
    proj = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
    if not proj:
        raise HTTPException(404, "Project not found")
    if u.role == "pm" and u.user_id not in (proj.get("project_managers") or []):
        raise HTTPException(403, "Not a PM for this project")
    if u.role == "site_engineer" and u.user_id not in (proj.get("site_engineers") or []):
        raise HTTPException(403, "Not a Site Engineer for this project")

    cust_name = ""
    if body.customer_id:
        c = await db.customers.find_one({"customer_id": body.customer_id},
                                          {"_id": 0, "name": 1})
        if c:
            cust_name = c.get("name") or ""
    vend_name = ""
    if body.vendor_id:
        v = await db.vendors.find_one({"vendor_id": body.vendor_id},
                                        {"_id": 0, "name": 1})
        if v:
            vend_name = v.get("name") or ""
    dc_number = await next_dc_number()
    dc = DC(
        **body.model_dump(),
        dc_number=dc_number,
        customer_name=cust_name,
        vendor_name=vend_name,
        created_by=u.user_id,
    )
    await db.dcs.insert_one(dc.model_dump())
    await audit("dc", dc.dc_id, "create", u,
                 {"dc_number": dc.dc_number,
                  "old_value": None,
                  "new_value": {"status": dc.status, "dc_type": dc.dc_type,
                                 "item_count": len(dc.items),
                                 "project_id": dc.project_id,
                                 "from_location": dc.from_location,
                                 "to_location": dc.to_location}})
    return await db.dcs.find_one({"dc_id": dc.dc_id}, {"_id": 0})


@api.get("/dc")
async def list_dcs(project_id: Optional[str] = None,
                     status: Optional[str] = None,
                     dc_type: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": {"$ne": True}}
    if project_id: q["project_id"] = project_id
    if status: q["status"] = status
    if dc_type: q["dc_type"] = dc_type
    if u.role == "pm":
        prjs = await db.projects.find({"project_managers": u.user_id},
                                        {"_id": 0, "project_id": 1}).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    elif u.role == "site_engineer":
        prjs = await db.projects.find({"site_engineers": u.user_id},
                                        {"_id": 0, "project_id": 1}).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    return await db.dcs.find(q, {"_id": 0}).sort("date", -1).to_list(500)


@api.get("/dc/{dc_id}")
async def get_dc(dc_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    return dc


@api.put("/dc/{dc_id}")
async def update_dc(dc_id: str, body: Dict[str, Any] = Body(...),
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    if u.role not in DC_ROLES:
        raise HTTPException(403, "Not allowed")
    if dc.get("status") == "approved" and u.role not in ("admin", "director"):
        raise HTTPException(400, "DC is approved and locked; only admin/director can override")
    ALLOWED = {
        "status", "dispatch_date", "vehicle_no", "driver_name", "driver_contact",
        "transporter", "e_way_bill_no", "e_way_bill_date", "remarks",
        "authorised_signatory", "items", "from_location", "to_location", "vendor_dc_ref",
    }
    updates = {k: v for k, v in body.items() if k in ALLOWED and k != "reason"}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    if "status" in updates and updates["status"] in ("approved", "rejected", "cancelled"):
        if u.role not in ("admin", "director"):
            raise HTTPException(403, "Use /approve or /cancel to change protected status")
    old_snap = {k: dc.get(k) for k in updates.keys()}
    updates["updated_at"] = now_utc()
    await db.dcs.update_one({"dc_id": dc_id}, {"$set": updates})
    await audit("dc", dc_id, "edit", u,
                 {"dc_number": dc.get("dc_number"),
                  "old_value": old_snap,
                  "new_value": {k: v for k, v in updates.items() if k != "updated_at"},
                  "reason": body.get("reason") or ""})
    return await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})


@api.post("/dc/{dc_id}/approve")
async def approve_dc(dc_id: str, body: Dict[str, Any] = Body(default={}),
                      authorization: Optional[str] = Header(None)):
    """Admin/Accounts (or Director) approves or rejects a Delivery Challan."""
    u = await get_current_user(authorization)
    if u.role not in DC_APPROVER_ROLES:
        raise HTTPException(403, "Only admin/accounts or director can approve DC")
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    action = (body.get("action") or "approve").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    if dc.get("status") not in ("pending_approval", "rejected", "issued"):
        raise HTTPException(400, f"Cannot {action}: DC is '{dc.get('status')}'")
    new_status = "approved" if action == "approve" else "rejected"
    hist = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": body.get("comment") or "",
        "timestamp": now_utc().isoformat(),
    }
    await db.dcs.update_one(
        {"dc_id": dc_id},
        {"$set": {"status": new_status, "updated_at": now_utc()},
         "$push": {"approval_history": hist}},
    )
    await audit("dc", dc_id, f"dc_{action}", u,
                 {"dc_number": dc.get("dc_number"),
                  "record_number": dc.get("dc_number"),
                  "old_value": {"status": dc.get("status")},
                  "new_value": {"status": new_status},
                  "reason": body.get("comment") or ""})
    return await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})


@api.delete("/dc/{dc_id}")
async def delete_dc(dc_id: str, reason: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can cancel DC")
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    await db.dcs.update_one({"dc_id": dc_id},
                              {"$set": {"deleted": True, "status": "cancelled"}})
    await audit("dc", dc_id, "cancel", u,
                 {"dc_number": dc.get("dc_number"),
                  "old_value": {"status": dc.get("status")},
                  "new_value": {"status": "cancelled"},
                  "reason": reason or ""})
    return {"ok": True}


# ---------------------- DC exports ----------------------
@api.get("/dc/{dc_id}/pdf")
async def dc_pdf(dc_id: str, token: Optional[str] = None,
                  force: Optional[int] = 0,
                  authorization: Optional[str] = Header(None)):
    auth = authorization or bearer_from_url_token(token)
    u = await get_current_user(auth)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    project = await db.projects.find_one({"project_id": dc["project_id"]}, {"_id": 0}) or {}
    cust = await db.customers.find_one({"customer_id": dc.get("customer_id")},
                                         {"_id": 0}) if dc.get("customer_id") else None
    vend = await db.vendors.find_one({"vendor_id": dc.get("vendor_id")},
                                        {"_id": 0}) if dc.get("vendor_id") else None
    missing, warnings = _validate_dc_for_export(dc, project, "pdf")
    if missing and not force:
        raise _validation_error(missing, warnings, "pdf")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                              leftMargin=15*mm, rightMargin=15*mm)
    doc.build(_dc_pdf_story(dc, project, cust, vend),
                onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    await _log_export(u, "dc", dc_id, "pdf", dc["dc_number"],
                        {"warnings": warnings, "forced": bool(force and missing)})
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{dc["dc_number"].replace("/", "_")}.pdf"'},
    )


@api.get("/dc/{dc_id}/export")
async def dc_export_dispatch(dc_id: str,
                              format: str = "pdf",
                              force: Optional[int] = 0,
                              token: Optional[str] = None,
                              authorization: Optional[str] = Header(None)):
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "excel"):
        raise HTTPException(400, "format must be 'pdf' or 'excel'")
    auth = authorization or bearer_from_url_token(token)
    u = await get_current_user(auth)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc:
        raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    if fmt == "pdf":
        return await dc_pdf(dc_id, token=token, force=force, authorization=authorization)
    project = await db.projects.find_one({"project_id": dc["project_id"]}, {"_id": 0}) or {}
    missing, warnings = _validate_dc_for_export(dc, project, fmt)
    if missing and not force:
        raise _validation_error(missing, warnings, fmt)
    wb = await _dc_excel_workbook([dc])
    await _log_export(u, "dc", dc_id, "excel", dc["dc_number"],
                        {"warnings": warnings, "forced": bool(force and missing)})
    return _excel_response(wb, f"{dc['dc_number'].replace('/', '_')}_details.xlsx")


@api.get("/export/dc")
async def export_dc(token: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    auth = authorization or bearer_from_url_token(token)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "pm", "gm", "store"):
        raise HTTPException(403, "Not allowed")
    dcs = await db.dcs.find({"deleted": {"$ne": True}}, {"_id": 0}).sort("date", -1).to_list(2000)
    wb = await _dc_excel_workbook(dcs)
    await _log_export(u, "dc", "bulk", "excel", f"count={len(dcs)}")
    return _excel_response(wb, "dc_export.xlsx")
