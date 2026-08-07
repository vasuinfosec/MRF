"""Project Material BOQ assignment router.

Lets Admin assign a material (MAT-#### UID) to a project with a BOQ quantity
(entered manually or pulled from the estimator integration), and exposes the
running Balance = boq_qty - consumed (sum of qty_approved on this project's
approved MRF items for that material). Only Admin may create/update/delete
an assignment; any authenticated role with project visibility may read the
list — the MRF create screen uses it to gate `qty_requested`.
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from fastapi import Header, HTTPException

from server import (
    api, db, get_current_user, audit, master_audit, now_utc, gid,
    ProjectMaterialIn, ProjectMaterial,
    _project_material_balance, _project_material_consumed,
)


@api.get("/projects/{project_id}/materials")
async def list_project_materials(project_id: str,
                                   authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    proj = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    if not proj:
        raise HTTPException(404, "Project not found")
    rows = await db.project_materials.find(
        {"project_id": project_id}, {"_id": 0}).to_list(1000)
    out = []
    for pm in rows:
        consumed = await _project_material_consumed(project_id, pm["material_uid"])
        out.append({**pm, "consumed_qty": consumed, "balance": pm["boq_qty"] - consumed})
    return out


@api.post("/projects/{project_id}/materials")
async def add_project_material(project_id: str, body: ProjectMaterialIn,
                                  authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    proj = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    if not proj:
        raise HTTPException(404, "Project not found")
    mat = await db.materials.find_one({"material_uid": body.material_uid}, {"_id": 0})
    if not mat:
        raise HTTPException(400, f"Material '{body.material_uid}' not found")
    existing = await db.project_materials.find_one(
        {"project_id": project_id, "material_uid": body.material_uid}, {"_id": 0})
    if existing:
        raise HTTPException(
            409, "This material is already assigned to the project — use edit instead")
    pm = ProjectMaterial(project_id=project_id, created_by=u.user_id,
                          **body.model_dump())
    await db.project_materials.insert_one(pm.model_dump())
    await master_audit("project_material", pm.pm_id, "create", u,
                        "Initial BOQ assignment", None, pm.model_dump())
    return {**pm.model_dump(), "consumed_qty": 0.0, "balance": pm.boq_qty}


@api.put("/projects/{project_id}/materials/{pm_id}")
async def update_project_material(project_id: str, pm_id: str, body: dict,
                                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    existing = await db.project_materials.find_one(
        {"project_id": project_id, "pm_id": pm_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Assignment not found")
    updates: Dict[str, Any] = {}
    if "boq_qty" in body:
        try:
            qty = float(body["boq_qty"])
        except Exception:
            raise HTTPException(400, "boq_qty must be numeric")
        if qty <= 0:
            raise HTTPException(400, "boq_qty must be greater than 0")
        updates["boq_qty"] = qty
    if "source" in body:
        if body["source"] not in ("manual", "estimator"):
            raise HTTPException(400, "source must be 'manual' or 'estimator'")
        updates["source"] = body["source"]
    if "boq_ref" in body:
        updates["boq_ref"] = body["boq_ref"]
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = now_utc()
    await db.project_materials.update_one({"pm_id": pm_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates if k != "updated_at"}
    new_snap = {k: v for k, v in updates.items() if k != "updated_at"}
    await master_audit("project_material", pm_id, "update", u,
                        body.get("reason") or "BOQ qty updated", old_snap, new_snap)
    return await _project_material_balance(project_id, existing["material_uid"])


@api.delete("/projects/{project_id}/materials/{pm_id}")
async def delete_project_material(project_id: str, pm_id: str,
                                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    existing = await db.project_materials.find_one(
        {"project_id": project_id, "pm_id": pm_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Assignment not found")
    consumed = await _project_material_consumed(project_id, existing["material_uid"])
    if consumed > 0:
        raise HTTPException(
            409, "Cannot delete — this material already has approved MRF quantity "
                 "against it. Reduce the BOQ qty instead.")
    await db.project_materials.delete_one({"pm_id": pm_id})
    await master_audit("project_material", pm_id, "delete", u,
                        "Assignment removed", existing, None)
    return {"ok": True}
