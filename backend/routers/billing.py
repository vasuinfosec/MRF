"""Billing router — extracted from server.py in Phase 9C round 5 (Batch C).

Exposes /api/billing/items (aggregated line-item roll-up across MRFs) and
/api/billing/update (per-line billing state mutation with auto-computed
billing_status). Restricted to purchase/admin/director.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, audit, now_utc,
    BillingUpdate,
)


@api.get("/billing/items")
async def billing_items(
    filter: Optional[str] = None,  # not_billed / partially_billed / fully_billed / non_billable
    project_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only purchase/director/admin")
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    mrfs = await db.mrfs.find(q, {"_id": 0}).to_list(500)
    out = []
    for m in mrfs:
        for it in m["items"]:
            if it["status"] == "rejected":
                continue
            bstat = it.get("billing_status", "not_billed")
            if filter and bstat != filter:
                continue
            out.append({
                "mrf_id": m["mrf_id"], "mrf_number": m["mrf_number"],
                "project_id": m["project_id"], "site": m["site"],
                "item_line_id": it["item_line_id"], "description": it["description"],
                "unit": it["unit"], "qty_approved": it.get("qty_approved") or 0,
                "qty_received": it.get("qty_received") or 0,
                "qty_issued": it.get("qty_issued") or 0,
                "qty_billed": it.get("qty_billed") or 0,
                "billing_status": bstat, "billable": it.get("billable", True),
                "client_bill_ref": it.get("client_bill_ref", ""),
                "ra_bill_no": it.get("ra_bill_no", ""),
                "billing_date": it.get("billing_date", ""),
            })
    return out


@api.post("/billing/update")
async def update_billing(body: BillingUpdate,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only billing/admin")
    mrf = await db.mrfs.find_one({"mrf_id": body.mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    items = mrf["items"]
    for it in items:
        if it["item_line_id"] == body.item_line_id:
            if body.qty_received is not None:
                it["qty_received"] = body.qty_received
            if body.qty_issued is not None:
                it["qty_issued"] = body.qty_issued
            if body.qty_billed is not None:
                it["qty_billed"] = body.qty_billed
            if body.client_bill_ref is not None:
                it["client_bill_ref"] = body.client_bill_ref
            if body.ra_bill_no is not None:
                it["ra_bill_no"] = body.ra_bill_no
            if body.billing_date is not None:
                it["billing_date"] = body.billing_date
            if body.billing_remarks is not None:
                it["billing_remarks"] = body.billing_remarks
            # Auto-compute billing status
            new_bstat = it.get("billing_status", "not_billed")
            if body.billing_status:
                if body.billing_status == "fully_billed":
                    qa = it.get("qty_approved") or 0
                    qr = it.get("qty_received") or qa
                    qb = it.get("qty_billed") or 0
                    if qb < qr and not body.override_reason:
                        raise HTTPException(400,
                            "Cannot mark fully billed: billed < received. "
                            "Provide override_reason.")
                new_bstat = body.billing_status
            else:
                qa = it.get("qty_approved") or 0
                qb = it.get("qty_billed") or 0
                if not it.get("billable", True):
                    new_bstat = "non_billable"
                elif qb <= 0:
                    new_bstat = "not_billed"
                elif qb >= qa:
                    new_bstat = "fully_billed"
                else:
                    new_bstat = "partially_billed"
            it["billing_status"] = new_bstat
    await db.mrfs.update_one({"mrf_id": body.mrf_id},
                               {"$set": {"items": items, "updated_at": now_utc()}})
    await audit("billing", body.item_line_id, "update", u,
                 body.model_dump(exclude_none=True))
    return {"ok": True}
