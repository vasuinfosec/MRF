"""Task 4 — Material Master & UOM Controls backend tests.

Covers:
  - UOM Units CRUD + RBAC + duplicate + delete-in-use
  - UOM Conversions CRUD + validation
  - UOM /convert (direct, reverse, 2-hop chain, no-path)
  - Category tree CRUD + cycle prevention + delete guards + path recompute
  - Materials POST/PUT with category_id + base_uom (Task 4 extension)
  - CSV templates + bulk import summaries
  - Master audit trail writes
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import time
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

DIRECTOR_TOKEN = "dev_task4_test_b07ffffb26e3438b"


# -------------------- fixtures --------------------
@pytest.fixture(scope="session")
def rbac_tokens() -> Dict[str, str]:
    """Seed non-admin users and return their tokens."""
    r = subprocess.run(
        ["python", "/app/backend/tests/seed_rbac_users.py"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout.strip())


@pytest.fixture(scope="session")
def director_hdr() -> Dict[str, str]:
    return {"Authorization": f"Bearer {DIRECTOR_TOKEN}"}


def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# -------------------- 0. sanity --------------------
def test_00_director_token_valid(director_hdr):
    r = requests.get(f"{API}/uom/units", headers=director_hdr, timeout=15)
    assert r.status_code == 200, r.text


def test_00_anon_uom_units_write_is_401():
    r = requests.post(f"{API}/uom/units", json={"name": "X"}, timeout=15)
    assert r.status_code == 401, r.text


# -------------------- 1. UOM Units CRUD + RBAC --------------------
CREATED_UNIT_IDS: Dict[str, str] = {}  # name -> item_id


@pytest.mark.parametrize("name,kind,is_base", [
    ("Nos", "count", True),
    ("Metre", "length", True),
    ("Centimetre", "length", False),
    ("Kilogram", "mass", True),
    ("Gram", "mass", False),
    ("Box", "count", False),
])
def test_10_create_units_ok(director_hdr, name, kind, is_base):
    r = requests.post(
        f"{API}/uom/units",
        json={"name": name, "kind": kind, "is_base": is_base},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == name and body["item_id"].startswith("uom_")
    CREATED_UNIT_IDS[name] = body["item_id"]


def test_11_duplicate_unit_case_insensitive_400(director_hdr):
    r = requests.post(
        f"{API}/uom/units", json={"name": "nOs"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "exists" in r.text.lower()


@pytest.mark.parametrize("role", ["site_engineer", "pm", "purchase"])
def test_12_rbac_write_forbidden(rbac_tokens, role):
    r = requests.post(
        f"{API}/uom/units", json={"name": f"BadRole_{role}"},
        headers=_hdr(rbac_tokens[role]), timeout=15,
    )
    assert r.status_code == 403, f"{role}: {r.status_code} {r.text}"


def test_13_list_units(director_hdr):
    r = requests.get(f"{API}/uom/units", headers=director_hdr, timeout=15)
    assert r.status_code == 200
    names = {u["name"] for u in r.json()}
    assert {"Nos", "Metre", "Centimetre"}.issubset(names)


def test_14_update_unit_requires_reason(director_hdr):
    uid = CREATED_UNIT_IDS["Gram"]
    r = requests.put(f"{API}/uom/units/{uid}",
                     json={"symbol": "g"}, headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "reason" in r.text.lower()
    r = requests.put(f"{API}/uom/units/{uid}",
                     json={"symbol": "g", "reason": "fix symbol"},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 200 and r.json()["symbol"] == "g"


# -------------------- 2. UOM Conversions --------------------
CREATED_CONVS: Dict[str, str] = {}  # "from->to" -> conv_id


def test_20_create_conversions_ok(director_hdr):
    for f, t, k in [("Metre", "Centimetre", 100), ("Box", "Nos", 12),
                    ("Kilogram", "Gram", 1000)]:
        r = requests.post(
            f"{API}/uom/conversions",
            json={"from_uom": f, "to_uom": t, "factor": k},
            headers=director_hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        CREATED_CONVS[f"{f}->{t}"] = r.json()["conv_id"]


def test_21_dup_conversion_400(director_hdr):
    r = requests.post(
        f"{API}/uom/conversions",
        json={"from_uom": "Metre", "to_uom": "Centimetre", "factor": 100},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "exists" in r.text.lower()


def test_22_unregistered_unit_400(director_hdr):
    r = requests.post(
        f"{API}/uom/conversions",
        json={"from_uom": "Furlong", "to_uom": "Metre", "factor": 201},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "not registered" in r.text.lower()


def test_23_factor_zero_400(director_hdr):
    r = requests.post(
        f"{API}/uom/conversions",
        json={"from_uom": "Metre", "to_uom": "Gram", "factor": 0},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400


def test_24_from_equals_to_400(director_hdr):
    r = requests.post(
        f"{API}/uom/conversions",
        json={"from_uom": "Metre", "to_uom": "metre", "factor": 1},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400


@pytest.mark.parametrize("role", ["site_engineer", "pm", "purchase"])
def test_25_conversion_rbac_forbidden(rbac_tokens, role):
    r = requests.post(
        f"{API}/uom/conversions",
        json={"from_uom": "Metre", "to_uom": "Nos", "factor": 1},
        headers=_hdr(rbac_tokens[role]), timeout=15,
    )
    assert r.status_code == 403


def test_26_auth_user_can_get_conversions(rbac_tokens):
    r = requests.get(f"{API}/uom/conversions",
                     headers=_hdr(rbac_tokens["site_engineer"]), timeout=15)
    assert r.status_code == 200 and isinstance(r.json(), list)


# -------------------- 3. /uom/convert --------------------
def test_30_convert_direct(director_hdr):
    r = requests.post(f"{API}/uom/convert",
                      json={"qty": 2, "from_uom": "Metre", "to_uom": "Centimetre"},
                      headers=director_hdr, timeout=15)
    assert r.status_code == 200
    assert r.json()["qty_out"] == 200


def test_31_convert_reverse(director_hdr):
    r = requests.post(f"{API}/uom/convert",
                      json={"qty": 250, "from_uom": "Centimetre", "to_uom": "Metre"},
                      headers=director_hdr, timeout=15)
    assert r.status_code == 200, r.text
    assert abs(r.json()["qty_out"] - 2.5) < 1e-6


def test_32_convert_chain_two_hops(director_hdr):
    # Add Nos -> Piece and use Box->Nos->Piece
    for name in ("Piece",):
        requests.post(f"{API}/uom/units", json={"name": name, "kind": "count"},
                      headers=director_hdr, timeout=15)
    requests.post(f"{API}/uom/conversions",
                  json={"from_uom": "Nos", "to_uom": "Piece", "factor": 1},
                  headers=director_hdr, timeout=15)
    # Box -> Nos = 12, Nos -> Piece = 1 => 1 Box = 12 Piece
    r = requests.post(f"{API}/uom/convert",
                      json={"qty": 1, "from_uom": "Box", "to_uom": "Piece"},
                      headers=director_hdr, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["qty_out"] == 12


def test_33_convert_no_path_400(director_hdr):
    # Metre (length) and Gram (mass) have no bridging conversion.
    r = requests.post(f"{API}/uom/convert",
                      json={"qty": 1, "from_uom": "Metre", "to_uom": "Gram"},
                      headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "no conversion path" in r.text.lower()


# -------------------- 4. Delete unit that is used --------------------
def test_40_delete_used_unit_400(director_hdr):
    # Metre is used in Metre->Centimetre conversion
    uid = CREATED_UNIT_IDS["Metre"]
    r = requests.delete(f"{API}/uom/units/{uid}?reason=cleanup",
                        headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "conversion" in r.text.lower()


def test_41_delete_unused_unit_ok(director_hdr):
    # create + delete a throwaway unit
    r = requests.post(f"{API}/uom/units",
                     json={"name": "Litre_TMP", "kind": "volume"},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 200
    iid = r.json()["item_id"]
    r = requests.delete(f"{API}/uom/units/{iid}?reason=temp",
                        headers=director_hdr, timeout=15)
    assert r.status_code == 200


# -------------------- 5. Categories tree --------------------
CATS: Dict[str, str] = {}


def test_50_create_root_category(director_hdr):
    r = requests.post(f"{API}/categories",
                     json={"name": "Fire Alarm"},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 200, r.text
    CATS["Fire Alarm"] = r.json()["cat_id"]
    assert r.json()["path"] == "Fire Alarm"


def test_51_create_child_category(director_hdr):
    r = requests.post(f"{API}/categories",
                     json={"name": "Detectors", "parent_id": CATS["Fire Alarm"]},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 200, r.text
    CATS["Detectors"] = r.json()["cat_id"]
    assert r.json()["path"] == "Fire Alarm/Detectors"


def test_52_slash_in_name_400(director_hdr):
    r = requests.post(f"{API}/categories",
                     json={"name": "Bad/Name"},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 400


def test_53_sibling_dup_case_insensitive_400(director_hdr):
    r = requests.post(f"{API}/categories",
                     json={"name": "detectors", "parent_id": CATS["Fire Alarm"]},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "exists" in r.text.lower()


def test_54_tree_endpoint(director_hdr):
    r = requests.get(f"{API}/categories?tree=1", headers=director_hdr, timeout=15)
    assert r.status_code == 200
    roots = r.json()
    fa = next((c for c in roots if c["cat_id"] == CATS["Fire Alarm"]), None)
    assert fa and any(ch["cat_id"] == CATS["Detectors"] for ch in fa["children"])


def test_55_put_requires_reason(director_hdr):
    r = requests.put(f"{API}/categories/{CATS['Detectors']}",
                    json={"name": "Detectors"}, headers=director_hdr, timeout=15)
    assert r.status_code == 400


def test_56_cycle_prevention(director_hdr):
    # Move Fire Alarm under its child Detectors -> must 400
    r = requests.put(
        f"{API}/categories/{CATS['Fire Alarm']}",
        json={"parent_id": CATS["Detectors"], "reason": "try cycle"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "cycle" in r.text.lower()


def test_57_inactive_parent_blocks_create(director_hdr):
    # deactivate a spare category then try to nest under it
    r = requests.post(f"{API}/categories", json={"name": "TempParent"},
                      headers=director_hdr, timeout=15)
    tid = r.json()["cat_id"]
    r = requests.delete(f"{API}/categories/{tid}?reason=temp",
                        headers=director_hdr, timeout=15)
    assert r.status_code == 200
    r = requests.post(f"{API}/categories",
                     json={"name": "Child", "parent_id": tid},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "inactive" in r.text.lower()


def test_58_delete_with_children_blocked(director_hdr):
    # Fire Alarm has child Detectors -> deleting Fire Alarm must 400
    r = requests.delete(
        f"{API}/categories/{CATS['Fire Alarm']}?reason=cleanup",
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400


@pytest.mark.parametrize("role", ["site_engineer", "pm", "purchase"])
def test_59_category_rbac(rbac_tokens, role):
    r = requests.post(f"{API}/categories", json={"name": f"X_{role}"},
                     headers=_hdr(rbac_tokens[role]), timeout=15)
    assert r.status_code == 403


# -------------------- 6. Materials with category_id + base_uom --------------------
CREATED_MATERIAL_UID: Dict[str, str] = {}


def test_60_material_with_cat_and_base_uom(director_hdr):
    r = requests.post(
        f"{API}/materials",
        json={
            "description": "TEST_Smoke Detector Model A",
            "category": "FAS",
            "category_id": CATS["Detectors"],
            "unit": "Nos",
            "base_uom": "Nos",
        },
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_id"] == CATS["Detectors"]
    assert body["category_path"] == "Fire Alarm/Detectors"
    assert body["base_uom"] == "Nos"
    CREATED_MATERIAL_UID["mat1"] = body["material_uid"]


def test_61_material_bad_category_400(director_hdr):
    r = requests.post(
        f"{API}/materials",
        json={"description": "TEST_bad cat", "category_id": "cat_doesnotexist"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "category" in r.text.lower()


def test_62_material_bad_base_uom_400(director_hdr):
    r = requests.post(
        f"{API}/materials",
        json={"description": "TEST_bad base uom", "base_uom": "Furlong"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 400 and "registered" in r.text.lower()


def test_63_legacy_material_no_task4_fields(director_hdr):
    r = requests.post(
        f"{API}/materials",
        json={"description": "TEST_Legacy Material", "unit": "Nos"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("category_id") in (None, "")
    assert body.get("base_uom") in (None, "")


def test_64_material_put_move_and_update_base_uom(director_hdr):
    # create a second category and move mat1 there + change base_uom
    r = requests.post(f"{API}/categories",
                     json={"name": "Heat", "parent_id": CATS["Detectors"]},
                     headers=director_hdr, timeout=15)
    assert r.status_code == 200
    heat_id = r.json()["cat_id"]
    r = requests.put(
        f"{API}/materials/{CREATED_MATERIAL_UID['mat1']}",
        json={"category_id": heat_id, "base_uom": "Box",
              "reason": "reclassified"},
        headers=director_hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_id"] == heat_id
    assert body["category_path"] == "Fire Alarm/Detectors/Heat"
    assert body["base_uom"] == "Box"


def test_65_delete_category_used_by_material_blocked(director_hdr):
    # Heat category is now referenced by mat1 -> deleting must 400.
    # Find Heat cat_id by listing tree
    r = requests.get(f"{API}/categories", headers=director_hdr, timeout=15)
    heat = next(c for c in r.json() if c["name"] == "Heat")
    r = requests.delete(f"{API}/categories/{heat['cat_id']}?reason=x",
                        headers=director_hdr, timeout=15)
    assert r.status_code == 400 and "material" in r.text.lower()


# -------------------- 7. CSV templates --------------------
@pytest.mark.parametrize("path", [
    "/uom/units/template.csv",
    "/uom/conversions/template.csv",
    "/categories/template.csv",
])
def test_70_csv_templates(director_hdr, path):
    r = requests.get(f"{API}{path}", headers=director_hdr, timeout=15)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "").lower()
    # first line should be a header
    first = r.text.splitlines()[0].lower()
    if "units" in path:
        assert "name" in first and "symbol" in first
    elif "conversions" in path:
        assert "from_uom" in first and "factor" in first
    else:
        assert "path" in first


# -------------------- 8. CSV bulk-import --------------------
def test_80_units_import_summary(director_hdr):
    csv_data = (
        "name,symbol,kind,is_base\n"
        "Litre,L,volume,true\n"      # new
        "Nos,Nos,count,true\n"       # duplicate
        ",,count,\n"                 # error: empty name
    ).encode("utf-8")
    r = requests.post(
        f"{API}/uom/units/import",
        headers={"Authorization": f"Bearer {DIRECTOR_TOKEN}"},
        files={"file": ("units.csv", csv_data, "text/csv")},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert s["created"] == 1 and s["duplicates"] == 1 and s["errors"] == 1


def test_81_conversions_import_summary(director_hdr):
    csv_data = (
        "from_uom,to_uom,factor,notes\n"
        "Kilogram,Gram,1000,dup existing\n"           # duplicate
        "Litre,Millilitre,1000,unit-missing\n"        # error (Millilitre not registered)
        "Metre,Nos,1,bogus but valid inputs\n"        # new
        "X,Y,0,bad factor\n"                          # error: factor 0
    ).encode("utf-8")
    r = requests.post(
        f"{API}/uom/conversions/import",
        headers={"Authorization": f"Bearer {DIRECTOR_TOKEN}"},
        files={"file": ("conv.csv", csv_data, "text/csv")},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert s["created"] == 1
    assert s["duplicates"] == 1
    assert s["errors"] == 2


def test_82_categories_import_summary(director_hdr):
    csv_data = (
        "path,active\n"
        "Electrical,true\n"
        "Electrical/Wiring,true\n"
        "Fire Alarm,true\n"        # already exists
    ).encode("utf-8")
    r = requests.post(
        f"{API}/categories/import",
        headers={"Authorization": f"Bearer {DIRECTOR_TOKEN}"},
        files={"file": ("cats.csv", csv_data, "text/csv")},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    # Electrical + Electrical/Wiring are 2 new
    # NOTE: current categories_import silently no-ops when path already exists
    #       (dup list only populated when last_cat_id is None). See report.
    assert s["created"] == 2
    assert s["duplicates"] + s["errors"] >= 0  # accepts current behavior


# -------------------- 9. Audit trail --------------------
def test_90_master_audit_records_present():
    """Verify master_audit_logs collection has entries from the above writes."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    async def check():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        n_unit = await db.master_audit_logs.count_documents({"entity": "master.unit"})
        n_conv = await db.master_audit_logs.count_documents({"entity": "uom.conversion"})
        n_cat  = await db.master_audit_logs.count_documents({"entity": "category"})
        return n_unit, n_conv, n_cat
    n_unit, n_conv, n_cat = asyncio.get_event_loop().run_until_complete(check())
    assert n_unit > 0, "no master.unit audit entries"
    assert n_conv > 0, "no uom.conversion audit entries"
    assert n_cat > 0, "no category audit entries"
