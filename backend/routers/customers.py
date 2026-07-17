"""Customers router — extracted from server.py in Phase 9C round 3.

Covers /customers and the nested /customers/{cid}/pos endpoints.
Note: All Customer PO attachments are strip-encoded (base64) — the `attachment_b64`
field is redacted from list responses to keep payloads sane; a dedicated
`/attachment` endpoint returns the raw content when needed.
"""
from __future__ import annotations

import re
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, master_audit,
    Customer, CustomerPO, _validate_customer_id,
)


# ---------------------- Customers ----------------------
@api.get("/customers")
async def list_customers(include_inactive: bool = False,
                          authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    q: Dict[str, Any] = {} if include_inactive else {"active": True}
    docs = await db.customers.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    for c in docs:
        c["po_count"] = await db.customer_pos.count_documents(
            {"customer_id": c["customer_id"], "active": True}
        )
    return docs


@api.get("/customers/{customer_id}")
async def get_customer(customer_id: str,
                        authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    c = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer not found")
    c["customer_pos"] = await db.customer_pos.find(
        {"customer_id": customer_id}, {"_id": 0, "attachment_b64": 0}
    ).to_list(200)
    return c


@api.post("/customers")
async def create_customer(body: Customer,
                           authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can manage customers")
    cid = _validate_customer_id(body.customer_id)
    body.customer_id = cid
    if await db.customers.find_one({
        "customer_id": {"$regex": f"^{re.escape(cid)}$", "$options": "i"}
    }):
        raise HTTPException(400, f"Customer ID '{cid}' already exists")
    if body.name.strip() and await db.customers.find_one({
        "name": {"$regex": f"^{re.escape(body.name.strip())}$", "$options": "i"}
    }):
        raise HTTPException(
            400,
            f"Customer name '{body.name}' already exists — edit the existing record instead.",
        )
    doc = body.model_dump()
    doc["name"] = body.name.strip()
    doc["customer_id"] = cid
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("customer", cid, "create", u, "Initial creation", None, doc)
    return doc


@api.put("/customers/{customer_id}")
async def update_customer(customer_id: str, body: dict,
                           authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    existing = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Customer not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")

    # Handle Customer ID change with CASCADE update to all references.
    new_cid = body.pop("customer_id", None)
    if new_cid and new_cid != customer_id:
        new_cid = _validate_customer_id(new_cid)
        if await db.customers.find_one({
            "customer_id": {"$regex": f"^{re.escape(new_cid)}$", "$options": "i"}
        }):
            raise HTTPException(400, f"Customer ID '{new_cid}' already exists")
        await db.customers.update_one({"customer_id": customer_id},
                                        {"$set": {"customer_id": new_cid}})
        await db.customer_pos.update_many({"customer_id": customer_id},
                                            {"$set": {"customer_id": new_cid}})
        await db.projects.update_many({"customer_id": customer_id},
                                        {"$set": {"customer_id": new_cid}})
        await db.mrfs.update_many({"customer_id": customer_id},
                                    {"$set": {"customer_id": new_cid}})
        await db.pos.update_many({"customer_id": customer_id},
                                   {"$set": {"customer_id": new_cid}})
        await db.invoices.update_many({"customer_id": customer_id},
                                        {"$set": {"customer_id": new_cid}})
        await master_audit("customer", new_cid, "rename_id", u, reason,
                            {"customer_id": customer_id},
                            {"customer_id": new_cid})
        customer_id = new_cid

    updates: Dict[str, Any] = {}
    for k in ("name", "gstin", "pan", "billing_address", "shipping_address",
              "contact_person", "phone", "email", "remarks"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "active" in body:
        updates["active"] = bool(body["active"])
    if updates:
        if ("name" in updates and updates["name"]
                and updates["name"].lower() != (existing.get("name") or "").lower()):
            dup = await db.customers.find_one({
                "customer_id": {"$ne": customer_id},
                "name": {"$regex": f"^{re.escape(updates['name'])}$", "$options": "i"},
            })
            if dup:
                raise HTTPException(
                    400,
                    f"Another customer already has the name '{updates['name']}'",
                )
        await db.customers.update_one({"customer_id": customer_id}, {"$set": updates})
        old_snapshot = {k: existing.get(k) for k in updates}
        await master_audit("customer", customer_id, "update", u, reason,
                            old_snapshot, updates)
    return await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})


@api.delete("/customers/{customer_id}")
async def deactivate_customer(customer_id: str,
                                reason: str = "Deactivated by admin",
                                authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    r = await db.customers.update_one({"customer_id": customer_id},
                                        {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    await master_audit("customer", customer_id, "deactivate", u, reason,
                        {"active": True}, {"active": False})
    return {"ok": True}


# ---------------------- Customer POs (nested) ----------------------
@api.post("/customers/{customer_id}/pos")
async def add_customer_po(customer_id: str, body: CustomerPO,
                           authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "purchase"):
        raise HTTPException(403, "Not allowed")
    cust = await db.customers.find_one({"customer_id": customer_id},
                                         {"_id": 0, "customer_id": 1})
    if not cust:
        raise HTTPException(404, "Customer not found")
    body.customer_id = customer_id
    doc = body.model_dump()
    await db.customer_pos.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("customer_po", body.cpo_id, "create", u,
                        "Added customer PO", None,
                        {k: v for k, v in doc.items() if k != "attachment_b64"})
    return {k: v for k, v in doc.items() if k != "attachment_b64"}


@api.put("/customers/{customer_id}/pos/{cpo_id}")
async def update_customer_po(customer_id: str, cpo_id: str, body: dict,
                              authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "purchase"):
        raise HTTPException(403, "Not allowed")
    reason = (body.pop("reason", "") or "").strip() or "Update customer PO"
    existing = await db.customer_pos.find_one(
        {"cpo_id": cpo_id, "customer_id": customer_id}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Customer PO not found")
    updates: Dict[str, Any] = {}
    for k in ("po_number", "po_date", "validity_till", "remarks",
              "attachment_name", "attachment_b64"):
        if k in body:
            updates[k] = body[k]
    if "value" in body:
        try:
            updates["value"] = float(body["value"])
        except Exception:
            raise HTTPException(400, "Invalid value")
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.customer_pos.update_one({"cpo_id": cpo_id}, {"$set": updates})
    redacted_old = {k: (existing.get(k) if k != "attachment_b64" else "[file]")
                    for k in updates}
    redacted_new = {k: (updates.get(k) if k != "attachment_b64" else "[file]")
                    for k in updates}
    await master_audit("customer_po", cpo_id, "update", u, reason,
                        redacted_old, redacted_new)
    return await db.customer_pos.find_one({"cpo_id": cpo_id},
                                            {"_id": 0, "attachment_b64": 0})


@api.get("/customers/{customer_id}/pos/{cpo_id}/attachment")
async def get_customer_po_attachment(customer_id: str, cpo_id: str,
                                       authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    d = await db.customer_pos.find_one(
        {"cpo_id": cpo_id, "customer_id": customer_id}, {"_id": 0}
    )
    if not d or not d.get("attachment_b64"):
        raise HTTPException(404, "Attachment not found")
    return {"filename": d.get("attachment_name") or "customer_po",
            "content_b64": d["attachment_b64"]}
