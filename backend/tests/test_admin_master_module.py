"""
Iteration 11 — Admin Master Module (Customers, Customer POs, Masters,
Projects/Vendors reason-enforcement, Master Audit).

Backend-only regression per review request. Uses dev-login for auth.
Fresh IDs (ACME-01, CAS-1, GST 18% Std, XC500, etc.) — does NOT wipe seed data.
"""

import os
import uuid
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://purchase-workflow-10.preview.emergentagent.com"
).rstrip("/")

API = f"{BASE_URL}/api"

VALID_ROLES = ["director", "gm", "pm", "purchase", "site_engineer", "store", "admin"]


# ---------------- Fixtures ----------------

def _login(email: str, role: str, name: str) -> str:
    r = requests.post(
        f"{API}/auth/dev-login",
        json={"email": email, "role": role, "name": name},
        timeout=15,
    )
    assert r.status_code == 200, f"dev-login failed for {role}: {r.status_code} {r.text}"
    return r.json()["session_token"]


def _h(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login("admin@vasu.dev", "admin", "Admin"),
        "director": _login("director@vasu.dev", "director", "Director"),
        "gm": _login("gm@vasu.dev", "gm", "GM"),
        "pm": _login("pm@vasu.dev", "pm", "PM"),
        "purchase": _login("purchase@vasu.dev", "purchase", "Purchase"),
        "site_engineer": _login("siteeng@vasu.dev", "site_engineer", "SE"),
        "store": _login("store@vasu.dev", "store", "Store"),
    }


@pytest.fixture(scope="module")
def state():
    """Shared bag across tests (customer/po IDs)."""
    return {}


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


