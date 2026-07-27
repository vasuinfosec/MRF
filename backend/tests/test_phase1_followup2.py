"""Phase 1 follow-up #2 tests.

Extra coverage for endpoints called out in the review request that were not
in test_phase1_followup.py:
- GET /api/po/{id}/grns as director (via _check_po_access)
- GET /api/grns as director
- GET /api/invoice as director (list)
- POST /api/billing/update as director (any MRF item)
- No 500s across the flow.
"""
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
             or os.environ.get("EXPO_BACKEND_URL")
             or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def dev_login(email, role, name=None):
    return requests.post(f"{API}/auth/dev-login", json={
        "email": email, "role": role, "name": name or email.split("@")[0]
    }, timeout=15)


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    r = dev_login("admin@vasu.dev", "admin", "Admin")
    assert r.status_code == 200, r.text
    admin_tok = r.json()["session_token"]
    seed = requests.post(f"{API}/seed", headers=h(admin_tok), timeout=30)
    assert seed.status_code == 200, seed.text
    out = {"admin": admin_tok}
    for role, email in [
        ("director", "director@vasu.dev"),
        ("pm", "pm@vasu.dev"),
        ("purchase", "purchase@vasu.dev"),
    ]:
        rr = dev_login(email, role)
        assert rr.status_code == 200, f"{role} login failed: {rr.text}"
        out[role] = rr.json()["session_token"]
    return out


@pytest.fixture(scope="module")
def vis101(tokens):
    r = requests.get(f"{API}/projects?all=true", headers=h(tokens["admin"]))
    assert r.status_code == 200
    return next(p for p in r.json() if p["code"] == "VIS-101")


@pytest.fixture(scope="module")
def po(tokens, vis101):
    # Create MRF+approve then PO
    body = {
        "project_id": vis101["project_id"],
        "site": vis101["site"],
        "required_by": "2026-06-15",
        "requesting_person": "TEST_R",
        "system_category": "Fire Alarm",
        "items": [{"description": "TEST_Panel", "unit": "Nos",
                   "qty_requested": 5, "billable": True}],
    }
    rm = requests.post(f"{API}/mrf", headers=h(tokens["admin"]), json=body)
    assert rm.status_code == 200
    mrf = rm.json()
    ap = requests.post(f"{API}/mrf/{mrf['mrf_id']}/approve",
                       headers=h(tokens["admin"]),
                       json={"action": "approve", "comment": "TEST"})
    assert ap.status_code == 200
    rv = requests.get(f"{API}/vendors", headers=h(tokens["admin"]))
    vendor = rv.json()[0]
    po_body = {
        "vendor_id": vendor["vendor_id"],
        "project_id": vis101["project_id"],
        "delivery_site": vis101["site"],
        "items": [{
            "mrf_id": mrf["mrf_id"],
            "item_line_id": mrf["items"][0]["item_line_id"],
            "description": "TEST_Panel", "unit": "Nos",
            "qty": 5, "rate": 100, "discount": 0, "gst": 18,
        }],
    }
    rp = requests.post(f"{API}/po", headers=h(tokens["purchase"]), json=po_body)
    assert rp.status_code == 200, rp.text
    return {"po": rp.json(), "mrf": mrf}


class TestDirectorGRNAccess:
    def test_director_lists_po_grns(self, tokens, po):
        pid = po["po"]["po_id"]
        r = requests.get(f"{API}/po/{pid}/grns", headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /po/{{id}}/grns expected 200, got {r.status_code}: "
            f"{r.text[:200]}"
        )
        assert isinstance(r.json(), list)

    def test_director_lists_all_grns(self, tokens):
        r = requests.get(f"{API}/grns", headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /grns expected 200, got {r.status_code}: {r.text[:200]}"
        )
        assert isinstance(r.json(), list)


class TestDirectorInvoiceList:
    def test_director_lists_invoices(self, tokens):
        r = requests.get(f"{API}/invoice", headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /invoice list expected 200, got {r.status_code}: "
            f"{r.text[:200]}"
        )
        assert isinstance(r.json(), list)


class TestDirectorBillingUpdate:
    def test_director_can_update_billing(self, tokens, po):
        mrf = po["mrf"]
        payload = {
            "mrf_id": mrf["mrf_id"],
            "item_line_id": mrf["items"][0]["item_line_id"],
            "qty_billed": 1,
            "client_bill_ref": f"TEST_REF_{uuid.uuid4().hex[:5]}",
        }
        r = requests.post(f"{API}/billing/update",
                          headers=h(tokens["director"]),
                          json=payload)
        assert r.status_code == 200, (
            f"director /billing/update expected 200, got {r.status_code}: "
            f"{r.text[:200]}"
        )
        # Verify persistence
        rg = requests.get(f"{API}/mrf/{mrf['mrf_id']}",
                          headers=h(tokens["admin"]))
        assert rg.status_code == 200
        item = next(i for i in rg.json()["items"]
                    if i["item_line_id"] == payload["item_line_id"])
        assert item.get("qty_billed") == 1
        assert item.get("client_bill_ref") == payload["client_bill_ref"]
