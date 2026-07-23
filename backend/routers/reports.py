"""Reports & dashboards router — extracted from server.py in Phase 9C.

Houses: /reports/dashboard, /reports/mrf-ageing, /reports/grn-variance.
Read-only — no writes, no audit rows produced here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set
from fastapi import Header

from server import api, db, get_current_user, now_utc

# SEC hardening: dashboard/report scope by role. Management sees all;
# PM sees their projects; site_engineer sees MRFs they created; store
# sees MRFs they raised or received.
_MGMT_ROLES = {"admin", "director", "gm", "purchase"}


async def _scoped_mrf_po_ids(user_id: str, role: str) -> Optional[Dict[str, Set[str]]]:
    """Return None for management (no filter). Otherwise return the caller's
    reachable mrf_ids / po_ids as sets — used to filter mrfs/pos lists."""
    if role in _MGMT_ROLES:
        return None
    mrf_ids: Set[str] = set()
    po_ids: Set[str] = set()
    if role == "pm":
        prjs = await db.projects.find(
            {"project_managers": user_id}, {"_id": 0, "project_id": 1}
        ).to_list(500)
        proj_ids = [p["project_id"] for p in prjs]
        if proj_ids:
            mrfs = await db.mrfs.find(
                {"project_id": {"$in": proj_ids}, "deleted": False},
                {"_id": 0, "mrf_id": 1},
            ).to_list(5000)
            mrf_ids = {m["mrf_id"] for m in mrfs}
            pos = await db.pos.find(
                {"project_id": {"$in": proj_ids}, "deleted": False},
                {"_id": 0, "po_id": 1},
            ).to_list(5000)
            po_ids = {p["po_id"] for p in pos}
    elif role == "site_engineer":
        mrfs = await db.mrfs.find(
            {"created_by": user_id, "deleted": False},
            {"_id": 0, "mrf_id": 1},
        ).to_list(5000)
        mrf_ids = {m["mrf_id"] for m in mrfs}
        if mrf_ids:
            pos = await db.pos.find(
                {"mrf_refs": {"$in": list(mrf_ids)}, "deleted": False},
                {"_id": 0, "po_id": 1},
            ).to_list(5000)
            po_ids = {p["po_id"] for p in pos}
    elif role == "store":
        mrfs = await db.mrfs.find(
            {"created_by": user_id, "deleted": False},
            {"_id": 0, "mrf_id": 1},
        ).to_list(5000)
        mrf_ids = {m["mrf_id"] for m in mrfs}
        # Store also sees PO events for POs that reference "their" MRFs
        if mrf_ids:
            pos = await db.pos.find(
                {"mrf_refs": {"$in": list(mrf_ids)}, "deleted": False},
                {"_id": 0, "po_id": 1},
            ).to_list(5000)
            po_ids = {p["po_id"] for p in pos}
    return {"mrf_ids": mrf_ids, "po_ids": po_ids}


@api.get("/reports/dashboard")
async def dashboard(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    scope = await _scoped_mrf_po_ids(u.user_id, u.role)
    mrf_q: Dict[str, Any] = {"deleted": False}
    po_q: Dict[str, Any] = {"deleted": False}
    if scope is not None:
        mrf_q["mrf_id"] = {"$in": list(scope["mrf_ids"])} if scope["mrf_ids"] else "__none__"
        po_q["po_id"] = {"$in": list(scope["po_ids"])} if scope["po_ids"] else "__none__"
    mrfs = await db.mrfs.find(mrf_q, {"_id": 0}).to_list(5000) if mrf_q.get("mrf_id") != "__none__" else []
    pos = await db.pos.find(po_q, {"_id": 0}).to_list(5000) if po_q.get("po_id") != "__none__" else []
    total_mrf = len(mrfs)
    pending_pm = sum(1 for m in mrfs if m["status"] in ["pm_review", "submitted"])
    pending_purchase = sum(1 for m in mrfs if m["status"] in
                             ["approved", "sent_to_purchase", "partially_ordered"])
    approved = sum(1 for m in mrfs if m["status"] == "approved")
    total_po = len(pos)
    po_value = sum(p.get("total", 0) for p in pos)

    billable_value = 0
    non_billable_value = 0
    pending_billing_count = 0
    fully_billed_count = 0
    for m in mrfs:
        for it in m["items"]:
            if it.get("billable", True):
                billable_value += (it.get("qty_approved") or 0)
                if it.get("billing_status") in ["not_billed", "partially_billed"]:
                    pending_billing_count += 1
                if it.get("billing_status") == "fully_billed":
                    fully_billed_count += 1
            else:
                non_billable_value += (it.get("qty_approved") or 0)

    now = now_utc()
    ageing_buckets = {"0-3": 0, "4-7": 0, "8-15": 0, "16+": 0}
    for m in mrfs:
        if m["status"] in ["approved", "closed", "received", "fully_ordered"]:
            continue
        created = m["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = (now - created).days
        if days <= 3:
            ageing_buckets["0-3"] += 1
        elif days <= 7:
            ageing_buckets["4-7"] += 1
        elif days <= 15:
            ageing_buckets["8-15"] += 1
        else:
            ageing_buckets["16+"] += 1

    return {
        "total_mrf": total_mrf,
        "pending_pm": pending_pm,
        "pending_purchase": pending_purchase,
        "approved": approved,
        "total_po": total_po,
        "po_value": round(po_value, 2),
        "billable_value": billable_value,
        "non_billable_value": non_billable_value,
        "pending_billing_count": pending_billing_count,
        "fully_billed_count": fully_billed_count,
        "ageing": ageing_buckets,
    }


@api.get("/reports/mrf-ageing")
async def mrf_ageing(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    scope = await _scoped_mrf_po_ids(u.user_id, u.role)
    mrf_q: Dict[str, Any] = {"deleted": False}
    if scope is not None:
        mrf_q["mrf_id"] = {"$in": list(scope["mrf_ids"])} if scope["mrf_ids"] else "__none__"
        if mrf_q["mrf_id"] == "__none__":
            return []
    mrfs = await db.mrfs.find(mrf_q, {"_id": 0}).to_list(5000)
    now = now_utc()
    out = []
    for m in mrfs:
        if m["status"] in ["closed", "received"]:
            continue
        created = m["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = (now - created).days
        out.append({
            "mrf_id": m["mrf_id"], "mrf_number": m["mrf_number"],
            "status": m["status"], "days": days,
            "project_id": m["project_id"], "site": m["site"],
        })
    out.sort(key=lambda x: -x["days"])
    return out


@api.get("/reports/grn-variance")
async def grn_variance(project_id: Optional[str] = None,
                        vendor_id: Optional[str] = None,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    if vendor_id:
        q["vendor_id"] = vendor_id
    scope = await _scoped_mrf_po_ids(u.user_id, u.role)
    if scope is not None:
        if not scope["po_ids"]:
            return []
        q["po_id"] = {"$in": list(scope["po_ids"])}
    pos = await db.pos.find(q, {"_id": 0}).to_list(5000)
    inv_totals: Dict[str, float] = {}
    inv_docs = await db.invoices.find({}, {"_id": 0}).to_list(2000)
    for iv in inv_docs:
        inv_totals[iv["po_id"]] = inv_totals.get(iv["po_id"], 0) + float(iv.get("total") or 0)
    out = []
    for p in pos:
        po_val_ord = 0.0
        po_val_recv = 0.0
        short_lines = 0
        line_count = len(p.get("items", []))
        for it in p.get("items", []):
            qty = float(it.get("qty") or 0)
            recv = float(it.get("qty_received") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst = float(it.get("gst") or 0)
            ord_val = qty * rate - disc
            ord_val = ord_val + ord_val * gst / 100
            recv_val = 0.0
            if qty > 0:
                recv_val = ord_val * (recv / qty)
            po_val_ord += ord_val
            po_val_recv += recv_val
            if recv < qty:
                short_lines += 1
        po_val_ord += float(p.get("freight") or 0) + float(p.get("other_charges") or 0)
        po_val_recv += float(p.get("freight") or 0) + float(p.get("other_charges") or 0) if p.get("status") == "received" else 0
        inv_total = inv_totals.get(p["po_id"], 0)
        variance = round(po_val_ord - po_val_recv, 2)
        invoice_variance = round(inv_total - po_val_recv, 2)
        out.append({
            "po_id": p["po_id"],
            "po_number": p["po_number"],
            "date": p["date"].strftime("%Y-%m-%d") if isinstance(p["date"], datetime) else str(p["date"]),
            "vendor_id": p.get("vendor_id"),
            "project_id": p.get("project_id"),
            "status": p.get("status", "issued"),
            "line_count": line_count,
            "short_lines": short_lines,
            "value_ordered": round(po_val_ord, 2),
            "value_received": round(po_val_recv, 2),
            "variance": variance,
            "invoice_total": round(inv_total, 2),
            "invoice_variance": invoice_variance,
        })
    out.sort(key=lambda r: (-abs(r["variance"]), r["po_number"]))
    return out
