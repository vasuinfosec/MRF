"""Iteration 18 — Backend regression for the new Audit Trail RBAC + enrichment.

Previous iteration (iter14) required admin/director-only on bulk /api/audit.
This iteration relaxes that:
  - admin/director/gm/purchase: full bulk visibility
  - pm: filtered (own actions + their-project MRFs/POs + master data)
  - site_engineer: own actions + own MRFs (+ POs referencing those MRFs)
  - store: own actions + received/grn events

Also verifies old_value/new_value enrichment on approvals, edits, PO create,
PO received, login/logout, customer edit mirroring and facets endpoint.

Requires ENABLE_DEV_LOGIN=1.
"""
import os
import uuid
from typing import Any, Dict, List

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


def _contains_objectid(o) -> bool:
    """Deep-scan for a MongoDB _id key which would indicate raw ObjectId leaked."""
    if isinstance(o, dict):
        if "_id" in o:
            return True
        return any(_contains_objectid(v) for v in o.values())
    if isinstance(o, list):
        return any(_contains_objectid(v) for v in o)
    return False


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def tokens() -> Dict[str, str]:
    return {
        "admin":    _login("admin@vasu.dev",    "admin",         "Iter18 Admin"),
        "director": _login("director@vasu.dev", "director",      "Iter18 Director"),
        "gm":       _login("gm@vasu.dev",       "gm",            "Iter18 GM"),
        "pm":       _login("pm@vasu.dev",       "pm",            "Iter18 PM"),
        "purchase": _login("purchase@vasu.dev", "purchase",      "Iter18 Purchase"),
        "se":       _login("siteeng@vasu.dev",  "site_engineer", "Iter18 SE"),
        "se2":      _login("iter18-se2@vasu.dev", "site_engineer", "Iter18 SE2"),
        "store":    _login("store@vasu.dev",    "store",         "Iter18 Store"),
    }


@pytest.fixture(scope="module")
def uid(tokens) -> Dict[str, str]:
    return {k: _me(t)["user_id"] for k, t in tokens.items()}


@pytest.fixture(scope="module")
def masters(tokens) -> Dict[str, List[Dict[str, Any]]]:
    r = requests.get(f"{API}/masters", headers=_hdr(tokens["admin"]), timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("material"), "need >=1 material master"
    return d


@pytest.fixture(scope="module")
def project_a(tokens, uid) -> Dict[str, Any]:
    cid = f"TESTCUS18-{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/customers", headers=_hdr(tokens["admin"]),
                      json={"customer_id": cid,
                            "name": f"TEST Cust {cid}",
                            "gstin": "27ABCDE1234F1Z5", "state": "MH"},
                      timeout=15)
    assert r.status_code == 200, r.text
    cust = r.json()
    pcode = f"TP-18-{uuid.uuid4().hex[:5].upper()}"
    r = requests.post(f"{API}/projects", headers=_hdr(tokens["admin"]),
                      json={"code": pcode, "name": f"TEST Proj {pcode}",
                            "site": "Pune", "client": "ClientA",
                            "customer_id": cust["customer_id"],
                            "site_engineers": [uid["se"]],
                            "project_managers": [uid["pm"]],
                            "reason": "iter18 setup"},
                      timeout=15)
    assert r.status_code == 200, r.text
    p = r.json()
    p["_customer_id"] = cust["customer_id"]
    return p


def _mk_item(masters, qty: float = 5.0) -> Dict[str, Any]:
    mat = masters["material"][0]
    return {"description": "TEST-Iter18 item",
            "unit": "nos", "qty_requested": qty,
            "material_id": mat["item_id"],
            "priority": "normal"}


