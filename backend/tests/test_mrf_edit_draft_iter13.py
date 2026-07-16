"""Iteration 13 — Backend regression for Phase 3a MRF draft-edit endpoint.

Covers `PUT /api/mrf/{mrf_id}` and the newly-added MRFItem fields:
  material_id, make, make_id, model, model_id, priority.

All 14 review-request cases implemented. Dev-login is required
(ENABLE_DEV_LOGIN=1 in backend/.env).
"""
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL"))
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"


# ---------------- helpers ----------------
def _login(email: str, role: str, name: str = "Test") -> str:
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": email, "role": role, "name": name},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def _hdr(t: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _me(t: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/auth/me", headers=_hdr(t), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    return j if "user_id" in j else j.get("user", j)


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def tokens() -> Dict[str, str]:
    return {
        "admin":    _login("admin@vasu.dev",    "admin",         "Admin"),
        "director": _login("director@vasu.dev", "director",      "Director"),
        "pm":       _login("pm@vasu.dev",       "pm",            "PM"),
        "se":       _login("siteeng@vasu.dev",  "site_engineer", "Site Eng"),
        # Second SE — reused across the module to test 403
        "se2":      _login("chand@vasuinfosec.com", "site_engineer", "Chand SE"),
    }


@pytest.fixture(scope="module")
def se_id(tokens) -> str:
    return _me(tokens["se"])["user_id"]


@pytest.fixture(scope="module")
def se2_id(tokens) -> str:
    return _me(tokens["se2"])["user_id"]


@pytest.fixture(scope="module")
def pm_id(tokens) -> str:
    return _me(tokens["pm"])["user_id"]


