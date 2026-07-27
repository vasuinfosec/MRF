"""Projects router — extracted from server.py in Phase 9C round 5 (Batch C).

Covers project master + nested Sites + Team management endpoints.
Admin required for all mutations. Read scoped per role.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, audit, master_audit, gid,
    Project,
)


@api.get("/projects")
async def list_projects(all: Optional[bool] = False,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"active": True}
    docs = await db.projects.find(q, {"_id": 0}).to_list(500)
    if all and u.role == "admin":
        return docs
    if u.role in ("purchase", "gm", "director", "admin"):
        return docs
    if u.role == "site_engineer":
        docs = [
            p for p in docs
            if u.user_id in (p.get("site_engineers") or [])
            or any(u.user_id in (s.get("site_engineers") or [])
                     for s in (p.get("sites") or []) if s.get("active", True))
        ]
    elif u.role == "pm":
        docs = [p for p in docs
                if u.user_id in (p.get("project_managers") or [])]
    elif u.role == "store":
        # Store users see projects where they're a site engineer at some site
        docs = [
            p for p in docs
            if u.user_id in (p.get("site_engineers") or [])
            or any(u.user_id in (s.get("site_engineers") or [])
                     for s in (p.get("sites") or []) if s.get("active", True))
        ]
    return docs


# ---------- Sites (sub-master) ----------
@api.post("/projects/{project_id}/sites")
async def add_site(project_id: str, body: dict,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Site name required")
    site = {
        "site_id": gid("st"),
        "name": name,
        "location": (body.get("location") or "").strip(),
        "site_engineers": list(body.get("site_engineers") or []),
        "active": True,
    }
    r = await db.projects.update_one({"project_id": project_id},
                                       {"$push": {"sites": site}})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "site_add", u, {"site": name})
    return site


@api.put("/projects/{project_id}/sites/{site_id}")
async def update_site(project_id: str, site_id: str, body: dict,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    updates: Dict[str, Any] = {}
    for k in ("name", "location"):
        if k in body:
            updates[f"sites.$.{k}"] = str(body[k] or "").strip()
    if "site_engineers" in body and isinstance(body["site_engineers"], list):
        updates["sites.$.site_engineers"] = [str(x) for x in body["site_engineers"]]
    if "active" in body:
        updates["sites.$.active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    r = await db.projects.update_one(
        {"project_id": project_id, "sites.site_id": site_id},
        {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Site not found")
    await audit("project", project_id, "site_update", u, {"site_id": site_id, **body})
    proj = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    return next((s for s in (proj.get("sites") or [])
                 if s["site_id"] == site_id), None)


@api.delete("/projects/{project_id}/sites/{site_id}")
async def remove_site(project_id: str, site_id: str,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    r = await db.projects.update_one(
        {"project_id": project_id, "sites.site_id": site_id},
        {"$set": {"sites.$.active": False}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Site not found")
    await audit("project", project_id, "site_delete", u, {"site_id": site_id})
    return {"ok": True}


# ---------- Team management ----------
@api.post("/projects/{project_id}/team")
async def update_project_team(project_id: str, body: dict,
                                authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    site_engineers = body.get("site_engineers")
    project_managers = body.get("project_managers")
    update: Dict[str, Any] = {}
    if isinstance(site_engineers, list):
        update["site_engineers"] = [str(x) for x in site_engineers]
    if isinstance(project_managers, list):
        update["project_managers"] = [str(x) for x in project_managers]
    if not update:
        raise HTTPException(400, "Nothing to update")
    r = await db.projects.update_one({"project_id": project_id}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "team_update", u, update)
    return await db.projects.find_one({"project_id": project_id}, {"_id": 0})


# ---------- Project CRUD ----------
@api.post("/projects")
async def add_project(p: Project, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    if p.customer_id:
        cust = await db.customers.find_one({"customer_id": p.customer_id}, {"_id": 0})
        if not cust:
            raise HTTPException(400,
                f"Customer '{p.customer_id}' not found — create the Customer master first")
        if not p.client:
            p.client = cust.get("name") or ""
    await db.projects.insert_one(p.model_dump())
    await master_audit("project", p.project_id, "create", u,
                        "Initial creation", None, p.model_dump())
    return p


@api.put("/projects/{project_id}")
async def update_project(project_id: str, body: dict,
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    existing = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Project not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")
    updates: Dict[str, Any] = {}
    for k in ("code", "name", "site", "client", "customer_id"):
        if k in body:
            updates[k] = str(body[k] or "").strip() or None
    if "system_categories" in body and isinstance(body["system_categories"], list):
        updates["system_categories"] = [str(x) for x in body["system_categories"]]
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    if updates.get("customer_id"):
        cust = await db.customers.find_one({"customer_id": updates["customer_id"]},
                                              {"_id": 0})
        if not cust:
            raise HTTPException(400, f"Customer '{updates['customer_id']}' not found")
    await db.projects.update_one({"project_id": project_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit("project", project_id, "update", u, reason, old_snap, updates)
    return await db.projects.find_one({"project_id": project_id}, {"_id": 0})


@api.delete("/projects/{project_id}")
async def deactivate_project(project_id: str, reason: str = "Deactivated",
                                authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    r = await db.projects.update_one({"project_id": project_id},
                                       {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await master_audit("project", project_id, "deactivate", u, reason,
                        {"active": True}, {"active": False})
    return {"ok": True}
