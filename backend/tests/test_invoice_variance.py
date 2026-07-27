"""
Backend tests for Iteration 3:
  * Vendor Invoice CRUD (POST/GET, list, per-PO list, PDF)
  * Auto-numbering INV/YYYY/####
  * Role checks (site_engineer denied 403; purchase/billing/admin allowed)
  * GRN vs PO Variance report shape + sort + filters
"""
import os
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
             or os.environ.get("EXPO_BACKEND_URL")
             or "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")


def _login(role, email, name):
    r = requests.post(f"{BASE_URL}/api/auth/dev-login",
                      json={"email": email, "role": role, "name": name}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def tokens():
    admin_tok = _login("admin", "admin@vasu.dev", "Director")
    r = requests.post(f"{BASE_URL}/api/seed", headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200
    return {
        "site": _login("site_engineer", "site@vasu.dev", "Ravi"),
        "pm": _login("project_manager", "pm@vasu.dev", "Priya"),
        "purchase": _login("purchase", "purchase@vasu.dev", "Kumar"),
        "billing": _login("billing", "billing@vasu.dev", "Anita"),
        "admin": admin_tok,
    }


@pytest.fixture(scope="module")
def po_context(tokens):
    """Create a fresh MRF → approve → send-to-purchase → PO for invoice/variance tests."""
    projects = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site"])).json()
    vendors = requests.get(f"{BASE_URL}/api/vendors", headers=_h(tokens["purchase"])).json()
    proj = projects[0]
    body = {
        "project_id": proj["project_id"], "site": proj["site"],
        "required_by": "2026-05-01", "requesting_person": "TEST_INV_Ravi",
        "system_category": "Fire Alarm",
        "items": [
            {"description": "TEST_INV_ItemA", "unit": "Nos", "qty_requested": 10, "billable": True},
            {"description": "TEST_INV_ItemB", "unit": "Nos", "qty_requested": 4, "billable": True},
        ],
    }
    r = requests.post(f"{BASE_URL}/api/mrf", headers=_h(tokens["site"]), json=body)
    assert r.status_code == 200, r.text
    mrf = r.json()
    mrf_id = mrf["mrf_id"]
    requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/submit", headers=_h(tokens["site"])).raise_for_status()

    item_actions = [{"item_line_id": it["item_line_id"], "action": "approve",
                     "qty_approved": it["qty_requested"]} for it in mrf["items"]]
    requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/approve", headers=_h(tokens["pm"]),
                  json={"action": "approve", "comment": "OK", "item_actions": item_actions}).raise_for_status()
    requests.post(f"{BASE_URL}/api/mrf/{mrf_id}/send-to-purchase",
                  headers=_h(tokens["pm"])).raise_for_status()

    mrf = requests.get(f"{BASE_URL}/api/mrf/{mrf_id}", headers=_h(tokens["purchase"])).json()
    approved = [it for it in mrf["items"] if it["status"] == "approved"]

    po_body = {
        "vendor_id": vendors[0]["vendor_id"],
        "project_id": proj["project_id"],
        "delivery_site": "TEST INV site",
        "items": [{
            "mrf_id": mrf_id, "item_line_id": approved[0]["item_line_id"],
            "description": approved[0]["description"], "unit": "Nos",
            "qty": 10, "rate": 100, "gst": 18, "discount": 0
        }, {
            "mrf_id": mrf_id, "item_line_id": approved[1]["item_line_id"],
            "description": approved[1]["description"], "unit": "Nos",
            "qty": 4, "rate": 250, "gst": 18, "discount": 0
        }],
        "freight": 50, "other_charges": 0,
    }
    r = requests.post(f"{BASE_URL}/api/po", headers=_h(tokens["purchase"]), json=po_body)
    assert r.status_code == 200, r.text
    po = r.json()
    # Do a partial receipt so variance is non-zero
    body = {"items": [
        {"mrf_id": mrf_id, "item_line_id": approved[0]["item_line_id"], "qty": 4},
        {"mrf_id": mrf_id, "item_line_id": approved[1]["item_line_id"], "qty": 4},
    ], "remarks": "TEST_INV_receipt"}
    requests.post(f"{BASE_URL}/api/po/{po['po_id']}/received",
                  headers=_h(tokens["purchase"]), json=body).raise_for_status()
    return {"mrf_id": mrf_id, "po_id": po["po_id"], "po_number": po["po_number"],
            "items": approved, "project_id": proj["project_id"],
            "vendor_id": vendors[0]["vendor_id"]}


# ---------- Invoice creation & numbering ----------
class TestInvoiceCreation:
    def test_site_engineer_forbidden(self, tokens, po_context):
        body = {"po_id": po_context["po_id"], "items": [
            {"mrf_id": po_context["mrf_id"], "item_line_id": po_context["items"][0]["item_line_id"],
             "description": "x", "unit": "Nos", "qty": 1, "rate": 1, "gst": 18}]}
        r = requests.post(f"{BASE_URL}/api/invoice", headers=_h(tokens["site"]), json=body)
        assert r.status_code == 403, r.text

    def test_purchase_creates_invoice(self, tokens, po_context):
        items = po_context["items"]
        body = {
            "po_id": po_context["po_id"],
            "vendor_invoice_number": "VINV-TEST-001",
            "invoice_date": "2026-01-15",
            "items": [
                {"mrf_id": po_context["mrf_id"], "item_line_id": items[0]["item_line_id"],
                 "description": items[0]["description"], "unit": "Nos",
                 "qty": 4, "rate": 100, "gst": 18, "discount": 0},
                {"mrf_id": po_context["mrf_id"], "item_line_id": items[1]["item_line_id"],
                 "description": items[1]["description"], "unit": "Nos",
                 "qty": 4, "rate": 250, "gst": 18, "discount": 0},
            ],
            "freight": 25, "other_charges": 0, "remarks": "TEST partial invoice"
        }
        r = requests.post(f"{BASE_URL}/api/invoice", headers=_h(tokens["purchase"]), json=body)
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["invoice_number"].startswith("INV/2026/"), inv["invoice_number"]
        assert inv["po_id"] == po_context["po_id"]
        assert inv["po_number"] == po_context["po_number"]
        assert inv["vendor_id"] == po_context["vendor_id"]
        assert inv["project_id"] == po_context["project_id"]
        assert inv["created_by_name"]  # non-empty
        assert isinstance(inv["mrf_refs"], list)
        assert len(inv["items"]) == 2
        # Verify totals: (4*100 + 4*250) = 1400 subtotal; gst 18%=252; +25 freight → 1677
        assert abs(inv["subtotal"] - 1400.0) < 0.01
        assert abs(inv["gst_total"] - 252.0) < 0.01
        assert abs(inv["total"] - 1677.0) < 0.01
        po_context["invoice_id_1"] = inv["invoice_id"]
        po_context["invoice_number_1"] = inv["invoice_number"]

    def test_billing_can_create(self, tokens, po_context):
        items = po_context["items"]
        body = {"po_id": po_context["po_id"], "items": [
            {"mrf_id": po_context["mrf_id"], "item_line_id": items[0]["item_line_id"],
             "description": items[0]["description"], "unit": "Nos",
             "qty": 1, "rate": 100, "gst": 18, "discount": 0}]}
        r = requests.post(f"{BASE_URL}/api/invoice", headers=_h(tokens["billing"]), json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["invoice_number"].startswith("INV/")
        po_context["invoice_id_2"] = d["invoice_id"]

    def test_invoice_number_increments(self, tokens, po_context):
        n1 = po_context["invoice_number_1"]  # e.g. INV/2026/0001
        # fetch all invoices for PO, verify at least two and both share prefix
        r = requests.get(f"{BASE_URL}/api/po/{po_context['po_id']}/invoices",
                         headers=_h(tokens["admin"]))
        assert r.status_code == 200
        rows = r.json()
        nums = [row["invoice_number"] for row in rows]
        assert n1 in nums
        # all should be INV/YYYY/####
        for n in nums:
            parts = n.split("/")
            assert parts[0] == "INV" and len(parts) == 3 and parts[2].isdigit()

    def test_bad_po_returns_404(self, tokens):
        body = {"po_id": "nonexistent", "items": [
            {"description": "x", "unit": "Nos", "qty": 1, "rate": 1, "gst": 18}]}
        r = requests.post(f"{BASE_URL}/api/invoice", headers=_h(tokens["purchase"]), json=body)
        assert r.status_code == 404


# ---------- Invoice retrieval ----------
class TestInvoiceRetrieval:
    def test_list_all_invoices(self, tokens, po_context):
        r = requests.get(f"{BASE_URL}/api/invoice", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 2
        assert any(row["invoice_id"] == po_context["invoice_id_1"] for row in rows)

    def test_list_invoice_filter_by_po(self, tokens, po_context):
        r = requests.get(f"{BASE_URL}/api/invoice?po_id={po_context['po_id']}",
                         headers=_h(tokens["admin"]))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 2
        for row in rows:
            assert row["po_id"] == po_context["po_id"]

    def test_get_single_invoice(self, tokens, po_context):
        iid = po_context["invoice_id_1"]
        r = requests.get(f"{BASE_URL}/api/invoice/{iid}", headers=_h(tokens["purchase"]))
        assert r.status_code == 200
        d = r.json()
        assert d["invoice_id"] == iid
        assert d["invoice_number"] == po_context["invoice_number_1"]

    def test_get_single_invoice_not_found(self, tokens):
        r = requests.get(f"{BASE_URL}/api/invoice/does-not-exist",
                         headers=_h(tokens["purchase"]))
        assert r.status_code == 404

    def test_list_po_invoices(self, tokens, po_context):
        r = requests.get(f"{BASE_URL}/api/po/{po_context['po_id']}/invoices",
                         headers=_h(tokens["purchase"]))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 2
        for row in rows:
            assert row["po_id"] == po_context["po_id"]

    def test_list_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/invoice")
        assert r.status_code == 401


# ---------- Invoice PDF ----------
class TestInvoicePDF:
    def test_pdf_download(self, tokens, po_context):
        iid = po_context["invoice_id_1"]
        r = requests.get(f"{BASE_URL}/api/invoice/{iid}/pdf?token={tokens['purchase']}")
        assert r.status_code == 200, r.text[:200]
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_pdf_missing_404(self, tokens):
        r = requests.get(f"{BASE_URL}/api/invoice/nope/pdf?token={tokens['admin']}")
        assert r.status_code == 404

    def test_pdf_without_auth(self):
        r = requests.get(f"{BASE_URL}/api/invoice/anything/pdf")
        assert r.status_code == 401


# ---------- Variance Report ----------
class TestVarianceReport:
    def test_variance_shape_and_sort(self, tokens, po_context):
        r = requests.get(f"{BASE_URL}/api/reports/grn-variance", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 1
        keys = {"po_id", "po_number", "value_ordered", "value_received",
                "variance", "invoice_total", "invoice_variance",
                "short_lines", "line_count", "status"}
        for row in rows:
            assert keys.issubset(row.keys()), f"missing keys in {row}"
        # Sorted by |variance| desc
        abs_vars = [abs(r_["variance"]) for r_ in rows]
        assert abs_vars == sorted(abs_vars, reverse=True), f"not sorted: {abs_vars[:5]}"

    def test_our_po_in_variance(self, tokens, po_context):
        r = requests.get(f"{BASE_URL}/api/reports/grn-variance", headers=_h(tokens["admin"]))
        rows = r.json()
        our = [row for row in rows if row["po_id"] == po_context["po_id"]]
        assert len(our) == 1
        v = our[0]
        # Ordered = (10*100 + 4*250)*1.18 + 50 freight = (1000+1000)*1.18 + 50 = 2360 + 50 = 2410
        assert abs(v["value_ordered"] - 2410.0) < 0.5
        # Received = 4/10 line1 + 4/4 line2, no freight (not fully received)
        # line1 = 1000*1.18 * 4/10 = 472; line2 = 1000*1.18 * 4/4 = 1180 → 1652
        assert abs(v["value_received"] - 1652.0) < 0.5
        # variance = ordered - received = 758
        assert abs(v["variance"] - 758.0) < 0.5
        # invoice_total we know from earlier tests: 1677 (first) + 118 (billing) = 1795
        assert abs(v["invoice_total"] - 1795.0) < 0.5
        assert v["short_lines"] == 1  # line1 short
        assert v["line_count"] == 2
        assert v["status"] == "partially_received"

    def test_variance_filter_by_project(self, tokens, po_context):
        r = requests.get(
            f"{BASE_URL}/api/reports/grn-variance?project_id={po_context['project_id']}",
            headers=_h(tokens["admin"])
        )
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert row["project_id"] == po_context["project_id"]

    def test_variance_filter_by_vendor(self, tokens, po_context):
        r = requests.get(
            f"{BASE_URL}/api/reports/grn-variance?vendor_id={po_context['vendor_id']}",
            headers=_h(tokens["admin"])
        )
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert row["vendor_id"] == po_context["vendor_id"]

    def test_variance_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/reports/grn-variance")
        assert r.status_code == 401
