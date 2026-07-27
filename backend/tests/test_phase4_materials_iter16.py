"""
Phase 4 regression — Material Master (MAT-####) + Variants (VAR-####) + Bulk Import.
Iteration 16 backend testing.

All endpoints hit the public preview URL via /api prefix. Uses dev-login
(gated by ENABLE_DEV_LOGIN=1) to obtain session tokens for each role.
"""

import os
import re
import time
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
             or os.environ.get("EXPO_BACKEND_URL")
             or "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")

ROLE_EMAILS = {
    "director": "director@vasu.dev",
    "gm": "gm@vasu.dev",
    "pm": "pm@vasu.dev",
    "purchase": "purchase@vasu.dev",
    "site_engineer": "siteeng@vasu.dev",
    "admin": "admin@vasu.dev",
}


def _login(role: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/dev-login",
        json={"email": ROLE_EMAILS[role], "role": role, "name": f"{role.title()} Test"},
        timeout=30,
    )
    assert r.status_code == 200, f"dev-login failed for {role}: {r.status_code} {r.text}"
    return r.json()["session_token"]


def _hdr(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- module-scoped fixtures ---
@pytest.fixture(scope="module")
def tokens():
    # Ensure users exist (idempotent seed).
    # First seed may not require auth if empty; try unauthenticated then admin.
    r = requests.post(f"{BASE_URL}/api/seed", timeout=60)
    if r.status_code == 403:
        # need admin — login as admin (already seeded)
        pass
    toks = {role: _login(role) for role in ROLE_EMAILS}
    # Reseed idempotency call
    r2 = requests.post(f"{BASE_URL}/api/seed", headers=_hdr(toks["admin"]), timeout=60)
    assert r2.status_code == 200, f"admin reseed failed: {r2.status_code} {r2.text}"
    return toks


# =====================================================================
# Migration
# =====================================================================
class TestMigration:
    def test_01_seed_idempotent_material_count(self, tokens):
        # Count materials before extra seed
        r1 = requests.get(f"{BASE_URL}/api/materials?status=all", headers=_hdr(tokens["admin"]))
        assert r1.status_code == 200
        before = len(r1.json())

        r_seed = requests.post(f"{BASE_URL}/api/seed", headers=_hdr(tokens["admin"]), timeout=60)
        assert r_seed.status_code == 200

        r2 = requests.get(f"{BASE_URL}/api/materials?status=all", headers=_hdr(tokens["admin"]))
        assert r2.status_code == 200
        after = len(r2.json())
        assert after == before, f"Materials doubled after re-seed: {before} -> {after}"

    def test_02_materials_have_uid_and_approved_status(self, tokens):
        r = requests.get(f"{BASE_URL}/api/materials", headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        mats = r.json()
        assert isinstance(mats, list) and len(mats) > 0
        uid_rx = re.compile(r"^MAT-\d{4}$")
        for m in mats:
            assert uid_rx.match(m["material_uid"]), f"bad UID: {m.get('material_uid')}"
            assert m["status"] == "approved"


# =====================================================================
# Create material
# =====================================================================
class TestCreateMaterial:
    def test_03_purchase_create_pending(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={
                "description": "Regression Test Mat 1",
                "category": "Fire Alarm",
                "unit": "Nos",
                "gst_rate": 18,
                "item_code": "RT1",
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "pending_pm_review"
        assert re.match(r"^MAT-\d{4}$", d["material_uid"])
        pytest.mat_created_uid_1 = d["material_uid"]

    def test_04_admin_create_bypass_approved(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["admin"]),
            json={
                "description": "Regression Test Mat 2 (admin bypass)",
                "category": "CCTV",
                "unit": "Nos",
                "gst_rate": 18,
                "item_code": "RT2",
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "approved"

    def test_05_site_engineer_forbidden(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["site_engineer"]),
            json={"description": "SE Attempted Mat", "unit": "Nos"},
        )
        assert r.status_code == 403

    def test_06_duplicate_description_case_insensitive(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": "REGRESSION test mat 1", "unit": "Nos"},
        )
        assert r.status_code == 400
        assert "already exists" in r.text.lower()

    def test_07_word_limit_exceeded(self, tokens):
        long_desc = " ".join([f"word{i}" for i in range(105)])
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": long_desc, "unit": "Nos"},
        )
        assert r.status_code == 400
        assert "exceeds 100 words" in r.text.lower() or "exceeds" in r.text.lower()


# =====================================================================
# PM review flow
# =====================================================================
class TestPMReview:
    def test_08_pm_approve_pending(self, tokens):
        # Create fresh pending
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": "Regression Test Mat PM-Approve", "unit": "Nos"},
        )
        assert r.status_code == 200
        uid = r.json()["material_uid"]

        r2 = requests.post(
            f"{BASE_URL}/api/materials/{uid}/action",
            headers=_hdr(tokens["pm"]),
            json={"action": "approve", "reason": "OK"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "approved"
        pytest.mat_pm_approved_uid = uid

    def test_09_pm_action_on_approved_400(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/materials/{pytest.mat_pm_approved_uid}/action",
            headers=_hdr(tokens["pm"]),
            json={"action": "approve", "reason": "again"},
        )
        assert r.status_code == 400

    def test_10_purchase_action_forbidden(self, tokens):
        # New pending material
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": "Regression Test Mat Purchase-Action", "unit": "Nos"},
        )
        uid = r.json()["material_uid"]
        r2 = requests.post(
            f"{BASE_URL}/api/materials/{uid}/action",
            headers=_hdr(tokens["purchase"]),
            json={"action": "approve", "reason": "no"},
        )
        assert r2.status_code == 403

    def test_11_bulk_action_pm(self, tokens):
        uids = []
        for i in range(3):
            r = requests.post(
                f"{BASE_URL}/api/materials",
                headers=_hdr(tokens["purchase"]),
                json={"description": f"Regression Bulk Mat {i} {time.time_ns()}", "unit": "Nos"},
            )
            assert r.status_code == 200, r.text
            uids.append(r.json()["material_uid"])
        r2 = requests.post(
            f"{BASE_URL}/api/materials/bulk-action",
            headers=_hdr(tokens["pm"]),
            json={"material_uids": uids, "action": "approve", "reason": "bulk ok"},
        )
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d["ok"] == 3, d
        assert d["skipped"] == 0, d


# =====================================================================
# GM approval on changes
# =====================================================================
class TestGMApproval:
    def test_12_edit_approved_triggers_gm(self, tokens):
        # Use previously PM-approved material
        uid = pytest.mat_pm_approved_uid
        r = requests.put(
            f"{BASE_URL}/api/materials/{uid}",
            headers=_hdr(tokens["purchase"]),
            json={"gst_rate": 12, "reason": "rate correction"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_gm_approval"
        pytest.mat_pending_gm_uid = uid

    def test_13_edit_without_reason_400(self, tokens):
        uid = pytest.mat_pm_approved_uid
        r = requests.put(
            f"{BASE_URL}/api/materials/{uid}",
            headers=_hdr(tokens["purchase"]),
            json={"gst_rate": 5},
        )
        assert r.status_code == 400

    def test_14_gm_approve_change(self, tokens):
        uid = pytest.mat_pending_gm_uid
        r = requests.post(
            f"{BASE_URL}/api/materials/{uid}/gm-approve",
            headers=_hdr(tokens["gm"]),
            json={"action": "approve", "reason": "OK"},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "approved"
        assert d["gst_rate"] == 12

    def test_15_non_gm_gm_approve_forbidden(self, tokens):
        # First get an approved mat into pending_gm_approval again
        uid = pytest.mat_pending_gm_uid
        r_edit = requests.put(
            f"{BASE_URL}/api/materials/{uid}",
            headers=_hdr(tokens["purchase"]),
            json={"gst_rate": 18, "reason": "second edit"},
        )
        assert r_edit.status_code == 200 and r_edit.json()["status"] == "pending_gm_approval"

        r = requests.post(
            f"{BASE_URL}/api/materials/{uid}/gm-approve",
            headers=_hdr(tokens["purchase"]),
            json={"action": "approve", "reason": "nope"},
        )
        assert r.status_code == 403
        # cleanup: GM approves it back
        requests.post(
            f"{BASE_URL}/api/materials/{uid}/gm-approve",
            headers=_hdr(tokens["gm"]),
            json={"action": "approve", "reason": "cleanup"},
        )

    def test_16_admin_edit_immediate_commit(self, tokens):
        # Create a purchase mat, PM approves, then admin edits.
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": f"Regression Admin Edit Mat {time.time_ns()}", "unit": "Nos"},
        )
        uid = r.json()["material_uid"]
        r2 = requests.post(
            f"{BASE_URL}/api/materials/{uid}/action",
            headers=_hdr(tokens["pm"]),
            json={"action": "approve", "reason": "ok"},
        )
        assert r2.status_code == 200 and r2.json()["status"] == "approved"

        r3 = requests.put(
            f"{BASE_URL}/api/materials/{uid}",
            headers=_hdr(tokens["admin"]),
            json={"remarks": "admin edited", "reason": "admin bypass"},
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["status"] == "approved"


# =====================================================================
# Variants
# =====================================================================
class TestVariants:
    def test_17_create_variant(self, tokens):
        # Get any approved material
        r = requests.get(f"{BASE_URL}/api/materials", headers=_hdr(tokens["admin"]))
        approved = [m for m in r.json() if m["status"] == "approved"]
        assert approved, "no approved materials to attach variant to"
        pytest.variant_mat_uid = approved[0]["material_uid"]

        r2 = requests.post(
            f"{BASE_URL}/api/variants",
            headers=_hdr(tokens["purchase"]),
            json={"material_uid": pytest.variant_mat_uid, "make": "Legrand", "model": "XC-500"},
        )
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert re.match(r"^VAR-\d{4}$", d["variant_uid"])
        pytest.variant_uid = d["variant_uid"]

    def test_18_variant_case_insensitive_idempotent(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/variants",
            headers=_hdr(tokens["purchase"]),
            json={"material_uid": pytest.variant_mat_uid, "make": "LEGRAND", "model": "xc-500"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["variant_uid"] == pytest.variant_uid

    def test_19_variant_on_unapproved_400_for_purchase(self, tokens):
        # Create a pending mat
        r = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": f"Regression Variant Pending Mat {time.time_ns()}", "unit": "Nos"},
        )
        uid = r.json()["material_uid"]
        r2 = requests.post(
            f"{BASE_URL}/api/variants",
            headers=_hdr(tokens["purchase"]),
            json={"material_uid": uid, "make": "X", "model": "Y"},
        )
        assert r2.status_code == 400

    def test_20_list_variants_filter(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/variants?material_uid={pytest.variant_mat_uid}",
            headers=_hdr(tokens["purchase"]),
        )
        assert r.status_code == 200
        vs = r.json()
        assert any(v["variant_uid"] == pytest.variant_uid for v in vs)


# =====================================================================
# Bulk import
# =====================================================================
class TestBulkImport:
    def test_21_bulk_import_2_unique_1_dup(self, tokens):
        # First ensure one is a duplicate — create a well-known mat first
        base_desc = f"Regression Import Base {time.time_ns()}"
        r0 = requests.post(
            f"{BASE_URL}/api/materials",
            headers=_hdr(tokens["purchase"]),
            json={"description": base_desc, "unit": "Nos"},
        )
        assert r0.status_code == 200

        rows = [
            {"Material Description": f"Import Unique A {time.time_ns()}", "Category": "Fire Alarm",
             "Make": "Honeywell", "Model": "H1", "Unit": "Nos", "GST Rate %": 18, "Item Code": "IUA"},
            {"Material Description": f"Import Unique B {time.time_ns()}", "Category": "CCTV",
             "Make": "Hikvision", "Model": "K1", "Unit": "Nos", "GST Rate %": 18, "Item Code": "IUB"},
            {"Material Description": base_desc, "Category": "x", "Unit": "Nos"},  # duplicate
        ]
        r = requests.post(
            f"{BASE_URL}/api/import/materials",
            headers=_hdr(tokens["purchase"]),
            json={"rows": rows},
        )
        assert r.status_code == 200, r.text
        s = r.json()["summary"]
        assert s["created"] == 2, s
        assert s["duplicates"] == 1, s

    def test_22_row_word_limit_lands_in_errors_and_needs_correction(self, tokens):
        long_desc = " ".join([f"w{i}" for i in range(101)])
        r = requests.post(
            f"{BASE_URL}/api/import/materials",
            headers=_hdr(tokens["purchase"]),
            json={"rows": [{"Material Description": long_desc, "Unit": "Nos"}]},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["summary"]["errors"] >= 1
        assert d["summary"]["flagged_word_limit"] >= 1
        assert any("101" in str(x.get("reason", "")) or x.get("words") == 101
                   for x in d["errors"] + d["needs_correction"])

    def test_23_site_engineer_bulk_import_forbidden(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/import/materials",
            headers=_hdr(tokens["site_engineer"]),
            json={"rows": [{"Material Description": "SE Attempt", "Unit": "Nos"}]},
        )
        assert r.status_code == 403

    def test_24_empty_rows_400(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/import/materials",
            headers=_hdr(tokens["purchase"]),
            json={"rows": []},
        )
        assert r.status_code == 400

    def test_25_template_download(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/import/materials/template",
            headers={"Authorization": f"Bearer {tokens['purchase']}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert len(r.content) > 4 * 1024, f"size {len(r.content)}B <= 4KB"


# =====================================================================
# Filter/list
# =====================================================================
class TestFilters:
    def test_26_default_returns_approved(self, tokens):
        r = requests.get(f"{BASE_URL}/api/materials", headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200
        for m in r.json():
            assert m["status"] == "approved"

    def test_27_filter_pending(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/materials?status=pending_pm_review",
            headers=_hdr(tokens["pm"]),
        )
        assert r.status_code == 200
        for m in r.json():
            assert m["status"] == "pending_pm_review"

    def test_28_search_q_case_insensitive(self, tokens):
        # Search for "smoke" — matches seeded "Smoke Detector..."
        r = requests.get(
            f"{BASE_URL}/api/materials?status=all&q=smoke",
            headers=_hdr(tokens["pm"]),
        )
        assert r.status_code == 200
        results = r.json()
        # Every result should match one of the fields (description/item_code/material_uid)
        # case-insensitively.
        for m in results:
            hay = (m.get("description", "") + " " + m.get("item_code", "") +
                   " " + m.get("material_uid", "")).lower()
            assert "smoke" in hay, f"unexpected match: {m}"
        # And at least one seeded smoke detector should be present.
        assert any("smoke" in m.get("description", "").lower() for m in results), \
            "expected at least one 'smoke' result"

    def test_29_counts_dict(self, tokens):
        r = requests.get(f"{BASE_URL}/api/materials/counts", headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d, dict)
        # Must sum >0 across statuses given tests we already ran.
        assert sum(d.values()) > 0
        # Keys must be valid statuses
        valid = {"pending_pm_review", "approved", "rejected", "pending_gm_approval", "needs_correction"}
        for k in d.keys():
            assert k in valid, f"unexpected status key: {k}"


# =====================================================================
# Audit
# =====================================================================
class TestAudit:
    def test_30_master_audit_material(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/master-audit?entity=material",
            headers=_hdr(tokens["admin"]),
        )
        assert r.status_code == 200, r.text
        actions = {row.get("action") for row in r.json()}
        expected = {"create", "pm_approve", "edit_requires_gm", "gm_approve", "pm_approve_bulk"}
        missing = expected - actions
        assert not missing, f"missing audit actions: {missing}. Seen: {actions}"
