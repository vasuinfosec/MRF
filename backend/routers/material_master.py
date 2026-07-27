"""Task 4 — category-linked Material Master and UOM administration.

All endpoints are local/staging-safe CRUD-style controls.  Historical records
are never deleted: category, UOM, and material lifecycle changes only toggle
``active`` and retain immutable identifiers/snapshots used by MRF/PO/GRN/DC.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from fastapi import Header, HTTPException
from pymongo.errors import DuplicateKeyError

from server import (
    MAT_WORD_LIMIT,
    _ensure_variant,
    _mat_uid,
    _next_seq,
    _norm,
    _strip_oids,
    _word_count,
    api,
    db,
    get_current_user,
    gid,
    master_audit,
    now_utc,
    permission_roles,
)


DEFAULT_LOW_VALUE_THRESHOLD_INR = 100.0
STANDARD_UOM_CODES = {"nos", "metre", "kg", "litre", "set", "box", "lot"}
PACKAGING_UOM_CODES = {"box", "lot"}
FASTENER_TERMS = {
    "fastener", "fasteners", "bolt", "bolts", "nut", "nuts", "screw",
    "screws", "washer", "washers", "anchor", "anchors", "rivet", "rivets",
}
BILLING_OPTIONS = {"billed", "not_billed", "either"}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _code(value: Any) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", _text(value).lower()).strip("_")


def _require_admin(user: Any) -> None:
    if not getattr(user, "is_active", False) or "admin" not in permission_roles(user):
        raise HTTPException(403, "Only an active Admin may manage Material Master controls")


async def _actor(authorization: Optional[str]) -> Any:
    user = await get_current_user(authorization)
    _require_admin(user)
    return user


async def _threshold() -> float:
    doc = await db.material_settings.find_one({"_id": "task4"})
    try:
        value = float((doc or {}).get("low_value_threshold_inr", DEFAULT_LOW_VALUE_THRESHOLD_INR))
    except (TypeError, ValueError):
        value = DEFAULT_LOW_VALUE_THRESHOLD_INR
    return value if value > 0 else DEFAULT_LOW_VALUE_THRESHOLD_INR


def _is_fastener(*values: Any) -> bool:
    words = set(re.findall(r"[a-z0-9]+", " ".join(_text(v).lower() for v in values)))
    return bool(words & FASTENER_TERMS)


def _classification(
    *,
    threshold: float,
    category: str,
    item: str,
    specification: str,
    description: str,
    unit_value: float,
    is_consumable: bool,
    force_traceable: bool,
) -> Dict[str, Any]:
    fastener = _is_fastener(category, item, specification, description)
    traceable = bool(
        force_traceable
        or fastener
        or not is_consumable
        or unit_value >= threshold
    )
    return {
        "classification": "traceable" if traceable else "low_value_consumable",
        "reconciliation_required": traceable,
        "fastener_protected": fastener,
        "low_value_threshold_inr": threshold,
    }


def _material_key(
    category_id: str,
    item: str,
    specification: str,
    make: str,
    model: str,
) -> str:
    return "|".join([
        _norm(category_id),
        _norm(item),
        _norm(specification),
        _norm(make),
        _norm(model),
    ])


def _category_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out.setdefault("active", True)
    return _strip_oids(out)


def _uom_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out.setdefault("active", True)
    out.setdefault("conversion_quantity", 1.0)
    out.setdefault("base_uom_id", "")
    out.setdefault("is_standard", (out.get("code") or "") in STANDARD_UOM_CODES)
    return _strip_oids(out)


def _material_view(doc: Dict[str, Any], threshold: float) -> Dict[str, Any]:
    out = dict(doc)
    out.setdefault("active", True)
    out["item"] = out.get("item") or out.get("item_name") or out.get("item_code") or out.get("description", "")
    out["item_name"] = out["item"]
    out.setdefault("specification", "")
    out["category_name"] = out.get("category_name") or out.get("category", "")
    out["uom_name"] = out.get("uom_name") or out.get("unit", "")
    out.setdefault("uom_code", _code(out.get("unit", "")))
    out.setdefault("make", "")
    out.setdefault("model", "")
    out.setdefault("unit_value", 0.0)
    out.setdefault("is_consumable", False)
    out.setdefault("force_traceable", False)
    out.setdefault("amc_material", False)
    out.setdefault("billing_option", "either")
    out.update(_classification(
        threshold=threshold,
        category=out.get("category_name", ""),
        item=out.get("item", ""),
        specification=out.get("specification", ""),
        description=out.get("description", ""),
        unit_value=float(out.get("unit_value") or 0),
        is_consumable=bool(out.get("is_consumable")),
        force_traceable=bool(out.get("force_traceable")),
    ))
    return _strip_oids(out)


async def _active_category(category_id: str) -> Dict[str, Any]:
    doc = await db.material_categories.find_one({
        "category_id": category_id,
        "active": {"$ne": False},
    }, {"_id": 0})
    if not doc:
        raise HTTPException(400, "Select an active material category")
    return doc


async def _active_uom(uom_id: str) -> Dict[str, Any]:
    doc = await db.uoms.find_one({
        "uom_id": uom_id,
        "active": {"$ne": False},
    }, {"_id": 0})
    if not doc:
        raise HTTPException(400, "Select an active approved UOM")
    return doc


def _validate_conversion(
    code: str,
    conversion_quantity: Any,
    base_uom_id: str,
) -> tuple[float, str]:
    try:
        quantity = float(conversion_quantity if conversion_quantity not in (None, "") else 1)
    except (TypeError, ValueError):
        raise HTTPException(400, "Conversion quantity must be numeric")
    if not math.isfinite(quantity) or quantity <= 0:
        raise HTTPException(400, "Conversion quantity must be greater than zero")
    if code in PACKAGING_UOM_CODES:
        if not _text(base_uom_id):
            raise HTTPException(400, "Box/lot UOM requires a base UOM")
    else:
        quantity = 1.0
        base_uom_id = ""
    return quantity, _text(base_uom_id)


async def _validate_uom_body(body: Dict[str, Any], existing_id: str = "") -> Dict[str, Any]:
    name = _text(body.get("name"))
    code = _code(body.get("code") or name)
    if not name or not code:
        raise HTTPException(400, "UOM name and code are required")
    if len(code) > 24:
        raise HTTPException(400, "UOM code must be 24 characters or fewer")
    conversion, base_id = _validate_conversion(
        code,
        body.get("conversion_quantity"),
        body.get("base_uom_id") or "",
    )
    if base_id:
        base = await db.uoms.find_one({
            "uom_id": base_id,
            "active": {"$ne": False},
        }, {"_id": 0})
        if not base:
            raise HTTPException(400, "Base UOM must be active")
        if existing_id and base_id == existing_id:
            raise HTTPException(400, "A UOM cannot convert to itself")
        if (base.get("code") or "") in PACKAGING_UOM_CODES:
            raise HTTPException(400, "Box/lot base UOM must resolve to a non-packaging unit")
    return {
        "name": name,
        "name_norm": _norm(name),
        "code": code,
        "code_norm": _norm(code),
        "conversion_quantity": conversion,
        "base_uom_id": base_id,
        "is_standard": code in STANDARD_UOM_CODES,
        "approved": True,
    }


async def _material_updates(body: Dict[str, Any]) -> Dict[str, Any]:
    category_id = _text(body.get("category_id"))
    uom_id = _text(body.get("uom_id"))
    category = await _active_category(category_id)
    uom = await _active_uom(uom_id)
    item = _text(body.get("item") or body.get("item_name"))
    specification = _text(body.get("specification"))
    description = _text(body.get("description"))
    make = _text(body.get("make"))
    model = _text(body.get("model"))
    if not item:
        raise HTTPException(400, "Item is required")
    if not specification:
        raise HTTPException(400, "Specification is required")
    if not description:
        raise HTTPException(400, "Description is required")
    if _word_count(description) > MAT_WORD_LIMIT:
        raise HTTPException(400, f"Description exceeds {MAT_WORD_LIMIT} words")
    try:
        unit_value = float(body.get("unit_value") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Unit value must be numeric")
    if unit_value < 0:
        raise HTTPException(400, "Unit value cannot be negative")
    billing_option = _code(body.get("billing_option") or "either")
    if billing_option not in BILLING_OPTIONS:
        raise HTTPException(400, "Billing option must be billed, not_billed or either")
    key = _material_key(category_id, item, specification, make, model)
    threshold = await _threshold()
    derived = _classification(
        threshold=threshold,
        category=category.get("name", ""),
        item=item,
        specification=specification,
        description=description,
        unit_value=unit_value,
        is_consumable=bool(body.get("is_consumable")),
        force_traceable=bool(body.get("force_traceable")),
    )
    return {
        "category_id": category_id,
        "category_name": category.get("name", ""),
        "category": category.get("name", ""),  # legacy/MRF display compatibility
        "item": item,
        "item_name": item,
        "item_norm": _norm(item),
        "specification": specification,
        "specification_norm": _norm(specification),
        "description": description,
        "description_norm": _norm(description),
        "make": make,
        "make_norm": _norm(make),
        "model": model,
        "model_norm": _norm(model),
        "uom_id": uom_id,
        "uom_name": uom.get("name", ""),
        "uom_code": uom.get("code", ""),
        "unit": uom.get("name", ""),  # existing MRF/PO/GRN/DC contract
        "unit_value": unit_value,
        "is_consumable": bool(body.get("is_consumable")),
        "force_traceable": bool(body.get("force_traceable")),
        "amc_material": bool(body.get("amc_material")),
        "billing_option": billing_option,
        "material_key": key,
        **derived,
    }


# ---------------------- Settings ----------------------
@api.get("/admin/material-master/settings")
async def get_material_settings(authorization: Optional[str] = Header(None)):
    await _actor(authorization)
    return {
        "low_value_threshold_inr": await _threshold(),
        "default_low_value_threshold_inr": DEFAULT_LOW_VALUE_THRESHOLD_INR,
    }


@api.put("/admin/material-master/settings")
async def update_material_settings(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    try:
        threshold = float(body.get("low_value_threshold_inr"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Low-value threshold must be numeric")
    if threshold <= 0:
        raise HTTPException(400, "Low-value threshold must be greater than zero")
    reason = _text(body.get("reason"))
    if not reason:
        raise HTTPException(400, "Reason is required")
    old = await db.material_settings.find_one({"_id": "task4"}, {"_id": 0}) or {
        "low_value_threshold_inr": DEFAULT_LOW_VALUE_THRESHOLD_INR
    }
    update = {
        "low_value_threshold_inr": threshold,
        "updated_at": now_utc(),
        "updated_by": user.user_id,
    }
    await db.material_settings.update_one(
        {"_id": "task4"},
        {"$set": update},
        upsert=True,
    )
    await master_audit(
        "material_settings", "task4", "update", user, reason,
        {"low_value_threshold_inr": old.get("low_value_threshold_inr")},
        {"low_value_threshold_inr": threshold},
    )
    return {"low_value_threshold_inr": threshold}


# ---------------------- Categories ----------------------
@api.get("/admin/material-master/categories")
async def list_material_categories(authorization: Optional[str] = Header(None)):
    await _actor(authorization)
    docs = await db.material_categories.find({}, {"_id": 0}).sort("name_norm", 1).to_list(1000)
    return [_category_view(doc) for doc in docs]


@api.post("/admin/material-master/categories")
async def create_material_category(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    name = _text(body.get("name"))
    if not name:
        raise HTTPException(400, "Category name is required")
    name_norm = _norm(name)
    if await db.material_categories.find_one({"name_norm": name_norm}):
        raise HTTPException(400, "Material category already exists")
    doc = {
        "category_id": gid("mcat"),
        "name": name,
        "name_norm": name_norm,
        "description": _text(body.get("description")),
        "active": True,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "created_by": user.user_id,
    }
    try:
        await db.material_categories.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(400, "Material category already exists")
    doc.pop("_id", None)
    await master_audit(
        "material_category", doc["category_id"], "create", user,
        "Category created", None, doc,
    )
    return _category_view(doc)


@api.put("/admin/material-master/categories/{category_id}")
async def update_material_category(
    category_id: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.material_categories.find_one({"category_id": category_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Category not found")
    reason = _text(body.get("reason"))
    if not reason:
        raise HTTPException(400, "Reason is required")
    name = _text(body.get("name", existing.get("name")))
    if not name:
        raise HTTPException(400, "Category name is required")
    duplicate = await db.material_categories.find_one({
        "name_norm": _norm(name),
        "category_id": {"$ne": category_id},
    })
    if duplicate:
        raise HTTPException(400, "Material category already exists")
    updates = {
        "name": name,
        "name_norm": _norm(name),
        "description": _text(body.get("description", existing.get("description"))),
        "updated_at": now_utc(),
        "updated_by": user.user_id,
    }
    await db.material_categories.update_one({"category_id": category_id}, {"$set": updates})
    await master_audit(
        "material_category", category_id, "update", user, reason,
        {"name": existing.get("name"), "description": existing.get("description")},
        updates,
    )
    return _category_view({**existing, **updates})


@api.post("/admin/material-master/categories/{category_id}/status")
async def set_material_category_status(
    category_id: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.material_categories.find_one({"category_id": category_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Category not found")
    active = bool(body.get("active"))
    reason = _text(body.get("reason")) or ("Activated" if active else "Deactivated")
    updates = {"active": active, "updated_at": now_utc(), "updated_by": user.user_id}
    await db.material_categories.update_one({"category_id": category_id}, {"$set": updates})
    await master_audit(
        "material_category", category_id,
        "activate" if active else "deactivate", user, reason,
        {"active": existing.get("active", True)}, {"active": active},
    )
    return {"category_id": category_id, "active": active, "historical_records_retained": True}


# ---------------------- UOM controls ----------------------
@api.get("/admin/material-master/uoms")
async def list_uoms(authorization: Optional[str] = Header(None)):
    await _actor(authorization)
    docs = await db.uoms.find({}, {"_id": 0}).sort("name_norm", 1).to_list(1000)
    return [_uom_view(doc) for doc in docs]


@api.post("/admin/material-master/uoms")
async def create_uom(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    values = await _validate_uom_body(body)
    if await db.uoms.find_one({"code_norm": values["code_norm"]}):
        raise HTTPException(400, "UOM code already exists")
    doc = {
        "uom_id": gid("uom"),
        **values,
        "active": True,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "created_by": user.user_id,
    }
    try:
        await db.uoms.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(400, "UOM code already exists")
    doc.pop("_id", None)
    await master_audit("uom", doc["uom_id"], "create", user, "UOM created", None, doc)
    return _uom_view(doc)


@api.put("/admin/material-master/uoms/{uom_id}")
async def update_uom(
    uom_id: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.uoms.find_one({"uom_id": uom_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "UOM not found")
    reason = _text(body.get("reason"))
    if not reason:
        raise HTTPException(400, "Reason is required")
    values = await _validate_uom_body({**existing, **body}, existing_id=uom_id)
    duplicate = await db.uoms.find_one({
        "code_norm": values["code_norm"],
        "uom_id": {"$ne": uom_id},
    })
    if duplicate:
        raise HTTPException(400, "UOM code already exists")
    values.update({"updated_at": now_utc(), "updated_by": user.user_id})
    await db.uoms.update_one({"uom_id": uom_id}, {"$set": values})
    await master_audit(
        "uom", uom_id, "update", user, reason,
        {k: existing.get(k) for k in values if k in existing}, values,
    )
    return _uom_view({**existing, **values})


@api.post("/admin/material-master/uoms/{uom_id}/status")
async def set_uom_status(
    uom_id: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.uoms.find_one({"uom_id": uom_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "UOM not found")
    active = bool(body.get("active"))
    if not active:
        # Do not leave an active packaging conversion pointing at an inactive
        # base unit. Historical rows remain intact, but the live conversion
        # graph must stay valid for new MRF/PO/GRN/DC work.
        dependents = await db.uoms.find({
            "base_uom_id": uom_id,
            "active": {"$ne": False},
        }, {"_id": 0}).to_list(1000)
        if any((row.get("code") or "") in PACKAGING_UOM_CODES for row in dependents):
            raise HTTPException(
                400,
                "Cannot deactivate a base UOM used by an active box/lot conversion",
            )
    reason = _text(body.get("reason")) or ("Activated" if active else "Deactivated")
    updates = {"active": active, "updated_at": now_utc(), "updated_by": user.user_id}
    await db.uoms.update_one({"uom_id": uom_id}, {"$set": updates})
    await master_audit(
        "uom", uom_id, "activate" if active else "deactivate", user, reason,
        {"active": existing.get("active", True)}, {"active": active},
    )
    return {"uom_id": uom_id, "active": active, "historical_records_retained": True}


# ---------------------- Materials ----------------------
@api.get("/admin/material-master/materials")
async def list_admin_materials(authorization: Optional[str] = Header(None)):
    await _actor(authorization)
    threshold = await _threshold()
    docs = await db.materials.find({}, {"_id": 0}).sort("material_uid", 1).to_list(3000)
    return [_material_view(doc, threshold) for doc in docs]


@api.post("/admin/material-master/materials")
async def create_admin_material(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    values = await _material_updates(body)
    duplicate = await db.materials.find_one(
        {"material_key": values["material_key"]},
        {"_id": 0, "material_uid": 1},
    )
    if duplicate:
        raise HTTPException(400, f"Duplicate material: {duplicate['material_uid']}")
    uid = _mat_uid(await _next_seq("materials"))
    doc = {
        "material_uid": uid,
        **values,
        "item_code": _text(body.get("item_code")),
        "remarks": _text(body.get("remarks")),
        "active": True,
        "status": "approved",
        "created_by": user.user_id,
        "created_by_name": user.name,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "approved_by": user.user_id,
        "approved_at": now_utc(),
        "source": "task4_admin_console",
    }
    try:
        await db.materials.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(400, "Duplicate material UID or normalized material definition")
    doc.pop("_id", None)
    if values.get("make") or values.get("model"):
        await _ensure_variant(uid, values.get("make", ""), values.get("model", ""), uid)
    await master_audit("material", uid, "create", user, "Task 4 Admin creation", None, doc)
    return _material_view(doc, await _threshold())


@api.put("/admin/material-master/materials/{material_uid}")
async def update_admin_material(
    material_uid: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Material not found")
    reason = _text(body.get("reason"))
    if not reason:
        raise HTTPException(400, "Reason is required")
    merged = {**_material_view(existing, await _threshold()), **body}
    values = await _material_updates(merged)
    duplicate = await db.materials.find_one({
        "material_key": values["material_key"],
        "material_uid": {"$ne": material_uid},
    }, {"_id": 0, "material_uid": 1})
    if duplicate:
        raise HTTPException(400, f"Duplicate material: {duplicate['material_uid']}")
    values.update({
        "item_code": _text(body.get("item_code", existing.get("item_code"))),
        "remarks": _text(body.get("remarks", existing.get("remarks"))),
        "updated_at": now_utc(),
        "updated_by": user.user_id,
    })
    try:
        await db.materials.update_one({"material_uid": material_uid}, {"$set": values})
    except DuplicateKeyError:
        raise HTTPException(400, "Duplicate normalized material definition")
    if values.get("make") or values.get("model"):
        await _ensure_variant(
            material_uid, values.get("make", ""), values.get("model", ""), material_uid
        )
    await master_audit(
        "material", material_uid, "update", user, reason,
        {k: existing.get(k) for k in values if k in existing}, values,
    )
    return _material_view({**existing, **values}, await _threshold())


@api.post("/admin/material-master/materials/{material_uid}/status")
async def set_material_status(
    material_uid: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    user = await _actor(authorization)
    existing = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Material not found")
    active = bool(body.get("active"))
    reason = _text(body.get("reason")) or ("Activated" if active else "Deactivated")
    updates = {"active": active, "updated_at": now_utc(), "updated_by": user.user_id}
    await db.materials.update_one({"material_uid": material_uid}, {"$set": updates})
    await master_audit(
        "material", material_uid, "activate" if active else "deactivate",
        user, reason, {"active": existing.get("active", True)}, {"active": active},
    )
    return {
        "material_uid": material_uid,
        "active": active,
        "historical_records_retained": True,
    }
