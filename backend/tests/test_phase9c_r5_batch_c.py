"""Phase 9C Round 5 (Batch C) — regression suite for the 7 newly-extracted routers.

Covers:
    routers/billing.py, routers/invoice.py, routers/imports.py,
    routers/vendors.py, routers/projects.py, routers/auth.py, routers/po_exports.py

Plus:
    - DC audit-fix verification (routers/dc.py:88)
    - OpenAPI presence for all 22 newly-refactored paths
    - PO PDF CGST/SGST/IGST split correctness (intra vs inter-state)
"""
from __future__ import annotations
import io
import os
import time
import uuid
import pytest
import requests
import openpyxl

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ROLES = ["admin", "director", "gm", "pm", "purchase", "site_engineer", "store"]


# ---------------------- helpers ----------------------
def _login(role: str) -> str:
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": f"{role}@vasu.dev", "role": role,
                            "name": role.title()}, timeout=10)
    assert r.status_code == 200, f"dev-login({role}) → {r.status_code} {r.text}"
    return r.json()["session_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tokens() -> dict:
    return {r: _login(r) for r in ROLES}


@pytest.fixture(scope="module")
def seeded(tokens):
    """Ensure baseline seed exists (idempotent)."""
    requests.post(f"{API}/seed", headers=_hdr(tokens["admin"]), timeout=10)
    return True


# ==========================================================
# P0 — Auth router
# ==========================================================
class TestAuthRouter:
    def test_dev_login_missing_email(self):
        r = requests.post(f"{API}/auth/dev-login",
                          json={"role": "pm", "name": "x"}, timeout=10)
        assert r.status_code == 400

    def test_dev_login_invalid_role(self):
        r = requests.post(f"{API}/auth/dev-login",
                          json={"email": "x@x.com", "role": "hacker",
                                "name": "x"}, timeout=10)
        assert r.status_code == 400

    def test_auth_me_ok(self, tokens):
        r = requests.get(f"{API}/auth/me", headers=_hdr(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_auth_me_no_bearer(self):
        r = requests.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 401

    def test_auth_session_invalid_id(self):
        r = requests.post(f"{API}/auth/session",
                          json={"session_id": "invalid_" + uuid.uuid4().hex},
                          timeout=15)
        assert r.status_code == 401

    def test_logout_ok(self):
        # Fresh dev-login so we don't invalidate module-scoped tokens
        tok = _login("pm")
        r = requests.post(f"{API}/auth/logout", headers=_hdr(tok), timeout=10)
        assert r.status_code == 200
        # After logout, /auth/me should 401
        r2 = requests.get(f"{API}/auth/me", headers=_hdr(tok), timeout=10)
        assert r2.status_code == 401

    def test_users_admin_full(self, tokens):
        r = requests.get(f"{API}/users", headers=_hdr(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) and len(data) > 0
        # Admin sees emails
        assert any((u.get("email") or "") != "" for u in data)

    def test_users_non_admin_stripped(self, tokens):
        r = requests.get(f"{API}/users", headers=_hdr(tokens["pm"]), timeout=10)
        assert r.status_code == 200
        data = r.json()
        # All emails should be blanked
        assert all(u.get("email") == "" for u in data)

    def test_set_role_non_admin_forbidden(self, tokens):
        r = requests.post(f"{API}/users/role",
                          headers=_hdr(tokens["pm"]),
                          json={"user_id": "user_x", "role": "pm"}, timeout=10)
        assert r.status_code == 403

    def test_set_role_invalid_role(self, tokens):
        # find any user
        users = requests.get(f"{API}/users",
                             headers=_hdr(tokens["admin"]), timeout=10).json()
        uid = users[0]["user_id"]
        r = requests.post(f"{API}/users/role",
                          headers=_hdr(tokens["admin"]),
                          json={"user_id": uid, "role": "hacker"}, timeout=10)
        assert r.status_code == 400

    def test_set_role_user_not_found(self, tokens):
        r = requests.post(f"{API}/users/role",
                          headers=_hdr(tokens["admin"]),
                          json={"user_id": "user_nope_xxx", "role": "pm"},
                          timeout=10)
        assert r.status_code == 404


# ==========================================================
# P0 — Vendors router
# ==========================================================
class TestVendorsRouter:
    _vendor_id = None

    def test_list_any_authed(self, tokens):
        for role in ("pm", "site_engineer", "admin", "purchase"):
            r = requests.get(f"{API}/vendors",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 200, f"vendors list {role} → {r.status_code}"
            assert isinstance(r.json(), list)

    def test_create_forbidden_for_pm(self, tokens):
        vid = f"vnd_test_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/vendors", headers=_hdr(tokens["pm"]),
                          json={"vendor_id": vid, "name": "TEST_R5 Vendor",
                                "address": "Maharashtra", "gstin": "",
                                "contact": "", "email": "", "active": True},
                          timeout=10)
        assert r.status_code == 403

    def test_create_ok_for_purchase(self, tokens):
        vid = f"vnd_test_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/vendors", headers=_hdr(tokens["purchase"]),
                          json={"vendor_id": vid,
                                "name": f"TEST_R5 Vendor {uuid.uuid4().hex[:4]}",
                                "address": "Maharashtra 400001", "gstin": "27AAAAA0000A1Z1",
                                "contact": "9800000000", "email": "t@t.com",
                                "active": True},
                          timeout=10)
        assert r.status_code == 200, r.text
        TestVendorsRouter._vendor_id = vid

    def test_update_requires_reason(self, tokens):
        vid = TestVendorsRouter._vendor_id
        assert vid, "prior create failed"
        r = requests.put(f"{API}/vendors/{vid}", headers=_hdr(tokens["purchase"]),
                         json={"name": "TEST_R5 Vendor RENAMED"}, timeout=10)
        assert r.status_code == 400

    def test_update_ok_with_reason(self, tokens):
        vid = TestVendorsRouter._vendor_id
        r = requests.put(f"{API}/vendors/{vid}", headers=_hdr(tokens["purchase"]),
                         json={"name": "TEST_R5 Vendor RENAMED",
                               "reason": "Test rename"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_R5 Vendor RENAMED"

    def test_soft_delete(self, tokens):
        vid = TestVendorsRouter._vendor_id
        r = requests.delete(f"{API}/vendors/{vid}?reason=cleanup",
                            headers=_hdr(tokens["purchase"]), timeout=10)
        assert r.status_code == 200
        # GET list should exclude it now (active=false)
        vendors = requests.get(f"{API}/vendors",
                               headers=_hdr(tokens["admin"]), timeout=10).json()
        assert not any(v["vendor_id"] == vid for v in vendors)


# ==========================================================
# P0 — Projects router
# ==========================================================
class TestProjectsRouter:
    def test_list_admin_sees_all(self, tokens, seeded):
        r = requests.get(f"{API}/projects",
                         headers=_hdr(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list) and len(r.json()) >= 1

    def test_list_purchase_gm_director_see_all(self, tokens):
        admin_count = len(requests.get(f"{API}/projects",
                                       headers=_hdr(tokens["admin"]),
                                       timeout=10).json())
        for role in ("purchase", "gm", "director"):
            docs = requests.get(f"{API}/projects",
                                headers=_hdr(tokens[role]),
                                timeout=10).json()
            assert len(docs) == admin_count, f"{role} count mismatch"

    def test_list_pm_scoped(self, tokens):
        # pm@vasu.dev user is not necessarily in project_managers → likely empty list
        r = requests.get(f"{API}/projects",
                         headers=_hdr(tokens["pm"]), timeout=10)
        assert r.status_code == 200
        docs = r.json()
        me = requests.get(f"{API}/auth/me",
                          headers=_hdr(tokens["pm"]), timeout=10).json()
        for p in docs:
            assert me["user_id"] in (p.get("project_managers") or [])

    def test_create_forbidden_non_admin(self, tokens):
        r = requests.post(f"{API}/projects",
                          headers=_hdr(tokens["pm"]),
                          json={"project_id": f"prj_{uuid.uuid4().hex[:6]}",
                                "code": f"TEST_R5_{uuid.uuid4().hex[:4]}",
                                "name": "TEST_R5 Project",
                                "site": "Site A"},
                          timeout=10)
        assert r.status_code == 403

    def test_create_invalid_customer(self, tokens):
        r = requests.post(f"{API}/projects",
                          headers=_hdr(tokens["admin"]),
                          json={"project_id": f"prj_{uuid.uuid4().hex[:6]}",
                                "code": f"TEST_R5_{uuid.uuid4().hex[:4]}",
                                "name": "TEST_R5 Project",
                                "site": "Site A",
                                "customer_id": "cust_nope_xxx"},
                          timeout=10)
        assert r.status_code == 400

    def test_update_requires_reason(self, tokens):
        docs = requests.get(f"{API}/projects",
                            headers=_hdr(tokens["admin"]), timeout=10).json()
        pid = docs[0]["project_id"]
        r = requests.put(f"{API}/projects/{pid}",
                         headers=_hdr(tokens["admin"]),
                         json={"name": "renamed"}, timeout=10)
        assert r.status_code == 400

    def test_site_add_admin_only(self, tokens):
        docs = requests.get(f"{API}/projects",
                            headers=_hdr(tokens["admin"]), timeout=10).json()
        pid = docs[0]["project_id"]
        r_pm = requests.post(f"{API}/projects/{pid}/sites",
                             headers=_hdr(tokens["pm"]),
                             json={"name": "TEST_R5 Site"}, timeout=10)
        assert r_pm.status_code == 403
        r_ad = requests.post(f"{API}/projects/{pid}/sites",
                             headers=_hdr(tokens["admin"]),
                             json={"name": f"TEST_R5 Site {uuid.uuid4().hex[:4]}"},
                             timeout=10)
        assert r_ad.status_code == 200

    def test_team_admin_only(self, tokens):
        docs = requests.get(f"{API}/projects",
                            headers=_hdr(tokens["admin"]), timeout=10).json()
        pid = docs[0]["project_id"]
        r = requests.post(f"{API}/projects/{pid}/team",
                         headers=_hdr(tokens["pm"]),
                         json={"site_engineers": []}, timeout=10)
        assert r.status_code == 403


# ==========================================================
# P0 — Billing router
# ==========================================================
class TestBillingRouter:
    def test_list_rbac(self, tokens):
        for role in ("pm", "gm", "site_engineer", "store"):
            r = requests.get(f"{API}/billing/items",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 403, f"{role} should be 403 got {r.status_code}"
        for role in ("purchase", "admin", "director"):
            r = requests.get(f"{API}/billing/items",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_list_filter(self, tokens):
        r = requests.get(f"{API}/billing/items?filter=not_billed",
                         headers=_hdr(tokens["purchase"]), timeout=10)
        assert r.status_code == 200
        for row in r.json():
            assert row["billing_status"] == "not_billed"

    def test_update_requires_override_when_billed_lt_received(self, tokens):
        rows = requests.get(f"{API}/billing/items",
                            headers=_hdr(tokens["purchase"]), timeout=10).json()
        if not rows:
            pytest.skip("no billing line available to test")
        row = rows[0]
        # Setup qty_received > qty_billed then try fully_billed with no override
        r = requests.post(f"{API}/billing/update",
                          headers=_hdr(tokens["purchase"]),
                          json={"mrf_id": row["mrf_id"],
                                "item_line_id": row["item_line_id"],
                                "qty_received": 10, "qty_billed": 3,
                                "billing_status": "fully_billed"}, timeout=10)
        assert r.status_code == 400, r.text


# ==========================================================
# P0 — Invoice router
# ==========================================================
class TestInvoiceRouter:
    def test_list_rbac(self, tokens):
        for role in ("pm", "gm", "site_engineer"):
            r = requests.get(f"{API}/invoice",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 403
        for role in ("purchase", "director", "admin"):
            r = requests.get(f"{API}/invoice",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 200

    def test_create_rbac(self, tokens):
        r = requests.post(f"{API}/invoice",
                          headers=_hdr(tokens["pm"]),
                          json={"po_id": "po_nope", "items": []},
                          timeout=10)
        assert r.status_code == 403


# ==========================================================
# P0 — Imports router
# ==========================================================
class TestImportsRouter:
    def test_vendor_template_any_authed(self, tokens):
        for role in ("pm", "site_engineer", "purchase", "admin"):
            r = requests.get(f"{API}/import/vendors/template",
                             headers=_hdr(tokens[role]), timeout=10)
            assert r.status_code == 200
            assert r.headers.get("content-type", "").startswith(
                "application/vnd.openxmlformats")

    def test_mrf_template_any_authed(self, tokens):
        r = requests.get(f"{API}/import/mrf/template",
                         headers=_hdr(tokens["site_engineer"]), timeout=10)
        assert r.status_code == 200

    def test_vendors_import_rbac(self, tokens):
        # pm forbidden
        r = requests.post(f"{API}/import/vendors",
                          headers=_hdr(tokens["pm"]),
                          files={"file": ("x.xlsx", b"", "application/octet-stream")},
                          timeout=10)
        assert r.status_code == 403

    def test_vendors_import_wrong_extension(self, tokens):
        r = requests.post(f"{API}/import/vendors",
                          headers=_hdr(tokens["purchase"]),
                          files={"file": ("x.csv", b"a,b,c", "text/csv")},
                          timeout=10)
        assert r.status_code == 400

    def test_vendors_import_oversized(self, tokens):
        big = b"0" * (5 * 1024 * 1024 + 100)  # >5MB
        r = requests.post(f"{API}/import/vendors",
                          headers=_hdr(tokens["purchase"]),
                          files={"file": ("big.xlsx", big,
                                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                          timeout=15)
        assert r.status_code == 413

    def test_vendors_import_dedup(self, tokens):
        # Build in-memory xlsx with 1 vendor row that already exists
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "address", "gstin", "contact", "email"])
        ws.append(["TEST_R5_dedup_vendor", "Pune", "", "", ""])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        # First import → inserted=1
        r1 = requests.post(f"{API}/import/vendors",
                           headers=_hdr(tokens["purchase"]),
                           files={"file": ("v.xlsx", buf.getvalue(),
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                           timeout=15)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert "inserted" in d1 and "skipped" in d1 and "errors" in d1
        # Second import → skipped=1
        buf.seek(0)
        r2 = requests.post(f"{API}/import/vendors",
                           headers=_hdr(tokens["purchase"]),
                           files={"file": ("v.xlsx", buf.getvalue(),
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                           timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["skipped"] >= 1

    def test_mrf_import_rbac(self, tokens):
        # purchase forbidden
        r = requests.post(f"{API}/import/mrf",
                          headers=_hdr(tokens["purchase"]),
                          files={"file": ("x.xlsx", b"", "application/octet-stream")},
                          timeout=10)
        assert r.status_code == 403
        # gm forbidden
        r = requests.post(f"{API}/import/mrf",
                          headers=_hdr(tokens["gm"]),
                          files={"file": ("x.xlsx", b"", "application/octet-stream")},
                          timeout=10)
        assert r.status_code == 403


# ==========================================================
# P0 — PO Exports router (heaviest)
# ==========================================================
class TestPOExportsRouter:
    _po_id = None
    _vendor_intra = None
    _vendor_inter = None

    @classmethod
    def _create_vendor(cls, tokens, address):
        vid = f"vnd_r5_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/vendors",
                          headers=_hdr(tokens["purchase"]),
                          json={"vendor_id": vid,
                                "name": f"TEST_R5 GST vendor {uuid.uuid4().hex[:4]}",
                                "address": address,
                                "gstin": "27AAAAA0000A1Z1",
                                "contact": "9800000000", "email": "",
                                "active": True}, timeout=10)
        assert r.status_code == 200
        return vid

    @staticmethod
    def _create_full_po(tokens, vendor_id):
        # Build a project MRF cycle → PO
        prj = requests.get(f"{API}/projects",
                           headers=_hdr(tokens["admin"]), timeout=10).json()[0]
        # MRF: create by admin then submit → approve → send-to-purchase
        r = requests.post(f"{API}/mrf",
                          headers=_hdr(tokens["admin"]),
                          json={"project_id": prj["project_id"],
                                "site": prj.get("site", "Site A"),
                                "required_by": "2026-06-01",
                                "requesting_person": "TEST_R5",
                                "system_category": "Fire Alarm",
                                "items": [{"description": "Smoke Detector",
                                           "specification": "spec",
                                           "unit": "Nos", "qty_requested": 1}],
                                "remarks": "TEST_R5_po_export"}, timeout=10)
        assert r.status_code == 200, r.text
        mrf = r.json()
        mid = mrf["mrf_id"]
        for step, body in (("submit", None),
                            ("approve", {"action": "approve", "comment": "ok"}),
                            ("send-to-purchase", None)):
            rs = requests.post(f"{API}/mrf/{mid}/{step}",
                               headers=_hdr(tokens["admin"]),
                               json=body, timeout=10)
            assert rs.status_code == 200, f"{step} {rs.status_code} {rs.text}"
        # Now create PO from purchase
        po_body = {
            "vendor_id": vendor_id,
            "project_id": prj["project_id"],
            "mrf_refs": [mid],
            "delivery_site": prj.get("site", "Site A"),
            "items": [{
                "mrf_id": mid,
                "item_line_id": mrf["items"][0]["item_line_id"],
                "description": "Smoke Detector",
                "unit": "Nos", "qty": 1, "rate": 100, "gst": 18, "discount": 0,
            }],
            "delivery_terms": "7 days", "payment_terms": "Net 30",
            "remarks": "TEST_R5_po_export",
        }
        r = requests.post(f"{API}/po", headers=_hdr(tokens["purchase"]),
                          json=po_body, timeout=10)
        assert r.status_code == 200, r.text
        return r.json()

    def test_setup_pos_with_intra_inter_vendors(self, tokens):
        TestPOExportsRouter._vendor_intra = self._create_vendor(
            tokens, "Mumbai Maharashtra 400001")
        TestPOExportsRouter._vendor_inter = self._create_vendor(
            tokens, "Bangalore Karnataka 560001")
        po_intra = self._create_full_po(tokens, self._vendor_intra)
        TestPOExportsRouter._po_id = po_intra["po_id"]
        assert TestPOExportsRouter._po_id

    def test_po_pdf_intra_state(self, tokens):
        pid = TestPOExportsRouter._po_id
        r = requests.get(f"{API}/po/{pid}/pdf?force=1",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_po_pdf_via_token_query(self, tokens):
        # SEC-003 (post-audit hardening): URL `?token=` no longer accepts raw
        # session tokens — a short-lived `dt_*` download token is required.
        # Mint one, then use it. The old direct session-token flow is asserted
        # in test_iter29_security.py.
        pid = TestPOExportsRouter._po_id
        mint = requests.post(f"{API}/auth/download-token",
                              headers={"Authorization": f"Bearer {tokens['admin']}"},
                              timeout=15).json()
        dt = mint["token"]
        r = requests.get(f"{API}/po/{pid}/pdf?force=1&token={dt}", timeout=15)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_gst_split_helpers_intra(self):
        """Direct unit check of the helper — imported via server module."""
        from server import _split_gst_amt, _is_intra_state
        assert _is_intra_state("Mumbai Maharashtra") is True
        assert _is_intra_state("Bangalore Karnataka") is False
        # Intra-state 100 @ 18% = 18 → 9 CGST + 9 SGST + 0 IGST
        c, s, i = _split_gst_amt(100.0, 18.0, True)
        assert (c, s, i) == (9.0, 9.0, 0.0)
        # Inter-state → 0, 0, 18
        c, s, i = _split_gst_amt(100.0, 18.0, False)
        assert (c, s, i) == (0.0, 0.0, 18.0)

    def test_bulk_export_mrf_rbac(self, tokens):
        for role in ("site_engineer", "store"):
            r = requests.get(f"{API}/export/mrf",
                             headers=_hdr(tokens[role]), timeout=15)
            assert r.status_code == 403, f"{role} → {r.status_code}"
        r = requests.get(f"{API}/export/mrf",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200

    def test_bulk_export_po_rbac(self, tokens):
        for role in ("site_engineer", "store"):
            r = requests.get(f"{API}/export/po",
                             headers=_hdr(tokens[role]), timeout=15)
            assert r.status_code == 403
        r = requests.get(f"{API}/export/po",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200

    def test_bulk_export_tally_rbac(self, tokens):
        r = requests.get(f"{API}/export/tally",
                         headers=_hdr(tokens["site_engineer"]), timeout=15)
        assert r.status_code == 403
        r = requests.get(f"{API}/export/tally?kind=purchase",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200

    def test_po_export_dispatcher_pdf(self, tokens):
        pid = TestPOExportsRouter._po_id
        r = requests.get(f"{API}/po/{pid}/export?format=pdf&force=1",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_po_export_dispatcher_excel(self, tokens):
        pid = TestPOExportsRouter._po_id
        r = requests.get(f"{API}/po/{pid}/export?format=excel&force=1",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "openxml" in ct

    def test_po_export_dispatcher_tally(self, tokens):
        pid = TestPOExportsRouter._po_id
        r = requests.get(f"{API}/po/{pid}/export?format=tally&force=1",
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200

    def test_po_export_dispatcher_invalid_format(self, tokens):
        pid = TestPOExportsRouter._po_id
        r = requests.get(f"{API}/po/{pid}/export?format=jpg",
                         headers=_hdr(tokens["admin"]), timeout=10)
        assert r.status_code == 400


# ==========================================================
# P0 — DC audit fix (routers/dc.py:88)
# ==========================================================
class TestDCAuditFix:
    def test_create_dc_audit_status_is_pending_approval(self, tokens):
        # Create a minimal DC
        prj = requests.get(f"{API}/projects",
                           headers=_hdr(tokens["admin"]), timeout=10).json()[0]
        body = {
            "project_id": prj["project_id"],
            "dc_type": "outbound",
            "from_location": "Warehouse",
            "to_location": "Site",
            "dispatch_date": "2026-06-01",
            "items": [{"description": "Cable", "unit": "Mtr", "qty": 10}],
            "remarks": "TEST_R5_audit_check",
        }
        r = requests.post(f"{API}/dc", headers=_hdr(tokens["purchase"]),
                          json=body, timeout=10)
        assert r.status_code == 200, r.text
        dc = r.json()
        assert dc["status"] == "pending_approval"

        # Now fetch the audit row for this create via /api/audit
        r2 = requests.get(f"{API}/audit?entity=dc&entity_id={dc['dc_id']}",
                          headers=_hdr(tokens["admin"]), timeout=10)
        assert r2.status_code == 200, r2.text
        rows = r2.json()
        if isinstance(rows, dict) and "items" in rows:
            rows = rows["items"]
        creates = [row for row in rows if row.get("action") == "create"]
        assert creates, "No create audit row found for the new DC"
        details = creates[0].get("details") or {}
        new_value = details.get("new_value") or {}
        new_status = new_value.get("status")
        assert new_status == "pending_approval", \
            f"DC audit new_value.status was '{new_status}', expected 'pending_approval'"


# ==========================================================
# P2 — OpenAPI presence (22 newly-refactored paths)
# ==========================================================
class TestOpenAPIPresence:
    @pytest.fixture(scope="class")
    def spec(self):
        r = requests.get(f"{BASE_URL}/openapi.json", timeout=15)
        assert r.status_code == 200
        return r.json()

    def _has(self, spec, path, method):
        return path in spec["paths"] and method.lower() in spec["paths"][path]

    def test_billing_paths(self, spec):
        assert self._has(spec, "/api/billing/items", "get")
        assert self._has(spec, "/api/billing/update", "post")

    def test_invoice_paths(self, spec):
        assert self._has(spec, "/api/invoice", "post")
        assert self._has(spec, "/api/invoice", "get")
        assert self._has(spec, "/api/invoice/{inv_id}", "get")
        assert self._has(spec, "/api/invoice/{inv_id}/pdf", "get")

    def test_import_paths(self, spec):
        assert self._has(spec, "/api/import/vendors/template", "get")
        assert self._has(spec, "/api/import/mrf/template", "get")
        assert self._has(spec, "/api/import/vendors", "post")
        assert self._has(spec, "/api/import/mrf", "post")

    def test_vendor_paths(self, spec):
        assert self._has(spec, "/api/vendors", "get")
        assert self._has(spec, "/api/vendors", "post")
        assert self._has(spec, "/api/vendors/{vendor_id}", "put")
        assert self._has(spec, "/api/vendors/{vendor_id}", "delete")

    def test_project_paths(self, spec):
        assert self._has(spec, "/api/projects", "get")
        assert self._has(spec, "/api/projects", "post")
        assert self._has(spec, "/api/projects/{project_id}", "put")
        assert self._has(spec, "/api/projects/{project_id}", "delete")
        assert self._has(spec, "/api/projects/{project_id}/sites", "post")
        assert self._has(spec, "/api/projects/{project_id}/sites/{site_id}", "put")
        assert self._has(spec, "/api/projects/{project_id}/sites/{site_id}", "delete")
        assert self._has(spec, "/api/projects/{project_id}/team", "post")

    def test_auth_paths(self, spec):
        assert self._has(spec, "/api/auth/session", "post")
        assert self._has(spec, "/api/auth/me", "get")
        assert self._has(spec, "/api/auth/logout", "post")
        assert self._has(spec, "/api/auth/dev-login", "post")
        assert self._has(spec, "/api/users", "get")
        assert self._has(spec, "/api/users/role", "post")

    def test_po_export_paths(self, spec):
        assert self._has(spec, "/api/po/{po_id}/pdf", "get")
        assert self._has(spec, "/api/export/mrf", "get")
        assert self._has(spec, "/api/export/po", "get")
        assert self._has(spec, "/api/export/tally", "get")
        assert self._has(spec, "/api/po/{po_id}/export", "get")