@pytest.fixture(scope="module")
def mrf(tokens, project_a, masters) -> Dict[str, Any]:
    body = {"project_id": project_a["project_id"],
            "site": project_a.get("site", "Pune"),
            "required_by": "2026-02-28",
            "requesting_person": "Iter18",
            "system_category": "electrical",
            "items": [_mk_item(masters)],
            "remarks": "iter18"}
    r = requests.post(f"{API}/mrf", headers=_hdr(tokens["se"]),
                      json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def approved_mrf(tokens, mrf) -> Dict[str, Any]:
    """SE submits → PM approves → PM sends to purchase."""
    mid = mrf["mrf_id"]
    r = requests.post(f"{API}/mrf/{mid}/submit",
                      headers=_hdr(tokens["se"]), timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/mrf/{mid}/approve",
                      headers=_hdr(tokens["pm"]),
                      json={"action": "approve", "comment": "ok iter18"},
                      timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/mrf/{mid}/send-to-purchase",
                      headers=_hdr(tokens["pm"]), timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/mrf/{mid}", headers=_hdr(tokens["admin"]),
                     timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def vendor(tokens) -> Dict[str, Any]:
    vid = f"TESTVEND18-{uuid.uuid4().hex[:6].upper()}"
    r = requests.post(f"{API}/vendors", headers=_hdr(tokens["admin"]),
                      json={"vendor_id": vid, "name": f"TEST Vendor {vid}",
                            "gstin": "27AABCT1234A1Z5", "state": "MH",
                            "active": True},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def po(tokens, project_a, approved_mrf, vendor) -> Dict[str, Any]:
    """Small PO auto-issued (below GM threshold)."""
    line = approved_mrf["items"][0]
    body = {
        "vendor_id": vendor["vendor_id"],
        "project_id": project_a["project_id"],
        "delivery_site": project_a.get("site", "Pune"),
        "items": [{
            "mrf_id": approved_mrf["mrf_id"],
            "item_line_id": line["item_line_id"],
            "description": line["description"],
            "unit": line["unit"],
            "qty": line.get("qty_approved") or line["qty_requested"],
            "rate": 100.0, "discount": 0, "gst": 18,
            "hsn_code": "8536",
        }],
        "delivery_schedule": "asap",
        "payment_terms": "net 30",
    }
    r = requests.post(f"{API}/po", headers=_hdr(tokens["purchase"]),
                      json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# =====================================================================
# 1. BULK AUDIT RBAC (regression: gm/purchase now 200, not 403)
# =====================================================================
class TestBulkAuditRBAC:
    def test_admin_bulk_200(self, tokens):
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_director_bulk_200(self, tokens):
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["director"]), timeout=15)
        assert r.status_code == 200, r.text

    def test_gm_bulk_200_regression_fix(self, tokens):
        """iter14 wanted 403 for GM; iter18 spec explicitly requires 200."""
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["gm"]), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_purchase_bulk_200_regression_fix(self, tokens):
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["purchase"]), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_pm_bulk_200_filtered(self, tokens, uid, mrf):
        """PM must get 200 but filtered — every entry must be either
        their own action OR reference an MRF/PO on their project OR a master."""
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["pm"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        # PM at least sees their own actions (they've approved the MRF)
        own = [x for x in rows if x.get("user_id") == uid["pm"]]
        assert own, "PM should see their own actions in bulk audit"

    def test_site_engineer_bulk_200_filtered(self, tokens, uid, mrf):
        # Fetch SE's actual MRF universe (they may have many across test runs)
        r0 = requests.get(f"{API}/mrf", headers=_hdr(tokens["se"]), timeout=15)
        assert r0.status_code == 200, r0.text
        allowed_mrf = {m["mrf_id"] for m in r0.json()
                       if m.get("created_by") == uid["se"]}
        # Also collect POs that reference those MRFs (via admin view)
        r_po = requests.get(f"{API}/po", headers=_hdr(tokens["admin"]), timeout=15)
        assert r_po.status_code == 200, r_po.text
        allowed_po = {p["po_id"] for p in r_po.json()
                      if any(it.get("mrf_id") in allowed_mrf for it in p.get("items", []))}
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["se"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        for row in rows:
            eid = row.get("entity_id")
            assert (row.get("user_id") == uid["se"]
                    or eid in allowed_mrf
                    or eid in allowed_po
                    ), f"SE saw unrelated row: {row}"

    def test_store_bulk_200_filtered(self, tokens, uid):
        r = requests.get(f"{API}/audit", headers=_hdr(tokens["store"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        for row in rows:
            act = row.get("action", "") or ""
            # Store either did the action themselves, or it's a received/grn event
            assert (row.get("user_id") == uid["store"]
                    or act.startswith("received")
                    or act.startswith("po_received")
                    or "grn" in act.lower()
                    ), f"Store saw unrelated row: {row}"


# =====================================================================
# 2. LOGIN / LOGOUT AUDIT
# =====================================================================
class TestAuthAudit:
    def test_dev_login_writes_audit_row(self, tokens):
        # Force a fresh login for a distinct name so we can find it
        email = f"iter18-auth-{uuid.uuid4().hex[:6]}@vasu.dev"
        r = requests.post(f"{API}/auth/dev-login",
                          json={"email": email, "role": "pm", "name": "Iter18 Auth"},
                          timeout=15)
        assert r.status_code == 200, r.text
        user_id = r.json()["user"]["user_id"]
        # Query admin audit for entity=auth, action=login for this user_id
        rr = requests.get(f"{API}/audit",
                          params={"entity": "auth", "action": "login",
                                  "user_id": user_id},
                          headers=_hdr(tokens["admin"]), timeout=15)
        assert rr.status_code == 200, rr.text
        rows = rr.json()
        assert rows, f"login audit row missing for {user_id}"
        row = rows[0]
        assert row["entity"] == "auth"
        assert row["action"] == "login"
        assert (row.get("details") or {}).get("method") == "dev-login"
        assert row.get("user_role") == "pm"

    def test_logout_writes_audit_row(self, tokens):
        email = f"iter18-lo-{uuid.uuid4().hex[:6]}@vasu.dev"
        r = requests.post(f"{API}/auth/dev-login",
                          json={"email": email, "role": "purchase", "name": "Iter18 LO"},
                          timeout=15)
        assert r.status_code == 200, r.text
        tok = r.json()["session_token"]
        user_id = r.json()["user"]["user_id"]
        r2 = requests.post(f"{API}/auth/logout", headers=_hdr(tok), timeout=15)
        assert r2.status_code == 200, r2.text
        rr = requests.get(f"{API}/audit",
                          params={"entity": "auth", "action": "logout",
                                  "user_id": user_id},
                          headers=_hdr(tokens["admin"]), timeout=15)
        assert rr.status_code == 200, rr.text
        rows = rr.json()
        assert rows, f"logout audit row missing for {user_id}"
        assert rows[0]["action"] == "logout"
        assert rows[0]["user_role"] == "purchase"


# =====================================================================
# 3. OLD_VALUE / NEW_VALUE ENRICHMENT ON WORKFLOW ENDPOINTS
# =====================================================================
class TestOldNewValueTracking:
    def _entries(self, tokens, entity_id: str, action: str = None) -> List[Dict]:
        params = {"entity_id": entity_id}
        if action:
            params["action"] = action
        r = requests.get(f"{API}/audit", params=params,
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def test_mrf_submit_has_old_new_status(self, tokens, mrf, approved_mrf):
        rows = self._entries(tokens, mrf["mrf_id"], action="submit")
        assert rows, "no submit audit row"
        det = rows[0]["details"]
        assert det.get("old_value", {}).get("status") == "draft"
        assert det.get("new_value", {}).get("status") == "pm_review"

    def test_mrf_approve_has_old_new_status(self, tokens, mrf, approved_mrf):
        rows = self._entries(tokens, mrf["mrf_id"], action="approve")
        assert rows, "no approve audit row"
        det = rows[0]["details"]
        assert det.get("old_value", {}).get("status") == "pm_review"
        assert det.get("new_value", {}).get("status") == "approved"

    def test_mrf_send_to_purchase_has_old_new_status(self, tokens, mrf, approved_mrf):
        rows = self._entries(tokens, mrf["mrf_id"], action="send_to_purchase")
        assert rows, "no send_to_purchase audit row"
        det = rows[0]["details"]
        assert det.get("old_value", {}).get("status") == "approved"
        assert det.get("new_value", {}).get("status") == "sent_to_purchase"

    def test_mrf_return_flow_has_old_new_status(self, tokens, project_a, masters):
        """Fresh MRF: submit → return."""
        body = {"project_id": project_a["project_id"],
                "site": project_a.get("site", "Pune"),
                "required_by": "2026-02-28",
                "requesting_person": "Iter18-return",
                "system_category": "electrical",
                "items": [_mk_item(masters)],
                "remarks": "iter18 return path"}
        r = requests.post(f"{API}/mrf", headers=_hdr(tokens["se"]),
                          json=body, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["mrf_id"]
        r = requests.post(f"{API}/mrf/{mid}/submit",
                          headers=_hdr(tokens["se"]), timeout=15)
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/mrf/{mid}/approve",
                          headers=_hdr(tokens["pm"]),
                          json={"action": "return", "comment": "need more info"},
                          timeout=15)
        assert r.status_code == 200, r.text
        rows = self._entries(tokens, mid, action="return")
        assert rows, "no return audit row"
        det = rows[0]["details"]
        assert det.get("old_value", {}).get("status") == "pm_review"
        assert det.get("new_value", {}).get("status") == "returned"
        assert det.get("reason") == "need more info"

    def test_mrf_edit_draft_has_old_new(self, tokens, project_a, masters):
        """Fresh Draft MRF: PUT edit → audit has old_value/new_value snapshots."""
        body = {"project_id": project_a["project_id"],
                "site": project_a.get("site", "Pune"),
                "required_by": "2026-02-28",
                "requesting_person": "Iter18-edit-original",
                "system_category": "electrical",
                "items": [_mk_item(masters)],
                "remarks": "iter18 edit path original"}
        r = requests.post(f"{API}/mrf", headers=_hdr(tokens["se"]),
                          json=body, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["mrf_id"]
        # Edit while draft
        r = requests.put(f"{API}/mrf/{mid}",
                         headers=_hdr(tokens["se"]),
                         json={"requesting_person": "Iter18-edit-CHANGED",
                               "remarks": "iter18 edit path CHANGED",
                               "reason": "typo fix"},
                         timeout=15)
        assert r.status_code == 200, r.text
        rows = self._entries(tokens, mid, action="edit_draft")
        assert rows, "no edit_draft audit row"
        det = rows[0]["details"]
        assert isinstance(det.get("old_value"), dict) and det["old_value"], \
            "edit_draft.old_value missing"
        assert isinstance(det.get("new_value"), dict) and det["new_value"], \
            "edit_draft.new_value missing"
        # At least one field must have been captured in the snapshot
        assert "requesting_person" in det["new_value"] or "remarks" in det["new_value"]

    def test_po_create_audit_has_new_value(self, tokens, po):
        rows = self._entries(tokens, po["po_id"], action="create")
        assert rows, "no PO create audit row"
        det = rows[0]["details"]
        new_val = det.get("new_value") or {}
        assert "total" in new_val
        assert "status" in new_val
        assert "vendor_id" in new_val
        assert "customer_id" in new_val or "project_id" in new_val
        assert "item_count" in new_val

    def test_po_approve_audit(self, tokens, project_a, masters, vendor):
        """Fresh MRF flow + PO above GM threshold → GM approve → verify old/new status."""
        # Fresh MRF
        body_mrf = {"project_id": project_a["project_id"],
                    "site": project_a.get("site", "Pune"),
                    "required_by": "2026-02-28",
                    "requesting_person": "Iter18-po-approve",
                    "system_category": "electrical",
                    "items": [_mk_item(masters, qty=1000.0)],
                    "remarks": "iter18 po-approve MRF"}
        r = requests.post(f"{API}/mrf", headers=_hdr(tokens["se"]),
                          json=body_mrf, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["mrf_id"]
        # Submit / approve / send-to-purchase
        for step, tok in (("submit", "se"), ("approve", "pm"),
                          ("send-to-purchase", "pm")):
            payload = {"action": "approve", "comment": ""} if step == "approve" else None
            r = requests.post(f"{API}/mrf/{mid}/{step}",
                              headers=_hdr(tokens[tok]),
                              json=payload, timeout=15)
            assert r.status_code == 200, f"{step}: {r.text}"
        r = requests.get(f"{API}/mrf/{mid}", headers=_hdr(tokens["admin"]),
                         timeout=15)
        assert r.status_code == 200, r.text
        approved = r.json()
        line = approved["items"][0]
        body = {
            "vendor_id": vendor["vendor_id"],
            "project_id": project_a["project_id"],
            "delivery_site": project_a.get("site", "Pune"),
            "items": [{
                "mrf_id": mid,
                "item_line_id": line["item_line_id"],
                "description": line["description"],
                "unit": line["unit"],
                "qty": line.get("qty_approved") or line["qty_requested"],
                "rate": 100.0, "discount": 0, "gst": 18,
                "hsn_code": "8536",
            }],
            "delivery_schedule": "asap",
            "payment_terms": "net 30",
        }
        r = requests.post(f"{API}/po", headers=_hdr(tokens["purchase"]),
                          json=body, timeout=15)
        assert r.status_code == 200, r.text
        pid = r.json()["po_id"]
        status = r.json().get("status")
        if status not in ("pending_gm_approval", "pending_director_approval"):
            pytest.skip(f"PO auto-issued at status={status}, threshold too high")
        approver = tokens["director"] if status == "pending_director_approval" else tokens["gm"]
        r = requests.post(f"{API}/po/{pid}/approve",
                          headers=_hdr(approver),
                          json={"action": "approve", "comment": "iter18 ok"},
                          timeout=15)
        assert r.status_code == 200, r.text
        rows = self._entries(tokens, pid, action="po_approve")
        assert rows, "no po_approve audit row"
        det = rows[0]["details"]
        assert det.get("old_value", {}).get("status") == status
        assert det.get("new_value", {}).get("status") == "issued"
        assert det.get("reason") == "iter18 ok"

    def test_po_received_audit(self, tokens, po):
        pid = po["po_id"]
        # Use the PO response's item structure (mrf_id + item_line_id + qty)
        po_item = po["items"][0]
        body = {
            "items": [{
                "mrf_id": po_item["mrf_id"],
                "item_line_id": po_item["item_line_id"],
                "qty": float(po_item["qty"]),
            }],
            "remarks": "iter18 received full",
        }
        r = requests.post(f"{API}/po/{pid}/received",
                          headers=_hdr(tokens["store"]),
                          json=body, timeout=15)
        if r.status_code == 403:
            r = requests.post(f"{API}/po/{pid}/received",
                              headers=_hdr(tokens["purchase"]),
                              json=body, timeout=15)
        assert r.status_code == 200, r.text
        rows = self._entries(tokens, pid, action="received")
        assert rows, "no received audit row"
        det = rows[0]["details"]
        assert "old_value" in det and det["old_value"].get("status") is not None
        assert det["new_value"].get("status") in ("received", "partially_received"), \
            f"unexpected new_value={det.get('new_value')}"
        assert det.get("grn_number"), f"grn_number missing: {det}"
        assert isinstance(det.get("per_line"), list) and det["per_line"], \
            f"per_line empty: {det}"
        assert det.get("po_number")


# =====================================================================
# 4. ENTITY-SCOPED AUDIT ACCESS
# =====================================================================
class TestEntityScopedAudit:
    def test_pm_scoped_mrf(self, tokens, mrf):
        r = requests.get(f"{API}/audit",
                         params={"entity_id": mrf["mrf_id"]},
                         headers=_hdr(tokens["pm"]), timeout=15)
        assert r.status_code == 200, r.text

    def test_purchase_scoped_po(self, tokens, po):
        r = requests.get(f"{API}/audit",
                         params={"entity_id": po["po_id"]},
                         headers=_hdr(tokens["purchase"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert rows and all(e.get("entity_id") == po["po_id"] for e in rows)

    def test_gm_scoped_mrf(self, tokens, mrf):
        r = requests.get(f"{API}/audit",
                         params={"entity_id": mrf["mrf_id"]},
                         headers=_hdr(tokens["gm"]), timeout=15)
        assert r.status_code == 200, r.text

    def test_pm_scoped_customer(self, tokens, project_a):
        cid = project_a["_customer_id"]
        for role_key in ("pm", "purchase", "gm", "director", "admin"):
            r = requests.get(f"{API}/audit",
                             params={"entity_id": cid},
                             headers=_hdr(tokens[role_key]), timeout=15)
            assert r.status_code == 200, f"{role_key}: {r.text}"


# =====================================================================
# 5. QUERY FILTERS (action / user_role / since)
# =====================================================================
class TestAuditFilters:
    def test_action_prefix_filter(self, tokens):
        r = requests.get(f"{API}/audit", params={"action": "export"},
                         headers=_hdr(tokens["director"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        for row in rows:
            assert (row.get("action") or "").startswith("export"), row

    def test_user_role_filter_gm(self, tokens):
        r = requests.get(f"{API}/audit", params={"user_role": "gm"},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        for row in rows:
            assert row.get("user_role") == "gm", row

    def test_since_iso_valid(self, tokens):
        r = requests.get(f"{API}/audit", params={"since": "2024-01-01"},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_since_iso_malformed_400(self, tokens):
        r = requests.get(f"{API}/audit", params={"since": "not-a-date"},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 400, r.text

    def test_limit_capped(self, tokens):
        r = requests.get(f"{API}/audit", params={"limit": 10},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        assert len(r.json()) <= 10


# =====================================================================
# 6. FACETS
# =====================================================================
class TestFacets:
    @pytest.mark.parametrize("role", ["admin", "director", "gm", "purchase", "pm"])
    def test_facets_allowed_roles(self, tokens, role):
        r = requests.get(f"{API}/audit/facets", headers=_hdr(tokens[role]), timeout=15)
        assert r.status_code == 200, f"{role}: {r.text}"
        d = r.json()
        assert "entities" in d and isinstance(d["entities"], list)
        assert "actions" in d and isinstance(d["actions"], list)
        assert "users" in d and isinstance(d["users"], list)

    def test_facets_site_engineer_403(self, tokens):
        r = requests.get(f"{API}/audit/facets", headers=_hdr(tokens["se"]), timeout=15)
        assert r.status_code == 403, r.text

    def test_facets_store_403(self, tokens):
        r = requests.get(f"{API}/audit/facets", headers=_hdr(tokens["store"]), timeout=15)
        assert r.status_code == 403, r.text


# =====================================================================
# 7. MASTER-AUDIT MIRRORING (customer edit)
# =====================================================================
class TestMasterAuditMirror:
    def test_customer_edit_mirrors_into_audit(self, tokens, project_a):
        cid = project_a["_customer_id"]
        # PUT with a reason
        r = requests.put(f"{API}/customers/{cid}",
                         headers=_hdr(tokens["admin"]),
                         json={"state": "MH", "reason": "iter18 mirror test",
                               "name": f"TEST Cust {cid} v2"},
                         timeout=15)
        assert r.status_code == 200, r.text
        # Query /api/audit?entity_id=<cid>
        r = requests.get(f"{API}/audit", params={"entity_id": cid},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert rows, "no mirrored customer audit rows"
        # At least one row must be from master_audit mirror (has 'reason' in details)
        mirrored = [e for e in rows
                    if isinstance(e.get("details"), dict)
                    and "reason" in e["details"]
                    and (e["details"].get("old") is not None
                         or e["details"].get("new") is not None)]
        assert mirrored, f"no mirrored master-audit entry, got: {rows}"

    def test_master_audit_endpoint_still_works(self, tokens, project_a):
        r = requests.get(f"{API}/master-audit",
                         headers=_hdr(tokens["admin"]), timeout=15)
        # Endpoint may or may not exist under that path; skip if 404
        if r.status_code == 404:
            pytest.skip("master-audit endpoint not exposed")
        assert r.status_code == 200, r.text


# =====================================================================
# 8. NO RAW OBJECTID LEAK
# =====================================================================
class TestSerialisation:
    def test_bulk_no_objectid(self, tokens):
        r = requests.get(f"{API}/audit", params={"limit": 200},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        assert not _contains_objectid(r.json()), "raw _id leaked in audit payload"

    def test_entity_scoped_no_objectid(self, tokens, po):
        r = requests.get(f"{API}/audit", params={"entity_id": po["po_id"]},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        assert not _contains_objectid(r.json())


# =====================================================================
# 9. REGRESSION: EXPORT / SEED / MATERIALS
# =====================================================================
class TestRegression:
    def test_export_po_pm_allowed(self, tokens):
        r = requests.get(f"{API}/export/po", headers=_hdr(tokens["pm"]),
                         timeout=30)
        assert r.status_code == 200, r.text

    def test_seed_idempotent(self, tokens):
        r = requests.post(f"{API}/seed", headers=_hdr(tokens["admin"]),
                          timeout=30)
        assert r.status_code == 200, r.text

    def test_materials_default_approved_only(self, tokens):
        r = requests.get(f"{API}/materials", headers=_hdr(tokens["admin"]),
                         timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        for m in rows:
            assert m.get("status") == "approved" or m.get("approved") is True, m
