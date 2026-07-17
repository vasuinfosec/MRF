"""PO (Purchase Order) lifecycle router — extracted from server.py in Phase 9C round 4.

Handles the PO lifecycle: create, threshold-based approval, list, get, mark
received (with auto-GRN creation), and list attached invoices.

PO PDF / Excel / Tally exports remain in `server.py` for now (very large layout
code + shared workbook helpers `_po_excel_workbook`, `_po_tally_workbook`) —
they will be extracted in a later round.
"""
from __future__ import annotations

from typing import Optional, Dict, Any, List
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, audit, notify, now_utc, gid,
    _check_po_access,
    get_thresholds, _po_initial_status,
    next_po_number, next_grn_number,
    POCreate, PO,
    GRN_ROLES,
)


# ---------------------- Create PO ----------------------
@api.post("/po")
async def create_po(body: POCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only purchase/admin/director can create POs")

    mrf_refs = set()
    total = 0.0
    for it in body.items:
        mrf_refs.add(it.mrf_id)
        mrf = await db.mrfs.find_one({"mrf_id": it.mrf_id}, {"_id": 0})
        if not mrf:
            raise HTTPException(400, f"MRF {it.mrf_id} not found")
        if mrf["status"] not in ["approved", "sent_to_purchase", "partially_ordered"]:
            raise HTTPException(400, f"MRF {mrf['mrf_number']} not in purchasable state")
        for mi in mrf["items"]:
            if mi["item_line_id"] == it.item_line_id:
                if mi["status"] == "rejected":
                    raise HTTPException(400, f"Item {mi['description']} is rejected")
        gross = it.qty * it.rate
        after_disc = gross - it.discount
        gst_amt = after_disc * it.gst / 100
        total += after_disc + gst_amt
    total += body.freight + body.other_charges

    thresholds = await get_thresholds()
    initial_status = _po_initial_status(total, thresholds["gm"], thresholds["director"])

    proj = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
    cust_id = (proj or {}).get("customer_id")
    cust_name = ""
    if cust_id:
        c = await db.customers.find_one({"customer_id": cust_id},
                                          {"_id": 0, "name": 1})
        cust_name = (c or {}).get("name") or ""
    if not cust_name:
        cust_name = (proj or {}).get("client") or ""

    po = PO(
        po_number=await next_po_number(),
        vendor_id=body.vendor_id,
        project_id=body.project_id,
        delivery_site=body.delivery_site,
        items=body.items,
        delivery_schedule=body.delivery_schedule,
        payment_terms=body.payment_terms,
        warranty_terms=body.warranty_terms,
        freight=body.freight,
        other_charges=body.other_charges,
        authorised_signatory=body.authorised_signatory,
        vendor_quotation=body.vendor_quotation,
        mrf_refs=list(mrf_refs),
        total=round(total, 2),
        customer_id=cust_id,
        customer_name=cust_name,
        created_by=u.user_id,
    )
    po_doc = po.model_dump()
    po_doc["status"] = initial_status
    po_doc["items"] = [i.model_dump() if hasattr(i, "model_dump") else i
                       for i in body.items]
    po_doc["approval_history"] = []
    po_doc["thresholds_applied"] = {"gm": thresholds["gm"],
                                     "director": thresholds["director"]}
    await db.pos.insert_one(po_doc)

    # If auto-approved (issued), roll MRF qty_ordered forward
    if initial_status == "issued":
        for it in body.items:
            mrf = await db.mrfs.find_one({"mrf_id": it.mrf_id}, {"_id": 0})
            items = mrf["items"]
            for mi in items:
                if mi["item_line_id"] == it.item_line_id:
                    mi["qty_ordered"] = (mi.get("qty_ordered") or 0) + it.qty
            all_ordered = all(
                (mi.get("qty_ordered") or 0) >= (mi.get("qty_approved") or 0)
                for mi in items if mi["status"] != "rejected"
            )
            any_ordered = any((mi.get("qty_ordered") or 0) > 0 for mi in items)
            new_status = "fully_ordered" if all_ordered else (
                "partially_ordered" if any_ordered else mrf["status"])
            await db.mrfs.update_one(
                {"mrf_id": it.mrf_id},
                {"$set": {"items": items, "status": new_status,
                          "updated_at": now_utc()}},
            )

    if initial_status == "pending_gm_approval":
        approvers = await db.users.find({"role": {"$in": ["gm", "director"]}},
                                          {"_id": 0, "user_id": 1}).to_list(50)
        await notify([a["user_id"] for a in approvers], "PO pending GM approval",
                       f"{po.po_number} (₹{total:,.2f}) awaits GM approval",
                       f"/po/{po.po_id}")
    elif initial_status == "pending_director_approval":
        approvers = await db.users.find({"role": "director"},
                                          {"_id": 0, "user_id": 1}).to_list(50)
        await notify([a["user_id"] for a in approvers],
                       "PO pending Director approval",
                       f"{po.po_number} (₹{total:,.2f}) awaits Director approval",
                       f"/po/{po.po_id}")

    await audit("po", po.po_id, "create", u,
                 {"po_number": po.po_number,
                  "old_value": None,
                  "new_value": {"total": total, "status": initial_status,
                                 "vendor_id": po_doc.get("vendor_id"),
                                 "customer_id": cust_id,
                                 "project_id": po_doc.get("project_id"),
                                 "item_count": len(po_doc.get("items") or [])},
                  "total": total,
                  "initial_status": initial_status})
    po_doc.pop("_id", None)
    return po_doc


# ---------------------- Approve/reject PO ----------------------
@api.post("/po/{po_id}/approve")
async def approve_po(po_id: str, body: Optional[dict] = None,
                       authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("gm", "director", "admin"):
        raise HTTPException(403, "Only GM/Director/Admin can approve POs")
    body = body or {}
    action = (body.get("action") or "approve").lower()
    comment = body.get("comment") or ""
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    cur = po.get("status", "issued")
    if cur not in ("pending_gm_approval", "pending_director_approval"):
        raise HTTPException(400, f"PO is not awaiting approval (status={cur})")
    if cur == "pending_director_approval" and u.role == "gm":
        raise HTTPException(403, "This PO exceeds GM threshold — Director approval required")

    new_status = "rejected" if action == "reject" else "issued"
    hist_entry = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": comment, "timestamp": now_utc().isoformat(),
    }
    await db.pos.update_one(
        {"po_id": po_id},
        {"$set": {"status": new_status},
         "$push": {"approval_history": hist_entry}},
    )

    if new_status == "issued":
        for it in po.get("items", []):
            mrf = await db.mrfs.find_one({"mrf_id": it.get("mrf_id")}, {"_id": 0})
            if not mrf:
                continue
            items = mrf["items"]
            for mi in items:
                if mi["item_line_id"] == it.get("item_line_id"):
                    mi["qty_ordered"] = (mi.get("qty_ordered") or 0) + float(it.get("qty") or 0)
            all_ordered = all(
                (mi.get("qty_ordered") or 0) >= (mi.get("qty_approved") or 0)
                for mi in items if mi["status"] != "rejected"
            )
            any_ordered = any((mi.get("qty_ordered") or 0) > 0 for mi in items)
            mrf_new = "fully_ordered" if all_ordered else (
                "partially_ordered" if any_ordered else mrf["status"])
            await db.mrfs.update_one(
                {"mrf_id": mrf["mrf_id"]},
                {"$set": {"items": items, "status": mrf_new,
                          "updated_at": now_utc()}},
            )

    await audit("po", po_id, f"po_{action}", u,
                 {"comment": comment, "old_value": {"status": cur},
                  "new_value": {"status": new_status},
                  "reason": comment,
                  "po_number": po.get("po_number")})
    creator = po.get("created_by")
    if creator:
        await notify([creator], f"PO {new_status}",
                       f"{po['po_number']} was {action}d by {u.name}", f"/po/{po_id}")
    return {"ok": True, "status": new_status}


# ---------------------- List / get ----------------------
@api.get("/po")
async def list_pos(project_id: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    docs = await db.pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    if u.role in ("admin", "purchase", "gm", "director"):
        return docs
    if u.role == "pm":
        prjs = await db.projects.find({"project_managers": u.user_id},
                                        {"_id": 0, "project_id": 1}).to_list(500)
        allowed = {p["project_id"] for p in prjs}
        return [p for p in docs if p.get("project_id") in allowed]
    if u.role == "site_engineer":
        my = await db.mrfs.find({"created_by": u.user_id},
                                  {"_id": 0, "mrf_id": 1}).to_list(2000)
        my_ids = {m["mrf_id"] for m in my}
        return [p for p in docs if my_ids.intersection(p.get("mrf_refs") or [])]
    if u.role == "store":
        prjs = await db.projects.find(
            {"$or": [
                {"site_engineers": u.user_id},
                {"sites.site_engineers": u.user_id},
            ]}, {"_id": 0, "project_id": 1}).to_list(500)
        allowed = {p["project_id"] for p in prjs}
        return [p for p in docs if p.get("project_id") in allowed]
    return []


@api.get("/po/{po_id}")
async def get_po(po_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    d = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, d)
    return d


# ---------------------- Mark received (auto-GRN) ----------------------
@api.post("/po/{po_id}/received")
async def mark_po_received(po_id: str, body: dict,
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in GRN_ROLES:
        raise HTTPException(403,
            "Only site engineer/store/purchase/PM/director/admin can record receipt")
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    if po.get("status") in ("pending_gm_approval", "pending_director_approval", "rejected"):
        raise HTTPException(400, f"PO not yet approved (status={po.get('status')})")
    await _check_po_access(u, po)

    per_line: Dict[Any, float] = {}
    if body and isinstance(body.get("items"), list):
        for row in body["items"]:
            key = (row.get("mrf_id"), row.get("item_line_id"))
            try:
                per_line[key] = float(row.get("qty") or 0)
            except (TypeError, ValueError):
                per_line[key] = 0

    po_items = po["items"]
    any_received = False
    grn_items: List[Dict[str, Any]] = []
    for pit in po_items:
        prev = float(pit.get("qty_received") or 0)
        ordered = float(pit.get("qty") or 0)
        remaining = max(ordered - prev, 0)
        if per_line:
            receive_now = per_line.get((pit["mrf_id"], pit["item_line_id"]), 0)
        else:
            receive_now = remaining
        receive_now = max(0.0, min(receive_now, remaining))
        if receive_now <= 0:
            continue
        pit["qty_received"] = prev + receive_now
        pit.setdefault("receipts", []).append({
            "date": now_utc().isoformat(),
            "qty": receive_now,
            "user_id": u.user_id,
            "user_name": u.name,
        })
        any_received = True
        grn_items.append({
            "mrf_id": pit["mrf_id"],
            "item_line_id": pit["item_line_id"],
            "description": pit.get("description", ""),
            "unit": pit.get("unit", ""),
            "qty": receive_now,
        })

        mrf = await db.mrfs.find_one({"mrf_id": pit["mrf_id"]}, {"_id": 0})
        if not mrf:
            continue
        items = mrf["items"]
        for mi in items:
            if mi["item_line_id"] == pit["item_line_id"]:
                mi["qty_received"] = (mi.get("qty_received") or 0) + receive_now
        all_recv = all(
            (mi.get("qty_received") or 0) >= (mi.get("qty_approved") or 0)
            for mi in items if mi["status"] != "rejected"
        )
        await db.mrfs.update_one(
            {"mrf_id": pit["mrf_id"]},
            {"$set": {"items": items,
                      "status": "received" if all_recv else mrf["status"],
                      "updated_at": now_utc()}},
        )

    fully = all(
        float(pi.get("qty_received") or 0) >= float(pi.get("qty") or 0)
        for pi in po_items
    )
    new_status = "received" if fully else (
        "partially_received" if any_received else po.get("status", "issued"))
    await db.pos.update_one(
        {"po_id": po_id},
        {"$set": {"items": po_items, "status": new_status}},
    )

    grn_id = None
    grn_number = None
    if grn_items:
        grn_id = gid("grn")
        grn_number = await next_grn_number()
        await db.grns.insert_one({
            "grn_id": grn_id,
            "grn_number": grn_number,
            "po_id": po_id,
            "po_number": po["po_number"],
            "mrf_refs": po.get("mrf_refs", []),
            "vendor_id": po.get("vendor_id"),
            "project_id": po.get("project_id"),
            "customer_id": po.get("customer_id"),
            "date": now_utc(),
            "items": grn_items,
            "received_by": u.user_id,
            "received_by_name": u.name,
            "remarks": (body or {}).get("remarks", ""),
            "status": "pending_approval",
            "approval_history": [],
        })
        await audit("grn", grn_id, "create", u,
                     {"grn_number": grn_number,
                      "old_value": None,
                      "new_value": {"status": "pending_approval",
                                     "po_number": po["po_number"],
                                     "item_count": len(grn_items)},
                      "record_number": grn_number,
                      "reason": (body or {}).get("remarks", "")})

    await audit("po", po_id, "received", u,
                 {"old_value": {"status": po.get("status")},
                  "new_value": {"status": new_status},
                  "grn_number": grn_number,
                  "per_line": grn_items,
                  "po_number": po.get("po_number"),
                  "reason": (body or {}).get("remarks", "")})
    return {"ok": True, "status": new_status, "grn_id": grn_id,
            "grn_number": grn_number}


# ---------------------- Invoices attached to a PO ----------------------
@api.get("/po/{po_id}/invoices")
async def list_po_invoices(po_id: str,
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    return await db.invoices.find({"po_id": po_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
