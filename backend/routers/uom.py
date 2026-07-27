"""UOM router — Task 4: Material Master & UOM controls.

Provides:
  - UOM CRUD (thin wrappers around the `masters` collection for category='unit')
  - UOM conversion rules (stored in `uom_conversions` collection)
  - Convenience `POST /uom/convert` endpoint (qty * factor)
  - CSV template & bulk-import for both units and conversions

Design decisions:
  - Units continue to live in `masters` (category='unit') so the existing
    /api/masters aggregation still works untouched.
  - Conversions are separate rows with { from_uom, to_uom, factor }.
  - Reverse lookups are computed on the fly (1/factor).
  - Chained conversions (A→B→C) are supported by BFS on demand.

Only director/admin may modify (director role can bootstrap when admin unset).
Anyone authenticated can list/convert.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional, Dict, Any, List
from fastapi import Header, HTTPException, UploadFile, File

from server import (
    api, db, get_current_user, master_audit, gid, now_utc,
    _strip_oids,
)

# Roles that may write UOM data
_UOM_ADMIN_ROLES = {"admin", "director"}


def _norm_unit(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


# ---------------------- Units (thin CRUD on masters/category=unit) ----------------------
@api.get("/uom/units")
async def uom_list_units(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    docs = await db.masters.find(
        {"category": "unit", "active": True}, {"_id": 0}
    ).sort("name", 1).to_list(500)
    return [_strip_oids(d) for d in docs]


@api.post("/uom/units")
async def uom_create_unit(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director may create units")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Unit name required")
    if len(name) > 32:
        raise HTTPException(400, "Unit name too long (max 32 chars)")
    dup = await db.masters.find_one({
        "category": "unit",
        "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        "active": True,
    })
    if dup:
        raise HTTPException(400, f"Unit '{name}' already exists")
    doc = {
        "item_id": gid("uom"),
        "category": "unit",
        "name": name,
        "symbol": (body.get("symbol") or name).strip()[:16],
        "kind": (body.get("kind") or "count").strip().lower(),  # count/length/mass/volume/time/area
        "is_base": bool(body.get("is_base", False)),
        "active": True,
        "created_at": now_utc(),
        "created_by": u.user_id,
    }
    await db.masters.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("master.unit", doc["item_id"], "create", u,
                       "UOM created", None, doc)
    return doc


@api.put("/uom/units/{item_id}")
async def uom_update_unit(item_id: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "Reason required for UOM changes")
    existing = await db.masters.find_one({"item_id": item_id, "category": "unit"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Unit not found")
    updates: Dict[str, Any] = {}
    for k in ("name", "symbol", "kind"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "is_base" in body:
        updates["is_base"] = bool(body["is_base"])
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.masters.update_one({"item_id": item_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit("master.unit", item_id, "update", u, reason, old_snap, updates)
    return await db.masters.find_one({"item_id": item_id}, {"_id": 0})


@api.delete("/uom/units/{item_id}")
async def uom_delete_unit(item_id: str, reason: str = "Deactivated",
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    existing = await db.masters.find_one({"item_id": item_id, "category": "unit"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Unit not found")
    # Block if in use by any conversion rule (soft protection)
    in_use = await db.uom_conversions.find_one(
        {"$or": [{"from_uom": existing["name"]}, {"to_uom": existing["name"]}]}
    )
    if in_use:
        raise HTTPException(400, "Unit is used in conversion rules — remove them first")
    await db.masters.update_one({"item_id": item_id}, {"$set": {"active": False}})
    await master_audit("master.unit", item_id, "deactivate", u, reason,
                       {"active": True}, {"active": False})
    return {"ok": True}


# ---------------------- Conversion rules ----------------------
@api.get("/uom/conversions")
async def uom_list_conversions(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    docs = await db.uom_conversions.find({}, {"_id": 0}).sort([("from_uom", 1), ("to_uom", 1)]).to_list(2000)
    return [_strip_oids(d) for d in docs]


@api.post("/uom/conversions")
async def uom_create_conversion(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director may add conversion rules")
    from_uom = (body.get("from_uom") or "").strip()
    to_uom = (body.get("to_uom") or "").strip()
    if not from_uom or not to_uom:
        raise HTTPException(400, "from_uom and to_uom required")
    if _norm_unit(from_uom) == _norm_unit(to_uom):
        raise HTTPException(400, "from_uom and to_uom must be different")
    try:
        factor = float(body.get("factor"))
    except Exception:
        raise HTTPException(400, "factor must be numeric (float)")
    if factor <= 0:
        raise HTTPException(400, "factor must be > 0")
    # Verify both units exist (active)
    for u_name in (from_uom, to_uom):
        exists = await db.masters.find_one({
            "category": "unit", "active": True,
            "name": {"$regex": f"^{re.escape(u_name)}$", "$options": "i"},
        }, {"_id": 0, "name": 1})
        if not exists:
            raise HTTPException(400, f"Unit '{u_name}' is not registered — add it under Units first")
    # De-dup
    dup = await db.uom_conversions.find_one({
        "from_uom_norm": _norm_unit(from_uom),
        "to_uom_norm": _norm_unit(to_uom),
    })
    if dup:
        raise HTTPException(400, f"Conversion {from_uom} → {to_uom} already exists")
    doc = {
        "conv_id": gid("uconv"),
        "from_uom": from_uom, "from_uom_norm": _norm_unit(from_uom),
        "to_uom": to_uom, "to_uom_norm": _norm_unit(to_uom),
        "factor": factor,
        "notes": (body.get("notes") or "").strip(),
        "created_at": now_utc(),
        "created_by": u.user_id,
        "created_by_name": u.name,
    }
    await db.uom_conversions.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("uom.conversion", doc["conv_id"], "create", u,
                       f"1 {from_uom} = {factor} {to_uom}", None, doc)
    return doc


@api.delete("/uom/conversions/{conv_id}")
async def uom_delete_conversion(conv_id: str, reason: str = "Removed",
                                 authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    existing = await db.uom_conversions.find_one({"conv_id": conv_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Conversion not found")
    await db.uom_conversions.delete_one({"conv_id": conv_id})
    await master_audit("uom.conversion", conv_id, "delete", u, reason, existing, None)
    return {"ok": True}


# ---------------------- Convert helper ----------------------
async def _resolve_factor(from_u: str, to_u: str) -> Optional[float]:
    """Return factor such that `qty_from * factor = qty_to`.

    Strategy:
      1. Direct hit in uom_conversions.
      2. Reverse hit (from ↔ to → factor = 1/f).
      3. BFS through the conversion graph up to depth 4.
    """
    src = _norm_unit(from_u)
    dst = _norm_unit(to_u)
    if not src or not dst:
        return None
    if src == dst:
        return 1.0
    # Build adjacency in-memory (uom count is small; cheap).
    edges: Dict[str, List[Dict[str, Any]]] = {}
    async for c in db.uom_conversions.find({}, {"_id": 0}):
        f = c["from_uom_norm"]; t = c["to_uom_norm"]; k = float(c["factor"])
        edges.setdefault(f, []).append({"to": t, "factor": k})
        edges.setdefault(t, []).append({"to": f, "factor": 1.0 / k if k else 0})
    # BFS
    if src not in edges:
        return None
    seen = {src}
    queue: List[tuple] = [(src, 1.0, 0)]
    while queue:
        node, acc, depth = queue.pop(0)
        if node == dst:
            return acc
        if depth >= 4:
            continue
        for e in edges.get(node, []):
            if e["to"] in seen:
                continue
            seen.add(e["to"])
            queue.append((e["to"], acc * e["factor"], depth + 1))
    return None


@api.post("/uom/convert")
async def uom_convert(body: dict, authorization: Optional[str] = Header(None)):
    """Body: { qty, from_uom, to_uom } → { qty, factor, chained: bool } or 400."""
    await get_current_user(authorization)
    try:
        qty = float(body.get("qty"))
    except Exception:
        raise HTTPException(400, "qty must be numeric")
    from_u = (body.get("from_uom") or "").strip()
    to_u = (body.get("to_uom") or "").strip()
    if not from_u or not to_u:
        raise HTTPException(400, "from_uom and to_uom required")
    factor = await _resolve_factor(from_u, to_u)
    if factor is None:
        raise HTTPException(400, f"No conversion path from '{from_u}' to '{to_u}'")
    return {
        "qty_in": qty,
        "qty_out": round(qty * factor, 6),
        "from_uom": from_u,
        "to_uom": to_u,
        "factor": factor,
    }


# ---------------------- CSV template & bulk-import ----------------------
@api.get("/uom/units/template.csv")
async def uom_units_template(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "symbol", "kind", "is_base"])
    w.writerow(["Nos", "Nos", "count", "true"])
    w.writerow(["Metre", "m", "length", "true"])
    w.writerow(["Centimetre", "cm", "length", "false"])
    w.writerow(["Kilogram", "kg", "mass", "true"])
    return _csv_response(buf.getvalue(), "uom_units_template.csv")


@api.get("/uom/conversions/template.csv")
async def uom_conv_template(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["from_uom", "to_uom", "factor", "notes"])
    w.writerow(["Metre", "Centimetre", "100", "1 m = 100 cm"])
    w.writerow(["Box", "Nos", "12", "1 box = 12 pieces"])
    w.writerow(["Kilogram", "Gram", "1000", "1 kg = 1000 g"])
    return _csv_response(buf.getvalue(), "uom_conversions_template.csv")


@api.post("/uom/units/import")
async def uom_units_import(file: UploadFile = File(...),
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    content = await file.read()
    if len(content) > 512 * 1024:
        raise HTTPException(400, "CSV file too large (max 512 KB)")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))
    created, dup, errors = [], [], []
    for idx, row in enumerate(reader, 2):
        name = (row.get("name") or "").strip()
        if not name:
            errors.append({"row": idx, "reason": "empty name"})
            continue
        if len(name) > 32:
            errors.append({"row": idx, "name": name[:32], "reason": "name too long"})
            continue
        exists = await db.masters.find_one({
            "category": "unit",
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            "active": True,
        })
        if exists:
            dup.append({"row": idx, "name": name})
            continue
        doc = {
            "item_id": gid("uom"),
            "category": "unit",
            "name": name,
            "symbol": (row.get("symbol") or name).strip()[:16],
            "kind": (row.get("kind") or "count").strip().lower(),
            "is_base": str(row.get("is_base") or "").strip().lower() in ("1", "true", "yes"),
            "active": True,
            "created_at": now_utc(),
            "created_by": u.user_id,
            "source": "csv_import",
        }
        await db.masters.insert_one(doc)
        created.append({"name": name})
    await master_audit("master.unit.import", f"batch_{now_utc().timestamp()}",
                       "bulk_import", u,
                       f"UOM CSV import: {len(created)} new, {len(dup)} dup, {len(errors)} err",
                       None, {"created": len(created), "duplicates": len(dup), "errors": len(errors)})
    return {"created": created, "duplicates": dup, "errors": errors,
            "summary": {"created": len(created), "duplicates": len(dup), "errors": len(errors)}}


@api.post("/uom/conversions/import")
async def uom_conv_import(file: UploadFile = File(...),
                           authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in _UOM_ADMIN_ROLES:
        raise HTTPException(403, "Only admin/director")
    content = await file.read()
    if len(content) > 512 * 1024:
        raise HTTPException(400, "CSV file too large (max 512 KB)")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))
    created, dup, errors = [], [], []
    for idx, row in enumerate(reader, 2):
        from_u = (row.get("from_uom") or "").strip()
        to_u = (row.get("to_uom") or "").strip()
        if not from_u or not to_u:
            errors.append({"row": idx, "reason": "from_uom / to_uom missing"})
            continue
        if _norm_unit(from_u) == _norm_unit(to_u):
            errors.append({"row": idx, "reason": "from and to are same"})
            continue
        try:
            factor = float(row.get("factor") or 0)
        except Exception:
            errors.append({"row": idx, "reason": "factor not numeric"})
            continue
        if factor <= 0:
            errors.append({"row": idx, "reason": "factor must be > 0"})
            continue
        # Validate registered units
        missing = None
        for name in (from_u, to_u):
            found = await db.masters.find_one({
                "category": "unit", "active": True,
                "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            }, {"_id": 0, "name": 1})
            if not found:
                missing = name; break
        if missing:
            errors.append({"row": idx, "reason": f"unit '{missing}' not registered"})
            continue
        existing = await db.uom_conversions.find_one({
            "from_uom_norm": _norm_unit(from_u),
            "to_uom_norm": _norm_unit(to_u),
        })
        if existing:
            dup.append({"row": idx, "from_uom": from_u, "to_uom": to_u})
            continue
        doc = {
            "conv_id": gid("uconv"),
            "from_uom": from_u, "from_uom_norm": _norm_unit(from_u),
            "to_uom": to_u, "to_uom_norm": _norm_unit(to_u),
            "factor": factor,
            "notes": (row.get("notes") or "").strip(),
            "created_at": now_utc(),
            "created_by": u.user_id,
            "created_by_name": u.name,
            "source": "csv_import",
        }
        await db.uom_conversions.insert_one(doc)
        created.append({"from_uom": from_u, "to_uom": to_u, "factor": factor})
    await master_audit("uom.conversion.import", f"batch_{now_utc().timestamp()}",
                       "bulk_import", u,
                       f"UOM conv CSV: {len(created)} new, {len(dup)} dup, {len(errors)} err",
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
