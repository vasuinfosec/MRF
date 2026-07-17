"""Audit-trail router — extracted from server.py in Phase 9C.

Houses the two audit endpoints: /audit (feed) and /audit/facets (filter
options). Read-only. Access model preserved verbatim from the original
server.py implementation (see docstring on `audit_logs`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, _check_mrf_access, _check_po_access,
    _strip_oids,
)


@api.get("/audit")
async def audit_logs(entity_id: Optional[str] = None,
                     entity: Optional[str] = None,
                     action: Optional[str] = None,
                     user_id: Optional[str] = None,
                     user_role: Optional[str] = None,
                     since: Optional[str] = None,
                     limit: int = 200,
                     authorization: Optional[str] = Header(None)):
    """Unified audit trail feed.

    Access model:
    - Admin / Director / GM / Purchase: full system audit visibility.
    - PM: audits for MRFs/POs on their projects + their own actions +
      all master-data audits.
    - Site Engineer: audit for MRFs they created + PO events referring to
      those MRFs + their own actions.
    - Store: audit for MRFs they raised + GRN/received events +
      their own actions.
    """
    u = await get_current_user(authorization)
    limit = max(1, min(int(limit or 200), 500))

    if entity_id:
        # Entity-scoped audit — gated by ability to read that entity.
        if entity_id.startswith("mrf_"):
            m = await db.mrfs.find_one({"mrf_id": entity_id}, {"_id": 0})
            if not m:
                raise HTTPException(404, "MRF not found")
            await _check_mrf_access(u, m)
        elif entity_id.startswith("po_"):
            p = await db.pos.find_one({"po_id": entity_id}, {"_id": 0})
            if not p:
                raise HTTPException(404, "PO not found")
            await _check_po_access(u, p)
        else:
            # Customer / vendor / material / master audits — visible to
            # management (admin/director/gm/purchase/pm) and to the acting user.
            if u.role not in ("admin", "director", "purchase", "pm", "gm"):
                # site_engineer / store can still see logs they themselves generated
                pass

    q: Dict[str, Any] = {}
    if entity_id: q["entity_id"] = entity_id
    if entity: q["entity"] = entity
    if action: q["action"] = {"$regex": f"^{action}"}
    if user_id: q["user_id"] = user_id
    if user_role: q["user_role"] = user_role
    if since:
        try:
            dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q["timestamp"] = {"$gte": dt}
        except Exception:
            raise HTTPException(400, "since must be ISO8601")

    # Global-view RBAC scoping when NO entity_id is supplied.
    if not entity_id:
        if u.role in ("admin", "director", "gm", "purchase"):
            pass  # full access
        elif u.role == "pm":
            prjs = await db.projects.find({"project_managers": u.user_id},
                                           {"_id": 0, "project_id": 1}).to_list(500)
            proj_ids = [p["project_id"] for p in prjs]
            mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
                {"project_id": {"$in": proj_ids}},
                {"_id": 0, "mrf_id": 1}).to_list(5000)]
            po_ids = [p["po_id"] for p in await db.pos.find(
                {"project_id": {"$in": proj_ids}},
                {"_id": 0, "po_id": 1}).to_list(5000)]
            or_clauses: List[Dict[str, Any]] = [
                {"user_id": u.user_id},
                {"entity_id": {"$in": mrf_ids}} if mrf_ids else {"entity_id": "__none__"},
                {"entity_id": {"$in": po_ids}} if po_ids else {"entity_id": "__none__"},
                {"entity": {"$in": ["customer", "vendor", "project", "material",
                                       "customer_po", "master.material",
                                       "master.category", "master.department",
                                       "material.bulk_import"]}},
            ]
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        elif u.role == "site_engineer":
            mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
                {"created_by": u.user_id},
                {"_id": 0, "mrf_id": 1}).to_list(5000)]
            or_clauses = [{"user_id": u.user_id}]
            if mrf_ids:
                or_clauses.append({"entity_id": {"$in": mrf_ids}})
                po_ids = [p["po_id"] for p in await db.pos.find(
                    {"mrf_refs": {"$in": mrf_ids}},
                    {"_id": 0, "po_id": 1}).to_list(5000)]
                if po_ids:
                    or_clauses.append({"entity_id": {"$in": po_ids}})
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        elif u.role == "store":
            or_clauses = [
                {"user_id": u.user_id},
                {"action": {"$regex": "^received|^po_received|grn"}},
            ]
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        else:
            q = {"$and": [q, {"user_id": u.user_id}]} if q else {"user_id": u.user_id}

    logs = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return [_strip_oids(d) for d in logs]


@api.get("/audit/facets")
async def audit_facets(authorization: Optional[str] = Header(None)):
    """Filter options for the audit UI: distinct entities, actions, and users."""
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "gm", "purchase", "pm"):
        raise HTTPException(403, "Not allowed")
    ents = await db.audit_logs.distinct("entity")
    acts = await db.audit_logs.distinct("action")
    users_docs = await db.audit_logs.aggregate([
        {"$group": {"_id": "$user_id",
                     "name": {"$first": "$user_name"},
                     "role": {"$first": "$user_role"}}},
        {"$limit": 200},
    ]).to_list(200)
    users = [{"user_id": d["_id"], "name": d.get("name"), "role": d.get("role")}
             for d in users_docs if d.get("_id")]
    return {"entities": sorted([e for e in ents if e]),
            "actions": sorted([a for a in acts if a]),
            "users": users}
