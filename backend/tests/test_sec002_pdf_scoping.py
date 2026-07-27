"""
Iteration 8 — SEC-002 follow-up: role/project scoping on
  GET /api/po (list)
  GET /api/po/{id}/pdf
  GET /api/grn/{grn_id}/pdf
  GET /api/invoice/{inv_id}/pdf
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

SEEDED = {
    "site_engineer": "site@vasu.dev",
    "project_manager": "pm@vasu.dev",
    "purchase": "purchase@vasu.dev",
    "billing": "billing@vasu.dev",
    "admin": "admin@vasu.dev",
}


def _login(email, role, name=None):
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": email, "role": role, "name": name or email})
    assert r.status_code == 200, f"dev-login failed {email}/{role}: {r.status_code} {r.text}"
    j = r.json()
    return j["session_token"], j["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- module-scope fixtures ----------
@pytest.fixture(scope="module")
def tokens():
    admin_tok, admin_u = _login(SEEDED["admin"], "admin")
    r = requests.post(f"{API}/seed", headers=_hdr(admin_tok))
    assert r.status_code == 200, r.text

    toks = {}
    users = {}
    for role, email in SEEDED.items():
        t, u = _login(email, role)
        toks[role] = t
        users[role] = u

    # Fresh unrelated site engineer (on no project, no MRFs)
    stranger_email = f"stranger_{uuid.uuid4().hex[:8]}@vasu.dev"
    t, u = _login(stranger_email, "site_engineer", name="Stranger SE")
    toks["stranger"] = t
    users["stranger"] = u

    # Fresh unrelated PM (on no project)
    pm_stranger_email = f"pmstranger_{uuid.uuid4().hex[:8]}@vasu.dev"
    t, u = _login(pm_stranger_email, "project_manager", name="Stranger PM")
    toks["pm_stranger"] = t
    users["pm_stranger"] = u

    # A second fresh site engineer (creates own MRFs); should NOT see other SE's POs
    se2_email = f"se2_{uuid.uuid4().hex[:8]}@vasu.dev"
    t, u = _login(se2_email, "site_engineer", name="Second SE")
    toks["se2"] = t
    users["se2"] = u
    return {"tokens": toks, "users": users}


@pytest.fixture(scope="module")
def po_and_grn(tokens):
    """Create MRF (by seeded site_engineer) → approve → PO → GRN. Return ids."""
    ttoks = tokens["tokens"]
    r = requests.get(f"{API}/projects", headers=_hdr(ttoks["admin"]))
    assert r.status_code == 200
    projects = r.json()
    proj = next((p for p in projects if p.get("code") == "VIS-101"), projects[0])
    proj_id = proj["project_id"]

    mrf_payload = {
        "project_id": proj_id,
        "site": "Bangalore",
        "required_by": "2026-02-20",
        "requesting_person": "TEST_SEC002_Iter8",
        "system_category": "Fire Safety",
        "items": [{"description": "TEST_Sec002_Iter8 Detector", "unit": "Nos",
                   "qty_requested": 3.0, "brand_preference": "Honeywell"}],
        "remarks": "TEST iter8"
    }
    r = requests.post(f"{API}/mrf", json=mrf_payload, headers=_hdr(ttoks["site_engineer"]))
    assert r.status_code == 200, r.text
    mrf_id = r.json()["mrf_id"]

    r = requests.post(f"{API}/mrf/{mrf_id}/submit", headers=_hdr(ttoks["site_engineer"]))
    assert r.status_code == 200
    r = requests.post(f"{API}/mrf/{mrf_id}/approve",
                      json={"action": "approve", "comment": "ok"},
                      headers=_hdr(ttoks["project_manager"]))
    assert r.status_code == 200

    r = requests.get(f"{API}/mrf/{mrf_id}", headers=_hdr(ttoks["admin"]))
    mrf_full = r.json()
    line = mrf_full["items"][0]

    r = requests.get(f"{API}/vendors", headers=_hdr(ttoks["purchase"]))
    vendor_id = r.json()[0]["vendor_id"]

    po_payload = {
        "vendor_id": vendor_id,
        "project_id": proj_id,
        "delivery_site": "BLR Whitefield",
        "items": [{
            "mrf_id": mrf_id, "item_line_id": line["item_line_id"],
            "description": line["description"], "unit": line["unit"],
            "qty": line.get("qty_approved") or line["qty_requested"],
            "rate": 750, "gst": 18,
        }],
        "delivery_schedule": "1wk", "payment_terms": "Net 30",
        "warranty_terms": "1yr", "freight": 0, "other_charges": 0,
    }
    r = requests.post(f"{API}/po", json=po_payload, headers=_hdr(ttoks["purchase"]))
    assert r.status_code == 200, r.text
    po = r.json()
    po_id = po["po_id"]

    # Receive to create a GRN
    r = requests.post(f"{API}/po/{po_id}/received",
                      json={"items": [{"mrf_id": mrf_id,
                                       "item_line_id": line["item_line_id"], "qty": 1}]},
                      headers=_hdr(ttoks["purchase"]))
    assert r.status_code == 200, r.text

    # Fetch GRN
    r = requests.get(f"{API}/po/{po_id}/grns", headers=_hdr(ttoks["admin"]))
    assert r.status_code == 200, r.text
    grns = r.json()
    assert grns, "expected at least one GRN"
    grn_id = grns[0]["grn_id"]

    # Create Invoice for negative-role tests on invoice PDF
    inv_payload = {
        "po_id": po_id,
        "vendor_id": vendor_id,
        "project_id": proj_id,
        "invoice_ref": f"TEST_INV_{uuid.uuid4().hex[:6]}",
        "invoice_date": "2026-01-20",
        "items": [{
            "mrf_id": mrf_id, "item_line_id": line["item_line_id"],
            "description": line["description"], "unit": line["unit"],
            "qty": 1, "rate": 750, "gst": 18
        }],
        "notes": "TEST iter8 inv"
    }
    r = requests.post(f"{API}/invoice", json=inv_payload, headers=_hdr(ttoks["billing"]))
    assert r.status_code == 200, r.text
    inv_id = r.json()["invoice_id"]

    return {"mrf_id": mrf_id, "po_id": po_id, "grn_id": grn_id,
            "invoice_id": inv_id, "project_id": proj_id}


# ============ GET /api/po list scoping ============
class TestPoListScoping:
    @pytest.mark.parametrize("role", ["admin", "purchase", "billing"])
    def test_full_list_for_privileged_roles(self, tokens, po_and_grn, role):
        r = requests.get(f"{API}/po", headers=_hdr(tokens["tokens"][role]))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Our created PO should be present
        assert any(p["po_id"] == po_and_grn["po_id"] for p in data), \
            f"{role} did not see created PO in list"

    def test_seeded_site_engineer_sees_related_po(self, tokens, po_and_grn):
        r = requests.get(f"{API}/po", headers=_hdr(tokens["tokens"]["site_engineer"]))
        assert r.status_code == 200
        pos = r.json()
        assert isinstance(pos, list)
        assert any(p["po_id"] == po_and_grn["po_id"] for p in pos), \
            "seeded SE (MRF creator) should see the related PO"

    def test_stranger_site_engineer_sees_empty_po_list(self, tokens, po_and_grn):
        r = requests.get(f"{API}/po", headers=_hdr(tokens["tokens"]["stranger"]))
        assert r.status_code == 200
        pos = r.json()
        assert isinstance(pos, list)
        # stranger has created no MRFs → no PO should be visible
        assert pos == [], f"stranger SE saw POs: {[p.get('po_id') for p in pos]}"
        assert not any(p["po_id"] == po_and_grn["po_id"] for p in pos)

    def test_se2_does_not_see_other_se_po(self, tokens, po_and_grn):
        """A second, unrelated SE (created no MRFs) must not see the PO."""
        ttoks = tokens["tokens"]
        r = requests.get(f"{API}/po", headers=_hdr(ttoks["se2"]))
        assert r.status_code == 200
        pos = r.json()
        assert not any(p["po_id"] == po_and_grn["po_id"] for p in pos), \
            "se2 (no MRFs) should not see PO from another SE's MRF"

    def test_pm_stranger_sees_empty(self, tokens, po_and_grn):
        r = requests.get(f"{API}/po", headers=_hdr(tokens["tokens"]["pm_stranger"]))
        assert r.status_code == 200
        pos = r.json()
        assert isinstance(pos, list)
        assert not any(p["po_id"] == po_and_grn["po_id"] for p in pos), \
            "unrelated PM must not see PO from projects they aren't PM of"

    def test_seeded_pm_sees_project_pos(self, tokens, po_and_grn):
        """Seeded pm@vasu.dev is on VIS-101; the created PO is on VIS-101."""
        r = requests.get(f"{API}/po", headers=_hdr(tokens["tokens"]["project_manager"]))
        assert r.status_code == 200
        pos = r.json()
        assert any(p["po_id"] == po_and_grn["po_id"] for p in pos), \
            "seeded PM should see PO for their project"


# ============ GET /api/po/{id}/pdf ============
class TestPoPdfScoping:
    def test_stranger_se_403(self, tokens, po_and_grn):
        tok = tokens["tokens"]["stranger"]
        r = requests.get(f"{API}/po/{po_and_grn['po_id']}/pdf?token={tok}")
        assert r.status_code == 403, f"expected 403 got {r.status_code}"

    def test_creator_se_200(self, tokens, po_and_grn):
        tok = tokens["tokens"]["site_engineer"]
        r = requests.get(f"{API}/po/{po_and_grn['po_id']}/pdf?token={tok}")
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")

    def test_pm_stranger_403(self, tokens, po_and_grn):
        tok = tokens["tokens"]["pm_stranger"]
        r = requests.get(f"{API}/po/{po_and_grn['po_id']}/pdf?token={tok}")
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["admin", "purchase", "billing"])
    def test_privileged_200(self, tokens, po_and_grn, role):
        tok = tokens["tokens"][role]
        r = requests.get(f"{API}/po/{po_and_grn['po_id']}/pdf?token={tok}")
        assert r.status_code == 200, f"{role}: {r.status_code} {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")


# ============ GET /api/grn/{id}/pdf ============
class TestGrnPdfScoping:
    def test_stranger_se_403(self, tokens, po_and_grn):
        tok = tokens["tokens"]["stranger"]
        r = requests.get(f"{API}/grn/{po_and_grn['grn_id']}/pdf?token={tok}")
        assert r.status_code == 403

    def test_creator_se_200(self, tokens, po_and_grn):
        tok = tokens["tokens"]["site_engineer"]
        r = requests.get(f"{API}/grn/{po_and_grn['grn_id']}/pdf?token={tok}")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")

    def test_pm_stranger_403(self, tokens, po_and_grn):
        tok = tokens["tokens"]["pm_stranger"]
        r = requests.get(f"{API}/grn/{po_and_grn['grn_id']}/pdf?token={tok}")
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["admin", "purchase", "billing"])
    def test_privileged_200(self, tokens, po_and_grn, role):
        tok = tokens["tokens"][role]
        r = requests.get(f"{API}/grn/{po_and_grn['grn_id']}/pdf?token={tok}")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")


# ============ GET /api/invoice/{id}/pdf ============
class TestInvoicePdfScoping:
    @pytest.mark.parametrize("role", ["site_engineer", "project_manager", "stranger", "pm_stranger"])
    def test_restricted_roles_403(self, tokens, po_and_grn, role):
        tok = tokens["tokens"][role]
        r = requests.get(f"{API}/invoice/{po_and_grn['invoice_id']}/pdf?token={tok}")
        assert r.status_code == 403, f"{role} got {r.status_code}"

    @pytest.mark.parametrize("role", ["purchase", "billing", "admin"])
    def test_privileged_200(self, tokens, po_and_grn, role):
        tok = tokens["tokens"][role]
        r = requests.get(f"{API}/invoice/{po_and_grn['invoice_id']}/pdf?token={tok}")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
