"""Phase 1 follow-up tests.

Covers:
- POST /api/po/{id}/received now allows director (fix for prior 403 duplicated-tuple bug).
- submit_mrf notifies users with role='pm' (previously 'project_manager' which matched nobody).
- Deduplicated role-tuple gates: /po create, /po pdf, /invoice create, /invoice pdf,
  /billing/items — all must return 200 for director.
- Fresh unrelated pm does not get elevated access.

Base URL: EXPO_BACKEND_URL (defaults http://localhost:8001).
"""
import os
import uuid
import time
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
    """Seed + login for every canonical role."""
    r = dev_login("admin@vasu.dev", "admin", "Admin")
    assert r.status_code == 200, r.text
    admin_tok = r.json()["session_token"]
    seed = requests.post(f"{API}/seed", headers=h(admin_tok), timeout=30)
    assert seed.status_code == 200, seed.text

    out = {"admin": admin_tok}
    for role, email in [
        ("director", "director@vasu.dev"),
        ("pm", "pm@vasu.dev"),
        ("gm", "gm@vasu.dev"),
        ("purchase", "purchase@vasu.dev"),
    ]:
        rr = dev_login(email, role)
        assert rr.status_code == 200, f"{role} login failed: {rr.text}"
        out[role] = rr.json()["session_token"]
    return out


@pytest.fixture(scope="module")
def vis101(tokens):
    r = requests.get(f"{API}/projects?all=true", headers=h(tokens["admin"]))
    assert r.status_code == 200, r.text
    return next(p for p in r.json() if p["code"] == "VIS-101")


def _create_and_approve_mrf(tokens, project):
    body = {
        "project_id": project["project_id"],
        "site": project["site"],
        "required_by": "2026-06-15",
        "requesting_person": "TEST_R",
        "system_category": "Fire Alarm",
        "items": [{"description": "TEST_Panel", "unit": "Nos",
                   "qty_requested": 5, "billable": True}],
    }
    rm = requests.post(f"{API}/mrf", headers=h(tokens["admin"]), json=body)
    assert rm.status_code == 200, rm.text
    mrf = rm.json()
    ap = requests.post(f"{API}/mrf/{mrf['mrf_id']}/approve",
                       headers=h(tokens["admin"]),
                       json={"action": "approve", "comment": "TEST"})
    assert ap.status_code == 200, ap.text
    return mrf


def _create_po(tokens, project, mrf, buyer_role="purchase"):
    rv = requests.get(f"{API}/vendors", headers=h(tokens["admin"]))
    vendor = rv.json()[0]
    po_body = {
        "vendor_id": vendor["vendor_id"],
        "project_id": project["project_id"],
        "delivery_site": project["site"],
        "items": [{
            "mrf_id": mrf["mrf_id"],
            "item_line_id": mrf["items"][0]["item_line_id"],
            "description": "TEST_Panel", "unit": "Nos",
            "qty": 5, "rate": 100, "discount": 0, "gst": 18,
        }],
    }
    return requests.post(f"{API}/po", headers=h(tokens[buyer_role]), json=po_body)


# ---------------- Bug fix (a): PO /received allows director ----------------
class TestPOReceivedRoles:
    @pytest.fixture(scope="class")
    def po_id(self, tokens, vis101):
        mrf = _create_and_approve_mrf(tokens, vis101)
        rpo = _create_po(tokens, vis101, mrf, buyer_role="purchase")
        assert rpo.status_code == 200, rpo.text
        return rpo.json()["po_id"]

    def _received(self, tok, pid):
        return requests.post(f"{API}/po/{pid}/received", headers=h(tok), json={})

    def test_director_200(self, tokens, po_id):
        r = self._received(tokens["director"], po_id)
        assert r.status_code == 200, f"director expected 200, got {r.status_code}: {r.text}"

    def test_purchase_200(self, tokens, po_id):
        r = self._received(tokens["purchase"], po_id)
        assert r.status_code == 200, r.text

    def test_admin_200(self, tokens, po_id):
        r = self._received(tokens["admin"], po_id)
        assert r.status_code == 200, r.text

    def test_pm_403(self, tokens, po_id):
        # Phase 2: PM (assigned to project) CAN record GRN.
        r = self._received(tokens["pm"], po_id)
        assert r.status_code == 200, f"pm expected 200 (Phase 2), got {r.status_code}"

    def test_gm_403(self, tokens, po_id):
        r = self._received(tokens["gm"], po_id)
        assert r.status_code == 403, f"gm expected 403, got {r.status_code}"


