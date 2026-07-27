"""
Backend regression tests for Vasu Infosec MRF & PO System.
Covers auth, seed, MRF lifecycle, PO creation, PDF, billing, dashboard, audit.
"""
import os
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
             or os.environ.get("EXPO_BACKEND_URL")
             or "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")


def _login(role: str, email: str, name: str):
    r = requests.post(f"{BASE_URL}/api/auth/dev-login",
                      json={"email": email, "role": role, "name": name}, timeout=20)
    assert r.status_code == 200, f"dev-login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def tokens():
    # Ensure seed data first (post-SEC-001 requires admin auth)
    admin_tok = _login("admin", "admin@vasu.dev", "Director")
    r = requests.post(f"{BASE_URL}/api/seed",
                      headers={"Authorization": f"Bearer {admin_tok}"}, timeout=30)
    assert r.status_code == 200
    return {
        "site": _login("site_engineer", "site@vasu.dev", "Ravi"),
        "pm": _login("project_manager", "pm@vasu.dev", "Priya"),
        "purchase": _login("purchase", "purchase@vasu.dev", "Kumar"),
        "billing": _login("billing", "billing@vasu.dev", "Anita"),
        "admin": admin_tok,
    }


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ----- Auth -----
class TestAuth:
    def test_seed_idempotent(self, tokens):
        h = _h(tokens["admin"])
        r1 = requests.post(f"{BASE_URL}/api/seed", headers=h, timeout=30)
        r2 = requests.post(f"{BASE_URL}/api/seed", headers=h, timeout=30)
        assert r1.status_code == 200 and r2.status_code == 200
        assert "logins" in r1.json()

    def test_dev_login_returns_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/dev-login",
                          json={"email": "site@vasu.dev", "role": "site_engineer", "name": "Ravi"})
        assert r.status_code == 200
        assert "session_token" in r.json()
        assert r.json()["user"]["role"] == "site_engineer"

    def test_me_endpoint(self, tokens):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(tokens["site"]))
        assert r.status_code == 200
        assert r.json()["email"] == "site@vasu.dev"

    def test_me_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401


