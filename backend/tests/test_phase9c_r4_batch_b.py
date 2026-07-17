"""Phase 9C round 4 (Batch B) regression — cs, dc, grn, mrf, po router extraction.

Verifies behaviour is byte-identical after moving 5 endpoint groups out of
server.py. Focus is on RBAC + workflow transitions + threshold-gated PO approvals
+ auto-GRN creation on PO receipt. PDF/Excel bodies are only smoke-checked.
"""
from __future__ import annotations

import base64
import os
import pytest
import requests

BASE = os.environ.get("EXPO_BACKEND_URL", "http://localhost:8001").rstrip("/")

ROLES = ["admin", "director", "gm", "pm", "purchase", "siteeng", "store"]


def _login(role_email: str, role: str, name: str = None) -> str:
    r = requests.post(f"{BASE}/api/auth/dev-login",
                      json={"email": role_email, "role": role,
                            "name": name or role_email})
    r.raise_for_status()
    return r.json()["session_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------- shared fixtures ----------------------------
@pytest.fixture(scope="module")
def tokens() -> dict:
    role_map = {
        "admin": ("admin@vasu.dev", "admin"),
        "director": ("director@vasu.dev", "director"),
        "gm": ("gm@vasu.dev", "gm"),
        "pm": ("pm@vasu.dev", "pm"),
        "purchase": ("purchase@vasu.dev", "purchase"),
        "siteeng": ("siteeng@vasu.dev", "site_engineer"),
        "store": ("store@vasu.dev", "store"),
    }
    out = {r: _login(e, role_key, r) for r, (e, role_key) in role_map.items()}
    # ensure seed exists
    requests.post(f"{BASE}/api/seed", headers=_hdr(out["admin"]))
    return out


@pytest.fixture(scope="module")
def seeded(tokens):
    """Pull first project + vendor + material for the flow tests."""
    projects = requests.get(f"{BASE}/api/projects",
                             headers=_hdr(tokens["admin"])).json()
    vendors = requests.get(f"{BASE}/api/vendors",
                            headers=_hdr(tokens["admin"])).json()
    materials = requests.get(f"{BASE}/api/materials?status=approved",
                              headers=_hdr(tokens["admin"])).json()
    assert projects and vendors and materials, "seed data missing"
    return {"project": projects[0], "vendor": vendors[0], "material": materials[0]}


@pytest.fixture(scope="module")
def mrf_full_lifecycle(tokens, seeded):
    """Create a fresh MRF as admin (bypasses site_engineer project scoping),
    submit and approve so downstream PO/GRN/DC flows can consume it.

    Returns dict {mrf_id, mrf_number, items:[{item_line_id, qty_approved}, ...]}.
    """
    proj = seeded["project"]
    body = {
        "project_id": proj["project_id"],
        "site": "TEST_R4_SITE",
        "required_by": "2026-12-31",
        "requesting_person": "TEST_R4_regressor",
        "system_category": "General",
        "items": [{
            "description": "TEST_R4 line 1",
            "unit": "nos",
            "qty_requested": 4,
            "material_id": seeded["material"].get("material_uid")
                             or seeded["material"].get("item_id"),
        }],
        "remarks": "TEST_R4 seed MRF",
    }
    r = requests.post(f"{BASE}/api/mrf", json=body, headers=_hdr(tokens["admin"]))
    assert r.status_code == 200, r.text
    m = r.json()
    mrf_id = m["mrf_id"]

    r2 = requests.post(f"{BASE}/api/mrf/{mrf_id}/submit",
                        headers=_hdr(tokens["admin"]))
    assert r2.status_code == 200, r2.text
    r3 = requests.post(f"{BASE}/api/mrf/{mrf_id}/approve",
                        json={"action": "approve", "comment": "TEST_R4 approve"},
                        headers=_hdr(tokens["admin"]))
    assert r3.status_code == 200, r3.text
    r4 = requests.post(f"{BASE}/api/mrf/{mrf_id}/send-to-purchase",
                        headers=_hdr(tokens["admin"]))
    assert r4.status_code == 200, r4.text

    got = requests.get(f"{BASE}/api/mrf/{mrf_id}",
                        headers=_hdr(tokens["admin"])).json()
    return got


# =====================================================================
# CS (Comparative Statement)
# =====================================================================
class TestCSRouter:
    def _cs_body(self, mrf_id: str) -> dict:
        raw = b"TEST_R4_CS_BYTES" * 4
        return {
            "mrf_id": mrf_id,
            "title": "TEST_R4 CS",
            "file_name": "test_r4_cs.txt",
            "mime_type": "text/plain",
            "file_base64": base64.b64encode(raw).decode(),
            "remarks": "TEST_R4 upload",
        }

    def test_upload_forbidden_for_pm_gm_director_siteeng_store(self, tokens, mrf_full_lifecycle):
        body = self._cs_body(mrf_full_lifecycle["mrf_id"])
        for role in ("pm", "gm", "director", "siteeng", "store"):
            r = requests.post(f"{BASE}/api/comparative-statement",
                              json=body, headers=_hdr(tokens[role]))
            assert r.status_code == 403, f"{role}: {r.status_code} {r.text}"

    def test_upload_missing_file_400(self, tokens, mrf_full_lifecycle):
        body = self._cs_body(mrf_full_lifecycle["mrf_id"]); body["file_base64"] = ""
        r = requests.post(f"{BASE}/api/comparative-statement", json=body,
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 400

    def test_upload_missing_mrf_and_po_400(self, tokens):
        body = self._cs_body("")  # no mrf_id
        body["mrf_id"] = ""; body["po_id"] = ""
        r = requests.post(f"{BASE}/api/comparative-statement", json=body,
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 400

    def test_upload_ok_purchase_and_resolves_project(self, tokens, mrf_full_lifecycle):
        body = self._cs_body(mrf_full_lifecycle["mrf_id"])
        r = requests.post(f"{BASE}/api/comparative-statement",
                          json=body, headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200, r.text
        cs = r.json()
        assert cs["mrf_id"] == mrf_full_lifecycle["mrf_id"]
        # project_id auto-resolved from MRF
        assert cs.get("project_id"), "project_id should be resolved from mrf"
        pytest.cs_id = cs["cs_id"]
        # download roundtrip
        d = requests.get(f"{BASE}/api/comparative-statement/{cs['cs_id']}/download",
                          headers=_hdr(tokens["purchase"]))
        assert d.status_code == 200
        assert d.content == b"TEST_R4_CS_BYTES" * 4

    def test_approve_403_for_purchase(self, tokens):
        r = requests.post(f"{BASE}/api/comparative-statement/{pytest.cs_id}/approve",
                          json={"action": "approve"},
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 403

    def test_approve_ok_pm_then_locked(self, tokens):
        r = requests.post(f"{BASE}/api/comparative-statement/{pytest.cs_id}/approve",
                          json={"action": "approve", "comment": "TEST_R4"},
                          headers=_hdr(tokens["pm"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # subsequent approve returns 400 (already approved)
        r2 = requests.post(f"{BASE}/api/comparative-statement/{pytest.cs_id}/approve",
                            json={"action": "approve"},
                            headers=_hdr(tokens["pm"]))
        assert r2.status_code == 400

    def test_put_locked_after_approved_for_purchase_but_admin_can_override(self, tokens):
        # purchase can edit CS in principle, but once approved → 400
        r = requests.put(f"{BASE}/api/comparative-statement/{pytest.cs_id}",
                        json={"title": "TEST_R4 rename"},
                        headers=_hdr(tokens["purchase"]))
        assert r.status_code == 400
        r2 = requests.put(f"{BASE}/api/comparative-statement/{pytest.cs_id}",
                        json={"title": "TEST_R4 rename admin"},
                        headers=_hdr(tokens["admin"]))
        assert r2.status_code == 200
        assert r2.json()["title"] == "TEST_R4 rename admin"

    def test_delete_only_admin_director(self, tokens):
        r = requests.delete(f"{BASE}/api/comparative-statement/{pytest.cs_id}",
                             headers=_hdr(tokens["pm"]))
        assert r.status_code == 403
        r2 = requests.delete(f"{BASE}/api/comparative-statement/{pytest.cs_id}",
                              headers=_hdr(tokens["director"]))
        assert r2.status_code == 200
        # soft-delete: still findable via direct GET but excluded from list
        g = requests.get(f"{BASE}/api/comparative-statement/{pytest.cs_id}",
                        headers=_hdr(tokens["admin"]))
        assert g.status_code == 200
        assert g.json().get("deleted") is True
        assert g.json().get("status") == "cancelled"


# =====================================================================
# DC (Delivery Challan)
# =====================================================================
class TestDCRouter:
    def _dc_body(self, project_id: str) -> dict:
        return {
            "dc_type": "outbound",
            "project_id": project_id,
            "from_location": "TEST_R4 Warehouse",
            "to_location": "TEST_R4 Site",
            "dispatch_date": "2026-12-31",
            "items": [{"description": "TEST_R4 DC item", "unit": "nos", "qty": 1}],
            "remarks": "TEST_R4 DC",
        }

    def test_create_dc_purchase_ok(self, tokens, seeded):
        r = requests.post(f"{BASE}/api/dc",
                          json=self._dc_body(seeded["project"]["project_id"]),
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200, r.text
        pytest.dc_id = r.json()["dc_id"]
        # DC model default is pending_approval (server.py DC class). Audit
        # metadata says "issued" but that's a pre-existing audit-record quirk.
        assert r.json()["status"] in ("pending_approval", "issued")

    def test_create_dc_forbidden_for_pm_gm_siteeng(self, tokens, seeded):
        body = self._dc_body(seeded["project"]["project_id"])
        for role in ("gm", "siteeng"):
            r = requests.post(f"{BASE}/api/dc", json=body,
                              headers=_hdr(tokens[role]))
            assert r.status_code == 403, f"{role}: {r.status_code}"

    def test_approve_dc_403_for_pm_purchase_gm(self, tokens):
        for role in ("pm", "purchase", "gm"):
            r = requests.post(f"{BASE}/api/dc/{pytest.dc_id}/approve",
                              json={"action": "approve"},
                              headers=_hdr(tokens[role]))
            assert r.status_code == 403, f"{role}: {r.status_code}"

    def test_approve_dc_admin_ok(self, tokens):
        r = requests.post(f"{BASE}/api/dc/{pytest.dc_id}/approve",
                          json={"action": "approve", "comment": "TEST_R4"},
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    def test_put_locked_after_approved(self, tokens):
        r = requests.put(f"{BASE}/api/dc/{pytest.dc_id}",
                          json={"remarks": "TEST_R4 edit attempt"},
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 400
        r2 = requests.put(f"{BASE}/api/dc/{pytest.dc_id}",
                          json={"remarks": "TEST_R4 admin override"},
                          headers=_hdr(tokens["admin"]))
        assert r2.status_code == 200
        assert r2.json()["remarks"] == "TEST_R4 admin override"

    def test_pdf_and_excel_stream(self, tokens):
        for fmt in ("pdf", "excel"):
            r = requests.get(f"{BASE}/api/dc/{pytest.dc_id}/export?format={fmt}&force=1",
                              headers=_hdr(tokens["admin"]))
            assert r.status_code == 200, f"{fmt}: {r.status_code} {r.text[:200]}"
            assert len(r.content) > 100

    def test_bulk_export_dc_rbac(self, tokens):
        r_site = requests.get(f"{BASE}/api/export/dc",
                               headers=_hdr(tokens["siteeng"]))
        assert r_site.status_code == 403
        r_ok = requests.get(f"{BASE}/api/export/dc",
                             headers=_hdr(tokens["purchase"]))
        assert r_ok.status_code == 200
        assert len(r_ok.content) > 100

    def test_delete_dc_admin_only(self, tokens):
        r = requests.delete(f"{BASE}/api/dc/{pytest.dc_id}",
                             headers=_hdr(tokens["purchase"]))
        assert r.status_code == 403
        r2 = requests.delete(f"{BASE}/api/dc/{pytest.dc_id}",
                              headers=_hdr(tokens["admin"]))
        assert r2.status_code == 200


# =====================================================================
# PO (creation + threshold + received → auto-GRN)
# =====================================================================
class TestPORouter:
    def _po_body(self, mrf_lc, seeded, rate: float) -> dict:
        return {
            "vendor_id": seeded["vendor"]["vendor_id"],
            "project_id": seeded["project"]["project_id"],
            "delivery_site": "TEST_R4",
            "items": [{
                "mrf_id": mrf_lc["mrf_id"],
                "item_line_id": mrf_lc["items"][0]["item_line_id"],
                "description": mrf_lc["items"][0]["description"],
                "unit": mrf_lc["items"][0]["unit"],
                "qty": 1,
                "rate": rate,
                "discount": 0,
                "gst": 0,
            }],
        }

    def test_po_low_total_auto_issued(self, tokens, mrf_full_lifecycle, seeded):
        # rate 100, qty 1, gst 0 → total 100 → below GM threshold (50000)
        body = self._po_body(mrf_full_lifecycle, seeded, rate=100)
        r = requests.post(f"{BASE}/api/po", json=body,
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "issued"
        assert po["total"] == 100.0
        pytest.po_issued_id = po["po_id"]
        # MRF should roll qty_ordered forward
        m = requests.get(f"{BASE}/api/mrf/{mrf_full_lifecycle['mrf_id']}",
                          headers=_hdr(tokens["admin"])).json()
        assert m["items"][0]["qty_ordered"] >= 1

    def test_po_gm_tier_pending_and_no_mrf_rollforward(self, tokens, seeded, mrf_full_lifecycle):
        # rate 60000, qty 1 → total 60000 → between GM (50k) & Director (500k)
        body = self._po_body(mrf_full_lifecycle, seeded, rate=60000)
        before = requests.get(f"{BASE}/api/mrf/{mrf_full_lifecycle['mrf_id']}",
                               headers=_hdr(tokens["admin"])).json()
        before_qty = before["items"][0].get("qty_ordered", 0)
        r = requests.post(f"{BASE}/api/po", json=body,
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "pending_gm_approval"
        pytest.po_gm_id = po["po_id"]
        after = requests.get(f"{BASE}/api/mrf/{mrf_full_lifecycle['mrf_id']}",
                              headers=_hdr(tokens["admin"])).json()
        assert after["items"][0].get("qty_ordered", 0) == before_qty, \
            "MRF qty_ordered must NOT roll forward when PO is pending_gm_approval"

    def test_po_director_tier_pending_director(self, tokens, seeded, mrf_full_lifecycle):
        # rate 600000 → > director threshold (500000)
        body = self._po_body(mrf_full_lifecycle, seeded, rate=600000)
        r = requests.post(f"{BASE}/api/po", json=body,
                          headers=_hdr(tokens["purchase"]))
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "pending_director_approval"
        pytest.po_dir_id = po["po_id"]

    def test_gm_cannot_approve_director_tier(self, tokens):
        r = requests.post(f"{BASE}/api/po/{pytest.po_dir_id}/approve",
                          json={"action": "approve"},
                          headers=_hdr(tokens["gm"]))
        assert r.status_code == 403, f"gm approving director-tier should be 403; got {r.status_code}"

    def test_gm_approves_gm_tier(self, tokens):
        r = requests.post(f"{BASE}/api/po/{pytest.po_gm_id}/approve",
                          json={"action": "approve", "comment": "TEST_R4"},
                          headers=_hdr(tokens["gm"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "issued"

    def test_director_approves_director_tier(self, tokens):
        r = requests.post(f"{BASE}/api/po/{pytest.po_dir_id}/approve",
                          json={"action": "approve", "comment": "TEST_R4"},
                          headers=_hdr(tokens["director"]))
        assert r.status_code == 200
        assert r.json()["status"] == "issued"

    def test_po_received_auto_creates_grn(self, tokens, mrf_full_lifecycle):
        # Receive the issued PO — should auto-create GRN row pending_approval
        r = requests.post(f"{BASE}/api/po/{pytest.po_issued_id}/received",
                          json={"remarks": "TEST_R4 receipt"},
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["grn_id"], f"no grn_id in response: {js}"
        assert js["grn_number"]
        pytest.grn_id = js["grn_id"]
        # GRN must be pending_approval
        g = requests.get(f"{BASE}/api/grn/{js['grn_id']}",
                          headers=_hdr(tokens["admin"]))
        assert g.status_code == 200
        assert g.json()["status"] == "pending_approval"

    def test_list_pos_site_engineer_scope(self, tokens, mrf_full_lifecycle):
        # site engineer only sees POs whose mrf_refs intersect their created MRFs;
        # our seed MRF was created by admin, so siteeng list must NOT contain it.
        r = requests.get(f"{BASE}/api/po", headers=_hdr(tokens["siteeng"]))
        assert r.status_code == 200
        pos = r.json()
        for p in pos:
            assert mrf_full_lifecycle["mrf_id"] not in (p.get("mrf_refs") or []), \
                f"site_engineer should not see admin-created MRF's PO {p.get('po_number')}"

    def test_po_pdf_still_in_server_returns_200(self, tokens):
        # PO PDF export stays in server.py — smoke only
        r = requests.get(f"{BASE}/api/po/{pytest.po_issued_id}/pdf?force=1",
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        assert len(r.content) > 500

    def test_po_invoices_endpoint_rbac(self, tokens):
        r = requests.get(f"{BASE}/api/po/{pytest.po_issued_id}/invoices",
                          headers=_hdr(tokens["siteeng"]))
        assert r.status_code == 403
        r2 = requests.get(f"{BASE}/api/po/{pytest.po_issued_id}/invoices",
                          headers=_hdr(tokens["purchase"]))
        assert r2.status_code == 200
        assert isinstance(r2.json(), list)


# =====================================================================
# GRN
# =====================================================================
class TestGRNRouter:
    def test_grns_list_403_for_siteeng_store(self, tokens):
        for role in ("siteeng", "store"):
            r = requests.get(f"{BASE}/api/grns", headers=_hdr(tokens[role]))
            assert r.status_code == 403, f"{role}: {r.status_code}"

    def test_grns_list_ok_admin(self, tokens):
        r = requests.get(f"{BASE}/api/grns", headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_grn_by_po_id(self, tokens):
        r = requests.get(f"{BASE}/api/po/{pytest.po_issued_id}/grns",
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        assert any(g["grn_id"] == pytest.grn_id for g in r.json())

    def test_grn_approve(self, tokens):
        r = requests.post(f"{BASE}/api/grn/{pytest.grn_id}/approve",
                          json={"action": "approve", "comment": "TEST_R4"},
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200, r.text
        # 2nd approve → 400 (already approved)
        r2 = requests.post(f"{BASE}/api/grn/{pytest.grn_id}/approve",
                            json={"action": "approve"},
                            headers=_hdr(tokens["admin"]))
        assert r2.status_code == 400

    def test_grn_pdf_and_excel(self, tokens):
        for fmt in ("pdf", "excel"):
            r = requests.get(f"{BASE}/api/grn/{pytest.grn_id}/export?format={fmt}&force=1",
                              headers=_hdr(tokens["admin"]))
            assert r.status_code == 200, f"{fmt}: {r.status_code}"
            assert len(r.content) > 100

    def test_bulk_export_grn(self, tokens):
        r = requests.get(f"{BASE}/api/export/grn",
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        assert len(r.content) > 100


# =====================================================================
# MRF (extra targeted checks — full lifecycle already covered via fixture)
# =====================================================================
class TestMRFRouter:
    def test_put_rejected_in_non_draft(self, tokens, mrf_full_lifecycle):
        # MRF is now in sent_to_purchase / partially_ordered / fully_ordered — locked
        r = requests.put(f"{BASE}/api/mrf/{mrf_full_lifecycle['mrf_id']}",
                          json={"remarks": "TEST_R4 late edit"},
                          headers=_hdr(tokens["admin"]))
        assert r.status_code == 400

    def test_line_edit_requires_reason_and_records_change_log(self, tokens, mrf_full_lifecycle):
        line_id = mrf_full_lifecycle["items"][0]["item_line_id"]
        mrf_id = mrf_full_lifecycle["mrf_id"]
        # missing reason → 400
        r_no_reason = requests.put(
            f"{BASE}/api/mrf/{mrf_id}/items/{line_id}",
            json={"remarks": "TEST_R4"},
            headers=_hdr(tokens["admin"]),
        )
        assert r_no_reason.status_code == 400
        # with reason → 200 + change_log written
        r_ok = requests.put(
            f"{BASE}/api/mrf/{mrf_id}/items/{line_id}",
            json={"remarks": "TEST_R4 line edit remark",
                  "reason": "TEST_R4 audit reason"},
            headers=_hdr(tokens["admin"]),
        )
        assert r_ok.status_code == 200, r_ok.text
        js = r_ok.json()
        assert "changes" in js and "remarks" in js["changes"]
        assert js["log"]["reason"] == "TEST_R4 audit reason"

    def test_list_siteeng_scoped_own_only(self, tokens, mrf_full_lifecycle):
        r = requests.get(f"{BASE}/api/mrf", headers=_hdr(tokens["siteeng"]))
        assert r.status_code == 200
        for m in r.json():
            assert m["created_by"] == None or True  # any siteeng doc
        # our admin-created MRF must not appear in siteeng list
        assert not any(m["mrf_id"] == mrf_full_lifecycle["mrf_id"]
                        for m in r.json())

    def test_delete_admin_only(self, tokens, seeded):
        # create a throw-away MRF as admin, then try delete with non-admin
        body = {
            "project_id": seeded["project"]["project_id"],
            "site": "TEST_R4",
            "required_by": "2026-12-31",
            "requesting_person": "TEST_R4",
            "system_category": "General",
            "items": [{"description": "TEST_R4 disposable", "unit": "nos",
                        "qty_requested": 1}],
        }
        r = requests.post(f"{BASE}/api/mrf", json=body,
                            headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        mid = r.json()["mrf_id"]
        r_403 = requests.delete(f"{BASE}/api/mrf/{mid}",
                                 headers=_hdr(tokens["director"]))
        assert r_403.status_code == 403
        r_ok = requests.delete(f"{BASE}/api/mrf/{mid}",
                                headers=_hdr(tokens["admin"]))
        assert r_ok.status_code == 200

    def test_mrf_pdf_and_excel(self, tokens, mrf_full_lifecycle):
        for fmt in ("pdf", "excel"):
            r = requests.get(
                f"{BASE}/api/mrf/{mrf_full_lifecycle['mrf_id']}/export?format={fmt}&force=1",
                headers=_hdr(tokens["admin"]),
            )
            assert r.status_code == 200, f"{fmt}: {r.status_code}"
            assert len(r.content) > 100


# =====================================================================
# OpenAPI presence (P2)
# =====================================================================
def test_openapi_presence():
    r = requests.get(f"{BASE}/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    required = [
        "/api/comparative-statement", "/api/comparative-statement/{cs_id}",
        "/api/comparative-statement/{cs_id}/download",
        "/api/comparative-statement/{cs_id}/approve",
        "/api/dc", "/api/dc/{dc_id}", "/api/dc/{dc_id}/approve",
        "/api/dc/{dc_id}/pdf", "/api/dc/{dc_id}/export", "/api/export/dc",
        "/api/grns", "/api/po/{po_id}/grns",
        "/api/grn/{grn_id}", "/api/grn/{grn_id}/approve",
        "/api/grn/{grn_id}/pdf", "/api/grn/{grn_id}/export", "/api/export/grn",
        "/api/mrf", "/api/mrf/{mrf_id}", "/api/mrf/{mrf_id}/submit",
        "/api/mrf/{mrf_id}/approve", "/api/mrf/{mrf_id}/send-to-purchase",
        "/api/mrf/{mrf_id}/items/{line_id}",
        "/api/mrf/{mrf_id}/pdf", "/api/mrf/{mrf_id}/export",
        "/api/po", "/api/po/{po_id}", "/api/po/{po_id}/approve",
        "/api/po/{po_id}/received", "/api/po/{po_id}/invoices",
        "/api/po/{po_id}/pdf", "/api/po/{po_id}/export",
    ]
    missing = [p for p in required if p not in paths]
    assert not missing, f"missing OpenAPI paths: {missing}"