# ---------------- Bug fix (b): submit_mrf notifies role='pm' ----------------
class TestSubmitMRFNotifiesPM:
    def test_pm_receives_notification_after_submit(self, tokens, vis101):
        # Create draft MRF as pm (allowed) then submit
        marker = f"TEST_submit_{uuid.uuid4().hex[:8]}"
        body = {
            "project_id": vis101["project_id"],
            "site": vis101["site"],
            "required_by": "2026-06-30",
            "requesting_person": marker,
            "system_category": "Fire Alarm",
            "items": [{"description": marker, "unit": "Nos",
                       "qty_requested": 3, "billable": True}],
        }
        # pm@vasu.dev is on VIS-101 project_managers so create allowed
        rm = requests.post(f"{API}/mrf", headers=h(tokens["pm"]), json=body)
        assert rm.status_code == 200, rm.text
        mrf = rm.json()
        # MRF starts as draft — submit to move to pm_review
        assert mrf["status"] in ("draft", "returned"), mrf["status"]

        rs = requests.post(f"{API}/mrf/{mrf['mrf_id']}/submit",
                           headers=h(tokens["pm"]))
        assert rs.status_code == 200, rs.text

        # allow a moment for notification write (in-process, should be immediate)
        time.sleep(0.5)

        rn = requests.get(f"{API}/notifications", headers=h(tokens["pm"]))
        assert rn.status_code == 200, rn.text
        notifs = rn.json()
        matching = [
            n for n in notifs
            if n.get("title") == "MRF pending review"
            and mrf["mrf_id"] in (n.get("link") or "")
        ]
        assert matching, (
            f"pm@vasu.dev should have received an 'MRF pending review' "
            f"notification for {mrf['mrf_id']}. Got titles: "
            f"{[n.get('title') for n in notifs[:10]]}"
        )


# ---------------- Deduped role-tuple gates: director must be 200 ----------------
class TestDirectorAccessOnDedupedGates:
    @pytest.fixture(scope="class")
    def prepared(self, tokens, vis101):
        mrf = _create_and_approve_mrf(tokens, vis101)
        rpo = _create_po(tokens, vis101, mrf, buyer_role="purchase")
        assert rpo.status_code == 200, rpo.text
        po = rpo.json()
        # Also create an invoice for pdf testing
        inv_body = {
            "po_id": po["po_id"],
            "vendor_invoice_number": f"TEST_INV_{uuid.uuid4().hex[:6]}",
            "invoice_date": "2026-06-20",
            "items": [{
                "item_line_id": po["items"][0]["item_line_id"],
                "description": "TEST_Panel", "unit": "Nos",
                "qty": 2, "rate": 100, "discount": 0, "gst": 18,
            }],
        }
        ri = requests.post(f"{API}/invoice", headers=h(tokens["purchase"]),
                           json=inv_body)
        assert ri.status_code == 200, ri.text
        return {"mrf": mrf, "po": po, "invoice": ri.json(),
                "project": vis101}

    def test_director_can_create_po(self, tokens, vis101):
        # Fresh approved MRF, then director creates PO
        mrf = _create_and_approve_mrf(tokens, vis101)
        rpo = _create_po(tokens, vis101, mrf, buyer_role="director")
        assert rpo.status_code == 200, (
            f"director /po create expected 200, got {rpo.status_code}: {rpo.text}"
        )

    def test_director_can_download_po_pdf(self, tokens, prepared):
        pid = prepared["po"]["po_id"]
        r = requests.get(f"{API}/po/{pid}/pdf", headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /po/{{id}}/pdf expected 200, got {r.status_code}: "
            f"{r.text[:200]}"
        )
        assert r.headers.get("content-type", "").startswith("application/pdf") \
            or r.content[:4] == b"%PDF"

    def test_director_can_create_invoice(self, tokens, prepared):
        inv_body = {
            "po_id": prepared["po"]["po_id"],
            "vendor_invoice_number": f"TEST_DIR_INV_{uuid.uuid4().hex[:6]}",
            "invoice_date": "2026-06-21",
            "items": [{
                "item_line_id": prepared["po"]["items"][0]["item_line_id"],
                "description": "TEST_Panel", "unit": "Nos",
                "qty": 1, "rate": 100, "discount": 0, "gst": 18,
            }],
        }
        r = requests.post(f"{API}/invoice", headers=h(tokens["director"]),
                          json=inv_body)
        assert r.status_code == 200, (
            f"director /invoice create expected 200, got {r.status_code}: "
            f"{r.text}"
        )

    def test_director_can_download_invoice_pdf(self, tokens, prepared):
        iid = prepared["invoice"]["invoice_id"]
        r = requests.get(f"{API}/invoice/{iid}/pdf",
                         headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /invoice/{{id}}/pdf expected 200, got {r.status_code}: "
            f"{r.text[:200]}"
        )

    def test_director_can_list_billing_items(self, tokens):
        r = requests.get(f"{API}/billing/items", headers=h(tokens["director"]))
        assert r.status_code == 200, (
            f"director /billing/items expected 200, got {r.status_code}: "
            f"{r.text}"
        )
        assert isinstance(r.json(), list)