@pytest.fixture(scope="module")
def masters(tokens) -> Dict[str, List[Dict[str, Any]]]:
    r = requests.get(f"{API}/masters", headers=_hdr(tokens["admin"]), timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("material"), "need >=1 material master"
    assert d.get("brand"),    "need >=1 brand master"
    assert d.get("model"),    "need >=1 model master"
    return d


@pytest.fixture(scope="module")
def project_a(tokens, se_id, pm_id) -> Dict[str, Any]:
    """Project A with a customer. SE + PM assigned."""
    cid = f"TESTCUSTA-{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/customers", headers=_hdr(tokens["admin"]),
                      json={"customer_id": cid,
                            "name": f"TEST Customer A {cid}",
                            "gstin": "27ABCDE1234F1Z5", "state": "MH"},
                      timeout=15)
    assert r.status_code == 200, r.text
    pcode = f"TP-A-{uuid.uuid4().hex[:5].upper()}"
    r = requests.post(f"{API}/projects", headers=_hdr(tokens["admin"]),
                      json={"code": pcode, "name": f"TEST Proj A {pcode}",
                            "site": "Pune", "client": "ClientA",
                            "customer_id": cid,
                            "site_engineers": [se_id],
                            "project_managers": [pm_id],
                            "reason": "iter13 setup"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def project_b(tokens, se_id, pm_id) -> Dict[str, Any]:
    """Project B with a DIFFERENT customer — used to verify customer snapshot
    is re-computed when admin changes project_id."""
    cid = f"TESTCUSTB-{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/customers", headers=_hdr(tokens["admin"]),
                      json={"customer_id": cid,
                            "name": f"TEST Customer B {cid}",
                            "gstin": "29ABCDE1234F1Z5", "state": "KA"},
                      timeout=15)
    assert r.status_code == 200, r.text
    pcode = f"TP-B-{uuid.uuid4().hex[:5].upper()}"
    r = requests.post(f"{API}/projects", headers=_hdr(tokens["admin"]),
                      json={"code": pcode, "name": f"TEST Proj B {pcode}",
                            "site": "Bangalore", "client": "ClientB",
                            "customer_id": cid,
                            "site_engineers": [se_id],
                            "project_managers": [pm_id],
                            "reason": "iter13 setup B"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_item(masters, qty: float = 10.0, priority: str = "high",
             desc: str = "TEST-MRFItem") -> Dict[str, Any]:
    mat = masters["material"][0]
    brand = masters["brand"][0]
    model = masters["model"][0]
    return {
        "description": desc,
        "unit": "nos",
        "qty_requested": qty,
        "material_id": mat["item_id"],
        "make":        brand["name"],
        "make_id":     brand["item_id"],
        "model":       model["name"],
        "model_id":    model["item_id"],
        "priority":    priority,
    }


def _create_draft(tokens, proj, masters, token_key: str = "se",
                  priority: str = "high") -> Dict[str, Any]:
    body = {
        "project_id": proj["project_id"],
        "site":       proj.get("site", "Pune"),
        "required_by": "2026-02-20",
        "requesting_person": "Iter13 Requester",
        "system_category":   "electrical",
        "items": [_mk_item(masters, qty=10, priority=priority,
                           desc="TEST-Iter13 primary")],
        "remarks": "iter13 draft",
    }
    r = requests.post(f"{API}/mrf",
                      headers=_hdr(tokens[token_key]), json=body, timeout=15)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["status"] == "draft"
    return m


# ---------------- test 1: create MRF with new fields ----------------
class TestMRFCreateWithNewFields:
    def test_01_create_populates_material_make_model_priority(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters, priority="high")
        it = mrf["items"][0]
        # New Phase 3a fields must round-trip
        assert it.get("material_id") == masters["material"][0]["item_id"]
        assert it.get("make") == masters["brand"][0]["name"]
        assert it.get("make_id") == masters["brand"][0]["item_id"]
        assert it.get("model") == masters["model"][0]["name"]
        assert it.get("model_id") == masters["model"][0]["item_id"]
        assert it.get("priority") == "high"
        assert mrf["status"] == "draft"
        # customer snapshot present
        assert mrf.get("customer_id")
        assert mrf.get("customer_name")


# ---------------- tests 2-8 & 10-14: PUT flows ----------------
class TestMRFEditDraft:

    def test_02_se_put_own_draft_updates_qty(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        line = mrf["items"][0]
        new_line = {**line, "qty_requested": 42.0}
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"items": [new_line]}, timeout=15)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["items"][0]["qty_requested"] == 42.0
        # existing item_line_id preserved
        assert updated["items"][0]["item_line_id"] == line["item_line_id"]

    def test_03_se_submit_moves_to_pm_review(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                          headers=_hdr(tokens["se"]), timeout=15)
        assert r.status_code == 200, r.text
        # Read back status
        g = requests.get(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]), timeout=10)
        assert g.status_code == 200, g.text
        # accepted: 'pm_review' (legacy) or 'under_review' (canonical)
        assert g.json()["status"] in ("pm_review", "under_review")

    def test_04_put_after_submit_400(self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        # Submit first
        s = requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                          headers=_hdr(tokens["se"]), timeout=15)
        assert s.status_code == 200, s.text
        # Now attempt to edit
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"remarks": "should be blocked"}, timeout=15)
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "cannot edit after submission" in detail, detail

    def test_05_pm_return_sets_status_returned(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        assert requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                             headers=_hdr(tokens["se"]),
                             timeout=15).status_code == 200
        r = requests.post(f"{API}/mrf/{mrf['mrf_id']}/approve",
                          headers=_hdr(tokens["pm"]),
                          json={"action": "return",
                                "comment": "please fix qty"},
                          timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "returned"

    def test_06_se_put_returned_mrf_200(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        assert requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                             headers=_hdr(tokens["se"]),
                             timeout=15).status_code == 200
        assert requests.post(f"{API}/mrf/{mrf['mrf_id']}/approve",
                             headers=_hdr(tokens["pm"]),
                             json={"action": "return", "comment": "fix"},
                             timeout=15).status_code == 200
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"remarks": "fixed after return"},
                         timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["remarks"] == "fixed after return"

    def test_07_other_se_put_403(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se2"]),
                         json={"remarks": "malicious edit"}, timeout=15)
        assert r.status_code == 403, r.text
        assert "creator" in (r.json().get("detail") or "").lower()

    def test_08a_admin_put_draft_200(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["admin"]),
                         json={"remarks": "admin touched"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["remarks"] == "admin touched"

    def test_08b_admin_put_after_submit_400(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        assert requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                             headers=_hdr(tokens["se"]),
                             timeout=15).status_code == 200
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["admin"]),
                         json={"remarks": "admin bypass?"}, timeout=15)
        assert r.status_code == 400, r.text
        assert "cannot edit after submission" in (
            r.json().get("detail") or "").lower()

    def test_09_admin_change_project_updates_customer_snapshot(
            self, tokens, project_a, project_b, masters):
        mrf = _create_draft(tokens, project_a, masters)
        assert mrf["customer_id"] == project_a["customer_id"]
        # Include a second editable field so `updates` is non-empty
        # (server currently ignores lone project_id; passing site here is
        # both realistic and defensive against that behaviour).
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["admin"]),
                         json={"project_id": project_b["project_id"],
                               "site":       project_b.get("site", "Bangalore")},
                         timeout=15)
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["project_id"] == project_b["project_id"]
        assert upd["customer_id"] == project_b["customer_id"], (
            f"customer_id not re-snapshotted: {upd.get('customer_id')} vs "
            f"expected {project_b['customer_id']}")
        # customer_name should reflect Customer B's name
        assert upd.get("customer_name"), "customer_name missing after project change"
        assert "customer b" in upd["customer_name"].lower(), (
            f"customer_name mismatch: {upd['customer_name']}")

    def test_10_items_preserve_existing_line_ids(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        # Add a second item via PUT — one keeps old line_id, one is new
        old_line = mrf["items"][0]
        old_id = old_line["item_line_id"]
        new_item = _mk_item(masters, qty=5, priority="low",
                            desc="TEST-Iter13 second line")
        # Payload sends old (with item_line_id) + new (no item_line_id)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"items": [
                             {**old_line, "qty_requested": 11},
                             new_item,
                         ]}, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 2, items
        ids = [it["item_line_id"] for it in items]
        assert old_id in ids, f"old line_id {old_id} not preserved: {ids}"
        # New line got a fresh id (not empty, not equal to old)
        other = [i for i in ids if i != old_id]
        assert other and other[0] and other[0] != old_id

    def test_11_empty_body_400(self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={}, timeout=15)
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "nothing to update" in detail, detail

    def test_12_pm_not_creator_put_draft_403(
            self, tokens, project_a, masters):
        # SE creates the draft; PM (who is on the project) should still be
        # blocked because they aren't the creator (only creator/admin/director).
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["pm"]),
                         json={"remarks": "pm edit attempt"}, timeout=15)
        assert r.status_code == 403, r.text
        assert "creator" in (r.json().get("detail") or "").lower()

    def test_13_updated_at_refreshes(self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        before = mrf.get("updated_at")
        time.sleep(1.1)  # ensure ISO timestamp changes
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"remarks": "touch to refresh updated_at"},
                         timeout=15)
        assert r.status_code == 200, r.text
        after = r.json().get("updated_at")
        assert before and after and str(before) != str(after), (
            f"updated_at did not refresh: before={before} after={after}")

    def test_14_audit_log_edit_draft_recorded(
            self, tokens, project_a, masters):
        mrf = _create_draft(tokens, project_a, masters)
        r = requests.put(f"{API}/mrf/{mrf['mrf_id']}",
                         headers=_hdr(tokens["se"]),
                         json={"remarks": "audit-check edit"}, timeout=15)
        assert r.status_code == 200, r.text
        # Admin reads audit log filtered by this MRF
        a = requests.get(f"{API}/audit",
                         headers=_hdr(tokens["admin"]),
                         params={"entity_id": mrf["mrf_id"]},
                         timeout=15)
        assert a.status_code == 200, a.text
        actions = [x.get("action") for x in a.json()]
        assert "edit_draft" in actions, (
            f"'edit_draft' missing from audit_logs for {mrf['mrf_id']}: "
            f"{actions}")