# ============================================================
# Customer CRUD (cases 1-9)
# ============================================================
class TestCustomerCRUD:

    def test_01_admin_create_ACME_01(self, tokens, state):
        cid = _uid("ACME")
        name = f"Acme Ltd {cid}"
        state["acme_cid"] = cid
        state["acme_name"] = name
        r = requests.post(f"{API}/customers", headers=_h(tokens["admin"]),
                          json={"customer_id": cid, "name": name, "gstin": "27AACCA0000A1Z5",
                                "pan": "AACCA0000A", "billing_address": "Pune",
                                "shipping_address": "Pune", "contact_person": "PoC",
                                "phone": "9999999999", "email": "acme@example.com",
                                "remarks": "test"})
        assert r.status_code == 200, r.text
        assert r.json()["customer_id"] == cid
        assert r.json()["name"] == name

    def test_02_duplicate_id_case_insensitive_400(self, tokens, state):
        cid_lower = state["acme_cid"].lower()
        r = requests.post(f"{API}/customers", headers=_h(tokens["admin"]),
                          json={"customer_id": cid_lower, "name": "Different Name"})
        assert r.status_code == 400, r.text

    def test_03_invalid_id_has_spaces_400(self, tokens):
        r = requests.post(f"{API}/customers", headers=_h(tokens["admin"]),
                          json={"customer_id": "has spaces", "name": "X Co"})
        assert r.status_code == 400, r.text

    def test_04_director_create_DIR_CUST_01(self, tokens, state):
        cid = _uid("DIR-CUST")
        state["dir_cust_cid"] = cid
        r = requests.post(f"{API}/customers", headers=_h(tokens["director"]),
                          json={"customer_id": cid, "name": f"Director Made {cid}"})
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("role", ["pm", "purchase", "site_engineer"])
    def test_05_non_admin_director_forbidden(self, tokens, role):
        r = requests.post(f"{API}/customers", headers=_h(tokens[role]),
                          json={"customer_id": _uid("BAD"), "name": "no"})
        assert r.status_code == 403, f"{role} expected 403 got {r.status_code}: {r.text}"

    def test_06_put_without_reason_400(self, tokens, state):
        r = requests.put(f"{API}/customers/{state['acme_cid']}",
                         headers=_h(tokens["admin"]),
                         json={"name": "Acme Limited"})
        assert r.status_code == 400, r.text

    def test_07_put_with_reason_and_audit(self, tokens, state):
        new_name = f"Acme Limited {state['acme_cid']}"
        r = requests.put(f"{API}/customers/{state['acme_cid']}",
                         headers=_h(tokens["admin"]),
                         json={"name": new_name, "reason": "corporate rename"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == new_name

        # audit entry
        a = requests.get(f"{API}/master-audit",
                         headers=_h(tokens["admin"]),
                         params={"entity": "customer",
                                 "entity_id": state["acme_cid"]})
        assert a.status_code == 200, a.text
        entries = a.json()
        assert any(e.get("action") == "update" and e.get("reason") == "corporate rename"
                   for e in entries), f"no update audit: {entries}"

    def test_08_rename_customer_id_and_cascade(self, tokens, state):
        new_cid = _uid("ACME-NEW")
        state["acme_new_cid"] = new_cid
        r = requests.put(f"{API}/customers/{state['acme_cid']}",
                         headers=_h(tokens["admin"]),
                         json={"customer_id": new_cid, "reason": "rebrand ID"})
        assert r.status_code == 200, r.text

        # old ID gone
        r_old = requests.get(f"{API}/customers/{state['acme_cid']}",
                             headers=_h(tokens["admin"]))
        assert r_old.status_code == 404, r_old.text

        # new ID present
        r_new = requests.get(f"{API}/customers/{new_cid}",
                             headers=_h(tokens["admin"]))
        assert r_new.status_code == 200, r_new.text

    def test_09_get_new_id_has_customer_pos_list(self, tokens, state):
        r = requests.get(f"{API}/customers/{state['acme_new_cid']}",
                         headers=_h(tokens["admin"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "customer_pos" in body and isinstance(body["customer_pos"], list)
        assert body["customer_pos"] == []


# ============================================================
# Cascade test (case 10)
# ============================================================
class TestCustomerRenameCascade:

    def test_10_project_customer_id_cascades_on_rename(self, tokens, state):
        cas1 = _uid("CAS")
        state["cas1"] = cas1
        # create customer
        r = requests.post(f"{API}/customers", headers=_h(tokens["admin"]),
                          json={"customer_id": cas1, "name": f"Cascade Co {cas1}"})
        assert r.status_code == 200, r.text

        # create project linked to CAS-1
        pid = _uid("PRJ")
        state["cas_pid"] = pid
        rp = requests.post(f"{API}/projects", headers=_h(tokens["admin"]),
                           json={"project_id": pid,
                                 "code": pid, "name": f"Proj {pid}",
                                 "site": "Site A", "customer_id": cas1})
        assert rp.status_code == 200, rp.text
        assert rp.json()["customer_id"] == cas1

        # rename cas1 -> cas2
        cas2 = _uid("CAS")
        state["cas2"] = cas2
        rr = requests.put(f"{API}/customers/{cas1}",
                          headers=_h(tokens["admin"]),
                          json={"customer_id": cas2, "reason": "cascade test"})
        assert rr.status_code == 200, rr.text

        # fetch project — customer_id should be new
        rg = requests.get(f"{API}/projects", headers=_h(tokens["admin"]))
        assert rg.status_code == 200
        proj = next((p for p in rg.json() if p["project_id"] == pid), None)
        assert proj is not None, "project missing"
        assert proj["customer_id"] == cas2, f"cascade failed: {proj}"


# ============================================================
# Customer POs (cases 11-15)
# ============================================================
class TestCustomerPOs:

    def test_11_admin_add_cpo(self, tokens, state):
        cid = state["acme_new_cid"]
        r = requests.post(f"{API}/customers/{cid}/pos",
                          headers=_h(tokens["admin"]),
                          json={"po_number": "PO/2026/001",
                                "po_date": "2026-06-15", "value": 100000})
        assert r.status_code == 200, r.text
        assert r.json()["customer_id"] == cid
        assert r.json()["po_number"] == "PO/2026/001"
        state["cpo1"] = r.json()["cpo_id"]

    def test_12_purchase_add_cpo(self, tokens, state):
        cid = state["acme_new_cid"]
        r = requests.post(f"{API}/customers/{cid}/pos",
                          headers=_h(tokens["purchase"]),
                          json={"po_number": "PO/2026/002",
                                "po_date": "2026-07-01", "value": 50000})
        assert r.status_code == 200, r.text
        state["cpo2"] = r.json()["cpo_id"]

    def test_13_se_add_cpo_forbidden(self, tokens, state):
        cid = state["acme_new_cid"]
        r = requests.post(f"{API}/customers/{cid}/pos",
                          headers=_h(tokens["site_engineer"]),
                          json={"po_number": "PO/2026/003", "value": 10000})
        assert r.status_code == 403, r.text

    def test_14_admin_put_cpo_change_value(self, tokens, state):
        cid = state["acme_new_cid"]
        cpo = state["cpo1"]
        r = requests.put(f"{API}/customers/{cid}/pos/{cpo}",
                         headers=_h(tokens["admin"]),
                         json={"value": 150000})
        assert r.status_code == 200, r.text
        assert float(r.json()["value"]) == 150000.0

    def test_15_admin_get_attachment_404_when_absent(self, tokens, state):
        cid = state["acme_new_cid"]
        cpo = state["cpo1"]
        r = requests.get(f"{API}/customers/{cid}/pos/{cpo}/attachment",
                         headers=_h(tokens["admin"]))
        assert r.status_code == 404, r.text


# ============================================================
# Masters (cases 16-23)
# ============================================================
class TestMasters:

    def test_16_add_gst_master(self, tokens, state):
        name = f"TEST GST 18% Std {uuid.uuid4().hex[:4]}"
        state["gst_name"] = name
        r = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                          json={"name": name, "category": "gst", "value": "18"})
        assert r.status_code == 200, r.text
        state["gst_item_id"] = r.json()["item_id"]

    def test_17_duplicate_gst_name_400(self, tokens, state):
        r = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                          json={"name": state["gst_name"], "category": "gst", "value": "18"})
        assert r.status_code == 400, r.text

    def test_18_gst_nonnumeric_value_400(self, tokens):
        r = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                          json={"name": f"TEST GST bad {uuid.uuid4().hex[:4]}",
                                "category": "gst", "value": "eighteen"})
        assert r.status_code == 400, r.text

    def test_19_department_master(self, tokens):
        name = f"TEST Purchase Dept {uuid.uuid4().hex[:4]}"
        r = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                          json={"name": name, "category": "department"})
        # duplicate against seed acceptable
        assert r.status_code in (200, 400), r.text

    def test_20_model_with_parent_brand(self, tokens, state):
        # create a brand first
        brand_name = f"TEST Brand {uuid.uuid4().hex[:4]}"
        rb = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                           json={"name": brand_name, "category": "brand"})
        assert rb.status_code == 200, rb.text
        brand_id = rb.json()["item_id"]
        state["brand_id"] = brand_id

        model_name = f"XC500-{uuid.uuid4().hex[:4]}"
        rm = requests.post(f"{API}/masters", headers=_h(tokens["admin"]),
                           json={"name": model_name, "category": "model",
                                 "parent_id": brand_id})
        assert rm.status_code == 200, rm.text
        assert rm.json()["parent_id"] == brand_id
        state["model_item_id"] = rm.json()["item_id"]

    def test_21_put_master_without_reason_400(self, tokens, state):
        r = requests.put(f"{API}/masters/{state['gst_item_id']}",
                         headers=_h(tokens["admin"]),
                         json={"value": "18"})
        assert r.status_code == 400, r.text

    def test_22_put_master_with_reason_and_audit(self, tokens, state):
        r = requests.put(f"{API}/masters/{state['gst_item_id']}",
                         headers=_h(tokens["admin"]),
                         json={"value": "18", "reason": "clarify GST"})
        assert r.status_code == 200, r.text
        # audit
        a = requests.get(f"{API}/master-audit",
                         headers=_h(tokens["admin"]),
                         params={"entity_id": state["gst_item_id"]})
        assert a.status_code == 200
        assert any(e.get("action") == "update" and e.get("reason") == "clarify GST"
                   for e in a.json()), a.json()

    def test_23_se_post_master_forbidden(self, tokens):
        r = requests.post(f"{API}/masters", headers=_h(tokens["site_engineer"]),
                          json={"name": "TEST X", "category": "unit"})
        assert r.status_code == 403, r.text


