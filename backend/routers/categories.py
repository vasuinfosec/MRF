"""Material Category tree — Task 4.

Provides a hierarchical category catalogue backed by `material_categories`.
Each node:
    { cat_id, name, parent_id, path, level, order, active, created_at, ... }

Design:
  - `path` is a slash-joined chain of names (e.g. "Fire Alarm/Detectors/Smoke").
    Recomputed on every mutation for read performance.
  - Move-tree operation guards against cycles.
  - Deactivating a parent with active children is blocked (soft protection).
  - CSV import: 2 columns — `path` (slash-separated) and `active` (optional).

Only admin/director may mutate; anyone authenticated may read.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional, Dict, Any, List
from fastapi import Header, HTTPException, UploadFile, File

from server import (
    api, db, get_current_user, master_audit, gid, now_utc, _strip_oids,
)

_ADMIN_ROLES = {"admin", "director"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


async def _recompute_paths(root_id: Optional[str]):
    """Rebuild `path` and `level` for the subtree rooted at `root_id`.

    If root_id is None → rebuild the entire tree. This is O(N) and fine for
    catalogues with a few hundred categories.
    """
    all_docs = await db.material_categories.find({}, {"_id": 0}).to_list(5000)
    by_id: Dict[str, Dict[str, Any]] = {d["cat_id"]: d for d in all_docs}
    updates: List[Any] = []
    for d in all_docs:
        chain: List[str] = []
        level = 0
        cur = d
        seen = set()
        while cur:
            if cur["cat_id"] in seen:
                # cycle guard: abort chain and mark orphan
                break
            seen.add(cur["cat_id"])
            chain.append(cur["name"])
            level += 1
            pid = cur.get("parent_id")
            cur = by_id.get(pid) if pid else None
        chain.reverse()
        new_path = "/".join(chain)
        new_level = max(level - 1, 0)
        if d.get("path") != new_path or d.get("level") != new_level:
            updates.append((d["cat_id"], new_path, new_level))
    if updates:
        for cat_id, p, lv in updates:
            await db.material_categories.update_one(
                {"cat_id": cat_id}, {"$set": {"path": p, "level": lv}}
            )


async def _has_cycle(cat_id: str, new_parent_id: Optional[str]) -> bool:
    """Return True if setting new_parent_id would create a cycle involving cat_id."""
    if not new_parent_id:
        return False
    if new_parent_id == cat_id:
        return True
    seen = set()
    cur_id: Optional[str] = new_parent_id
    while cur_id:
        if cur_id in seen:
            return True
        if cur_id == cat_id:
            return True
        seen.add(cur_id)
        parent = await db.material_categories.find_one(
            {"cat_id": cur_id}, {"_id": 0, "parent_id": 1}
        )
        cur_id = parent.get("parent_id") if parent else None
    return False


# ---------------------- List / Tree ----------------------
@api.get("/categories")
async def list_categories(tree: int = 0, include_inactive: int = 0,
                          authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    filt: Dict[str, Any] = {}
    if not include_inactive:
        filt["active"] = True
    docs = await db.material_categories.find(filt, {"_id": 0}).sort(
        [("path", 1), ("name", 1)]
    ).to_list(5000)
    docs = [_strip_oids(d) for d in docs]
    if not tree:
        return docs
    # Build a tree
    by_id: Dict[str, Dict[str, Any]] = {d["cat_id"]: {**d, "children": []} for d in docs}
    roots: List[Dict[str, Any]] = []
    for d in by_id.values():
        pid = d.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(d)
        else:
            roots.append(d)
    return roots


# ---------------------- Create ----------------------
@api.post("/categories")
async def create_category(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director may create categories")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Category name required")
    if len(name) > 60:
        raise HTTPException(400, "Category name too long (max 60 chars)")
    if "/" in name:
        raise HTTPException(400, "'/' is reserved — use parent_id to nest categories")
    parent_id = (body.get("parent_id") or "").strip() or None
    if parent_id:
        parent = await db.material_categories.find_one({"cat_id": parent_id}, {"_id": 0})
        if not parent:
            raise HTTPException(400, "parent_id not found")
        if not parent.get("active", True):
            raise HTTPException(400, "Cannot nest under an inactive category")
    # Duplicate sibling name check (case-insensitive)
    dup = await db.material_categories.find_one({
        "parent_id": parent_id,
        "name_norm": _norm(name),
        "active": True,
    })
    if dup:
        raise HTTPException(400, f"'{name}' already exists at this level")
    doc = {
        "cat_id": gid("cat"),
        "name": name,
        "name_norm": _norm(name),
        "parent_id": parent_id,
        "path": "",
        "level": 0,
        "order": int(body.get("order") or 0),
        "active": True,
        "created_at": now_utc(),
        "created_by": u.user_id,
        "created_by_name": u.name,
    }
    await db.material_categories.insert_one(doc)
    doc.pop("_id", None)
    await _recompute_paths(None)
    saved = await db.material_categories.find_one({"cat_id": doc["cat_id"]}, {"_id": 0})
    await master_audit("category", doc["cat_id"], "create", u,
                       f"Category '{name}' created", None, saved)
    return saved


# ---------------------- Update (rename/move/toggle active) ----------------------
@api.put("/categories/{cat_id}")
async def update_category(cat_id: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "Reason is required for category changes")
    existing = await db.material_categories.find_one({"cat_id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Category not found")

    updates: Dict[str, Any] = {}
    if "name" in body:
        new_name = (body["name"] or "").strip()
        if not new_name:
            raise HTTPException(400, "name cannot be empty")
        if "/" in new_name:
            raise HTTPException(400, "'/' is reserved in names")
        if len(new_name) > 60:
            raise HTTPException(400, "name too long")
        # sibling uniqueness
        pid = body.get("parent_id", existing.get("parent_id"))
        sib = await db.material_categories.find_one({
            "cat_id": {"$ne": cat_id},
            "parent_id": pid,
            "name_norm": _norm(new_name),
            "active": True,
        })
        if sib:
            raise HTTPException(400, f"'{new_name}' already exists at this level")
        updates["name"] = new_name
        updates["name_norm"] = _norm(new_name)

    if "parent_id" in body:
        new_parent = (body["parent_id"] or "").strip() or None
        if new_parent == cat_id:
            raise HTTPException(400, "Cannot set self as parent")
        if new_parent:
            parent = await db.material_categories.find_one({"cat_id": new_parent}, {"_id": 0})
            if not parent:
                raise HTTPException(400, "New parent not found")
            if await _has_cycle(cat_id, new_parent):
                raise HTTPException(400, "Move would create a cycle")
        updates["parent_id"] = new_parent

    if "order" in body:
        try:
            updates["order"] = int(body["order"])
        except Exception:
            raise HTTPException(400, "order must be an integer")

    if "active" in body:
        want_active = bool(body["active"])
        if not want_active:
            # cannot deactivate if there are active children
            child = await db.material_categories.find_one(
                {"parent_id": cat_id, "active": True}
            )
            if child:
                raise HTTPException(400, "Deactivate all child categories first")
        updates["active"] = want_active

    if not updates:
        raise HTTPException(400, "Nothing to update")

    updates["updated_at"] = now_utc()
    await db.material_categories.update_one({"cat_id": cat_id}, {"$set": updates})
    await _recompute_paths(None)
    fresh = await db.material_categories.find_one({"cat_id": cat_id}, {"_id": 0})
    old_snap = {k: existing.get(k) for k in updates if k in existing}
    await master_audit("category", cat_id, "update", u, reason, old_snap, updates)
    return fresh


# ---------------------- Delete (soft, guarded) ----------------------
@api.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, reason: str = "Deactivated",
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    existing = await db.material_categories.find_one({"cat_id": cat_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Category not found")
    child = await db.material_categories.find_one({"parent_id": cat_id, "active": True})
    if child:
        raise HTTPException(400, "Deactivate all child categories first")
    # Optional: warn if referenced by materials
    ref = await db.materials.find_one({"category_id": cat_id})
    if ref:
        raise HTTPException(400, "Category is used by existing materials — re-assign them first")
    await db.material_categories.update_one({"cat_id": cat_id}, {"$set": {"active": False}})
    await master_audit("category", cat_id, "deactivate", u, reason,
                       {"active": True}, {"active": False})
    return {"ok": True}


# ---------------------- CSV template & import ----------------------
@api.get("/categories/template.csv")
async def categories_template(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["path", "active"])
    w.writerow(["Fire Alarm", "true"])
    w.writerow(["Fire Alarm/Detectors", "true"])
    w.writerow(["Fire Alarm/Detectors/Smoke", "true"])
    w.writerow(["Fire Alarm/Detectors/Heat", "true"])
    w.writerow(["Electrical/Wiring", "true"])
    return _csv_response(buf.getvalue(), "categories_template.csv")


@api.post("/categories/import")
async def categories_import(file: UploadFile = File(...),
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    content = await file.read()
    if len(content) > 512 * 1024:
        raise HTTPException(400, "CSV too large (max 512 KB)")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))
    created, dup, errors = [], [], []
    # Sort by path length so parents are created before children
    rows = [r for r in reader]
    rows.sort(key=lambda r: len((r.get("path") or "").split("/")))
    for idx, row in enumerate(rows, 2):
        path = (row.get("path") or "").strip().strip("/")
        if not path:
            errors.append({"row": idx, "reason": "empty path"})
            continue
        parts = [p.strip() for p in path.split("/") if p.strip()]
        if not parts:
            errors.append({"row": idx, "reason": "empty path"})
            continue
        cur_parent: Optional[str] = None
        last_cat_id: Optional[str] = None
        created_any = False
        skipped = False
        for name in parts:
            if len(name) > 60:
                errors.append({"row": idx, "reason": f"'{name[:20]}...' too long"})
                skipped = True; break
            existing = await db.material_categories.find_one({
                "parent_id": cur_parent,
                "name_norm": _norm(name),
                "active": True,
            }, {"_id": 0, "cat_id": 1})
            if existing:
                last_cat_id = existing["cat_id"]
                cur_parent = existing["cat_id"]
                continue
            doc = {
                "cat_id": gid("cat"),
                "name": name,
                "name_norm": _norm(name),
                "parent_id": cur_parent,
                "path": "",  # recomputed below
                "level": 0,
                "order": 0,
                "active": str(row.get("active") or "true").strip().lower() in ("1", "true", "yes"),
                "created_at": now_utc(),
                "created_by": u.user_id,
                "source": "csv_import",
            }
            await db.material_categories.insert_one(doc)
            last_cat_id = doc["cat_id"]
            cur_parent = doc["cat_id"]
            created_any = True
            created.append({"path": "/".join(parts[: parts.index(name) + 1])})
        if skipped:
            continue
        # If every segment of this row already existed, mark it as a duplicate
        # so the summary correctly reflects "nothing new was added".
        if not created_any and last_cat_id is not None:
            dup.append({"row": idx, "path": path})
        elif last_cat_id is None:
            dup.append({"row": idx, "path": path})
    await _recompute_paths(None)
    await master_audit("category.import", f"batch_{now_utc().timestamp()}",
                       "bulk_import", u,
                       f"Category CSV: {len(created)} new, {len(dup)} dup, {len(errors)} err",
                       None, {"created": len(created), "duplicates": len(dup), "errors": len(errors)})
    return {"created": created, "duplicates": dup, "errors": errors,
            "summary": {"created": len(created), "duplicates": len(dup), "errors": len(errors)}}


# ---------------------- Helpers ----------------------
def _csv_response(text: str, filename: str):
    from fastapi.responses import Response
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