# ---------------- Unrelated fresh pm must not get elevated access ----------------
class TestUnrelatedPMNoElevation:
    @pytest.fixture(scope="class")
    def fresh_pm_token(self):
        email = f"TEST_fresh_pm_{uuid.uuid4().hex[:6]}@vasu.dev"
        r = dev_login(email, "pm", "Fresh PM")
        assert r.status_code == 200, r.text
        return r.json()["session_token"], email

    def test_fresh_pm_cannot_create_po(self, tokens, vis101, fresh_pm_token):
        tok, _ = fresh_pm_token
        # Reuse an approved MRF
        mrf = _create_and_approve_mrf(tokens, vis101)
        rv = requests.get(f"{API}/vendors", headers=h(tokens["admin"]))
        vendor = rv.json()[0]
        body = {
            "vendor_id": vendor["vendor_id"],
            "project_id": vis101["project_id"],
            "delivery_site": vis101["site"],
            "items": [{
                "mrf_id": mrf["mrf_id"],
                "item_line_id": mrf["items"][0]["item_line_id"],
                "description": "TEST_Panel", "unit": "Nos",
                "qty": 1, "rate": 10, "discount": 0, "gst": 18,
            }],
        }
        r = requests.post(f"{API}/po", headers=h(tok), json=body)
        assert r.status_code == 403, f"fresh pm expected 403 on /po create, got {r.status_code}"

    def test_fresh_pm_cannot_access_billing_items(self, fresh_pm_token):
        tok, _ = fresh_pm_token
        r = requests.get(f"{API}/billing/items", headers=h(tok))
        assert r.status_code == 403, (
            f"fresh pm expected 403 on /billing/items, got {r.status_code}"
        )

    def test_fresh_pm_cannot_access_invoices(self, fresh_pm_token):
        tok, _ = fresh_pm_token
        r = requests.get(f"{API}/invoice", headers=h(tok))
        assert r.status_code == 403, (
            f"fresh pm expected 403 on /invoice list, got {r.status_code}"
        )

    def test_fresh_pm_cannot_receive_po(self, tokens, vis101, fresh_pm_token):
        tok, _ = fresh_pm_token
        # Use any existing PO on VIS-101
        r = requests.get(f"{API}/po?project_id={vis101['project_id']}",
                         headers=h(tokens["admin"]))
        assert r.status_code == 200 and r.json()
        po = r.json()[0]
        rr = requests.post(f"{API}/po/{po['po_id']}/received",
                           headers=h(tok), json={})
        assert rr.status_code == 403