# ============================================================
# Project & Vendor reason enforcement (cases 24-26)
# ============================================================
class TestProjectVendorReason:

    def test_24_project_put_without_reason_400(self, tokens, state):
        pid = state["cas_pid"]
        r = requests.put(f"{API}/projects/{pid}",
                         headers=_h(tokens["admin"]),
                         json={"name": "renamed"})
        assert r.status_code == 400, r.text

    def test_25_project_put_with_unknown_customer_400(self, tokens, state):
        pid = state["cas_pid"]
        r = requests.put(f"{API}/projects/{pid}",
                         headers=_h(tokens["admin"]),
                         json={"customer_id": "GHOST", "reason": "try ghost"})
        assert r.status_code == 400, r.text

    def test_26_vendor_put_without_reason_400(self, tokens):
        # first create a vendor to update
        vname = f"TEST Vendor {uuid.uuid4().hex[:4]}"
        rc = requests.post(f"{API}/vendors", headers=_h(tokens["admin"]),
                           json={"name": vname})
        assert rc.status_code == 200, rc.text
        vid = rc.json()["vendor_id"]
        r = requests.put(f"{API}/vendors/{vid}",
                         headers=_h(tokens["admin"]),
                         json={"name": vname + " X"})
        assert r.status_code == 400, r.text


# ============================================================
# Master audit (cases 27-30)
# ============================================================
class TestMasterAudit:

    def test_27_admin_get_master_audit(self, tokens):
        r = requests.get(f"{API}/master-audit", headers=_h(tokens["admin"]))
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 3, f"expected >=3 audit entries, got {len(r.json())}"

    def test_28_director_get_master_audit(self, tokens):
        r = requests.get(f"{API}/master-audit", headers=_h(tokens["director"]))
        assert r.status_code == 200, r.text

    def test_29_se_get_master_audit_403(self, tokens):
        r = requests.get(f"{API}/master-audit", headers=_h(tokens["site_engineer"]))
        assert r.status_code == 403, r.text

    def test_30_filter_by_entity_customer(self, tokens):
        r = requests.get(f"{API}/master-audit",
                         headers=_h(tokens["admin"]),
                         params={"entity": "customer"})
        assert r.status_code == 200, r.text
        entries = r.json()
        assert entries, "expected at least one customer audit entry"
        assert all(e["entity"] == "customer" for e in entries), \
            "filter leaked non-customer entries"