# ----- Master data -----
class TestMasters:
    def test_list_projects(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site"]))
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_list_vendors(self, tokens):
        r = requests.get(f"{BASE_URL}/api/vendors", headers=_h(tokens["purchase"]))
        assert r.status_code == 200
        assert len(r.json()) >= 5

    def test_masters_grouped(self, tokens):
        r = requests.get(f"{BASE_URL}/api/masters", headers=_h(tokens["site"]))
        assert r.status_code == 200
        d = r.json()
        assert "unit" in d and "material" in d


# ----- Role enforcement -----
class TestRoleAccess:
    def test_site_engineer_cannot_create_po(self, tokens):
        r = requests.post(f"{BASE_URL}/api/po", headers=_h(tokens["site"]),
                          json={"vendor_id": "v", "project_id": "p", "delivery_site": "s", "items": []})
        assert r.status_code == 403

    def test_non_admin_cannot_change_role(self, tokens):
        r = requests.post(f"{BASE_URL}/api/users/role", headers=_h(tokens["pm"]),
                          json={"user_id": "abc", "role": "admin"})
        assert r.status_code == 403


# ----- Full MRF -> PO -> Billing flow -----
class TestMRFWorkflow:
    _state = {}

    def test_01_create_mrf(self, tokens):
        projects = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site"])).json()
        proj = projects[0]
        body = {
            "project_id": proj["project_id"],
            "site": proj["site"],
            "required_by": "2026-02-15",
            "requesting_person": "TEST_Ravi",
            "system_category": "Fire Alarm",
            "items": [
                {"description": "TEST_Smoke Detector", "unit": "Nos", "qty_requested": 10, "billable": True},
                {"description": "TEST_Manual Call Point", "unit": "Nos", "qty_requested": 5, "billable": True},
                {"description": "TEST_Sounder", "unit": "Nos", "qty_requested": 4, "billable": True},
            ],
            "remarks": "TEST run",
        }
        r = requests.post(f"{BASE_URL}/api/mrf", headers=_h(tokens["site"]), json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "draft"
        assert d["mrf_number"].startswith("MRF/")
        assert len(d["items"]) == 3
        TestMRFWorkflow._state["mrf_id"] = d["mrf_id"]
        TestMRFWorkflow._state["items"] = d["items"]
        TestMRFWorkflow._state["project_id"] = proj["project_id"]

    def test_02_submit_mrf(self, tokens):
        mrf_id = self._state["mrf_id"]
        r = requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/submit", headers=_h(tokens["site"]))
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/mrf/{mrf_id}", headers=_h(tokens["site"])).json()
        assert g["status"] == "pm_review"

    def test_03_pm_approve_with_item_actions(self, tokens):
        mrf_id = self._state["mrf_id"]
        items = self._state["items"]
        item_actions = [
            {"item_line_id": items[0]["item_line_id"], "action": "approve", "qty_approved": 10},
            {"item_line_id": items[1]["item_line_id"], "action": "reject", "reason": "Not required"},
            {"item_line_id": items[2]["item_line_id"], "action": "approve", "qty_approved": 4},
        ]
        r = requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/approve", headers=_h(tokens["pm"]),
                          json={"action": "approve", "comment": "OK", "item_actions": item_actions})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        d = requests.get(f"{BASE_URL}/api/mrf/{mrf_id}", headers=_h(tokens["pm"])).json()
        statuses = [it["status"] for it in d["items"]]
        assert statuses.count("rejected") == 1 and statuses.count("approved") == 2

    def test_04_send_to_purchase(self, tokens):
        r = requests.post(f"{BASE_URL}/api/mrf/{self._state['mrf_id']}/send-to-purchase",
                          headers=_h(tokens["pm"]))
        assert r.status_code == 200

    def test_05_po_reject_rejected_item(self, tokens):
        vendors = requests.get(f"{BASE_URL}/api/vendors", headers=_h(tokens["purchase"])).json()
        items = self._state["items"]
        rejected_item = items[1]
        body = {
            "vendor_id": vendors[0]["vendor_id"],
            "project_id": self._state["project_id"],
            "delivery_site": "TEST site",
            "items": [{
                "mrf_id": self._state["mrf_id"],
                "item_line_id": rejected_item["item_line_id"],
                "description": rejected_item["description"],
                "unit": "Nos", "qty": 5, "rate": 100
            }]
        }
        r = requests.post(f"{BASE_URL}/api/po", headers=_h(tokens["purchase"]), json=body)
        assert r.status_code == 400

    def test_06_create_po(self, tokens):
        vendors = requests.get(f"{BASE_URL}/api/vendors", headers=_h(tokens["purchase"])).json()
        items = self._state["items"]
        approved_items = [it for it in items if it["item_line_id"] != items[1]["item_line_id"]]
        body = {
            "vendor_id": vendors[0]["vendor_id"],
            "project_id": self._state["project_id"],
            "delivery_site": "TEST delivery",
            "items": [{
                "mrf_id": self._state["mrf_id"],
                "item_line_id": approved_items[0]["item_line_id"],
                "description": approved_items[0]["description"],
                "unit": "Nos", "qty": 10, "rate": 150, "gst": 18, "discount": 0
            }, {
                "mrf_id": self._state["mrf_id"],
                "item_line_id": approved_items[1]["item_line_id"],
                "description": approved_items[1]["description"],
                "unit": "Nos", "qty": 4, "rate": 500, "gst": 18, "discount": 0
            }],
            "freight": 200, "other_charges": 0,
            "payment_terms": "30 days", "warranty_terms": "1 year"
        }
        r = requests.post(f"{BASE_URL}/api/po", headers=_h(tokens["purchase"]), json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["po_number"].startswith("PO/")
        assert d["total"] > 0
        TestMRFWorkflow._state["po_id"] = d["po_id"]
        TestMRFWorkflow._state["approved_items"] = approved_items
        # Verify MRF status updated
        mrf = requests.get(f"{BASE_URL}/api/mrf/{self._state['mrf_id']}", headers=_h(tokens["purchase"])).json()
        assert mrf["status"] in ["fully_ordered", "partially_ordered"]

    def test_07_po_pdf_download(self, tokens):
        po_id = self._state["po_id"]
        r = requests.get(f"{BASE_URL}/api/po/{po_id}/pdf?token={tokens['purchase']}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_08_po_mark_received(self, tokens):
        r = requests.post(f"{BASE_URL}/api/po/{self._state['po_id']}/received",
                          headers=_h(tokens["purchase"]), json={})
        assert r.status_code == 200

    def test_09_billing_update(self, tokens):
        approved = self._state["approved_items"][0]
        body = {"mrf_id": self._state["mrf_id"], "item_line_id": approved["item_line_id"],
                "qty_billed": 10, "client_bill_ref": "TEST_BILL_1", "ra_bill_no": "RA/1"}
        r = requests.post(f"{BASE_URL}/api/billing/update", headers=_h(tokens["billing"]), json=body)
        assert r.status_code == 200, r.text
        # Verify billing status auto-computed as fully_billed
        mrf = requests.get(f"{BASE_URL}/api/mrf/{self._state['mrf_id']}", headers=_h(tokens["billing"])).json()
        it = next(it for it in mrf["items"] if it["item_line_id"] == approved["item_line_id"])
        assert it["billing_status"] == "fully_billed"

    def test_10_billing_override_required(self, tokens):
        # Set qty_received > qty_billed then try to mark fully_billed without override
        approved = self._state["approved_items"][1]
        # first ensure some received qty exists (already from PO received)
        body = {"mrf_id": self._state["mrf_id"], "item_line_id": approved["item_line_id"],
                "qty_billed": 1, "billing_status": "fully_billed"}
        r = requests.post(f"{BASE_URL}/api/billing/update", headers=_h(tokens["billing"]), json=body)
        assert r.status_code == 400

    def test_11_billing_override_with_reason(self, tokens):
        approved = self._state["approved_items"][1]
        body = {"mrf_id": self._state["mrf_id"], "item_line_id": approved["item_line_id"],
                "qty_billed": 1, "billing_status": "fully_billed", "override_reason": "TEST client agreement"}
        r = requests.post(f"{BASE_URL}/api/billing/update", headers=_h(tokens["billing"]), json=body)
        assert r.status_code == 200


# ----- PM returns MRF flow -----
class TestReturnFlow:
    def test_pm_return_mrf(self, tokens):
        projects = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site"])).json()
        body = {
            "project_id": projects[0]["project_id"], "site": "TEST site",
            "required_by": "2026-03-01", "requesting_person": "TEST_R",
            "system_category": "CCTV",
            "items": [{"description": "TEST_Cam", "unit": "Nos", "qty_requested": 2}],
        }
        r = requests.post(f"{BASE_URL}/api/mrf", headers=_h(tokens["site"]), json=body)
        mrf_id = r.json()["mrf_id"]
        requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/submit", headers=_h(tokens["site"]))
        r = requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/approve", headers=_h(tokens["pm"]),
                         json={"action": "return", "comment": "Need clarification"})
        assert r.status_code == 200
        assert r.json()["status"] == "returned"


# ----- Reports/exports/audit -----
class TestReports:
    def test_dashboard(self, tokens):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        d = r.json()
        assert "total_mrf" in d and "ageing" in d
        assert set(d["ageing"].keys()) == {"0-3", "4-7", "8-15", "16+"}

    def test_mrf_ageing(self, tokens):
        r = requests.get(f"{BASE_URL}/api/reports/mrf-ageing", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_audit_logs(self, tokens):
        r = requests.get(f"{BASE_URL}/api/audit", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        logs = r.json()
        assert isinstance(logs, list) and len(logs) > 0
        assert "action" in logs[0] and "user_role" in logs[0]

    def test_excel_export_mrf(self, tokens):
        r = requests.get(f"{BASE_URL}/api/export/mrf?token={tokens['admin']}")
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert r.content[:2] == b"PK"  # xlsx = zip

    def test_notifications(self, tokens):
        r = requests.get(f"{BASE_URL}/api/notifications", headers=_h(tokens["pm"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestAdmin:
    def test_admin_can_change_role(self, tokens):
        users = requests.get(f"{BASE_URL}/api/users", headers=_h(tokens["admin"])).json()
        target = next(u for u in users if u["email"] == "site@vasu.dev")
        r = requests.post(f"{BASE_URL}/api/users/role", headers=_h(tokens["admin"]),
                          json={"user_id": target["user_id"], "role": "site_engineer"})
        assert r.status_code == 200
        assert r.json()["role"] == "site_engineer"
