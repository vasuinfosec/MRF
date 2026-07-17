"""Iteration 22 — LLM file-upload attachment path validation.

Covers:
  * item-standardise + PDF attachment (small, reportlab-generated)
  * item-standardise regression (no attachments)
  * >10MB attachment rejection (413)
  * quotation-compare with 2 PDF attachments (no structured quotes)
  * quotation-compare with 1 structured quote + 1 attachment
  * quotation-compare with 0 quotes + 1 attachment (400)
  * quotation-compare with 9 attachments (400 — max 8)
  * reconcile with vendor invoice PDF attachment
  * xlsx / csv / txt / unsupported (image) attachment kinds
  * Workflow collection immutability
  * audit chars_in grows with attachment
  * input_summary in llm_suggestions never contains base64
  * Cache-hit regression on identical prompt

Run:
  pytest /app/backend/tests/test_llm_attachments_iter22.py -v \
    --junitxml=/app/test_reports/pytest/iter22_llm_attachments.xml
"""
import os
import io
import csv
import base64
import time
import pytest
import requests
from typing import Dict, List

from reportlab.pdfgen import canvas
from openpyxl import Workbook

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ROLES = {
    "admin": ("admin@vasu.dev", "admin", "Admin"),
    "director": ("director@vasu.dev", "director", "Director"),
    "gm": ("gm@vasu.dev", "gm", "GM"),
    "pm": ("pm@vasu.dev", "pm", "PM"),
    "purchase": ("purchase@vasu.dev", "purchase", "Purchase"),
    "site_engineer": ("siteeng@vasu.dev", "site_engineer", "SE"),
}


# ---------- fixtures --------------------------------------------------------
def _login(role: str) -> str:
    email, role_name, name = ROLES[role]
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": email, "role": role_name, "name": name},
                      timeout=15)
    assert r.status_code == 200, f"dev-login failed for {role}: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def tokens() -> Dict[str, str]:
    return {r: _login(r) for r in ROLES}


def hdr(tokens: Dict[str, str], role: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tokens[role]}",
            "Content-Type": "application/json"}


# ---------- attachment builders --------------------------------------------
def _pdf_b64(lines: List[str]) -> str:
    """Generate a tiny in-memory PDF with reportlab."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 20
    c.showPage()
    c.save()
    return base64.b64encode(buf.getvalue()).decode()


def _xlsx_b64(rows: List[List]) -> str:
    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for r in rows:
        ws.append(r)
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def _csv_b64(rows: List[List[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return base64.b64encode(buf.getvalue().encode()).decode()


def _txt_b64(content: str) -> str:
    return base64.b64encode(content.encode()).decode()


def _fake_large_pdf_b64(size_bytes: int) -> str:
    """Return base64 of `size_bytes` of random-ish bytes prefixed with %PDF-.
    Content doesn't need to parse — server should reject on size first."""
    payload = b"%PDF-1.4\n" + b"A" * (size_bytes - 9)
    return base64.b64encode(payload).decode()


# =========================================================================
# 1. Item Standardise — PDF attachment
# =========================================================================

class TestItemStandardisePdf:
    def test_with_small_pdf(self, tokens):
        att = {
            "file_name": "TEST_iter22_spec.pdf",
            "mime_type": "application/pdf",
            "file_base64": _pdf_b64([
                "TEST_iter22 CAT6 UTP cable specification",
                "Length: 305m box, 4-pair 23AWG solid copper",
                "Category 6 UTP, LSZH jacket, blue",
                "Make: D-Link  Model: NCB-C6UGRYR-305",
            ]),
        }
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "CAT6 UTP cable 305m box",
                                "make": "D-Link", "context": "iter22 attachment",
                                "attachments": [att]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip(f"LLM upstream unavailable: {r.text}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "cheap"
        assert d.get("kind") == "item_standardise"
        assert d.get("status") == "pending_review"
        # input_summary must have slim attachments only — NO base64
        sm = d.get("input_summary") or {}
        atts = sm.get("attachments") or []
        assert len(atts) == 1
        a0 = atts[0]
        assert a0.get("file_name") == "TEST_iter22_spec.pdf"
        assert a0.get("kind") == "pdf"
        assert isinstance(a0.get("chars"), int) and a0["chars"] > 0
        # CRITICAL: never contain base64 payload
        assert "file_base64" not in a0
        for v in a0.values():
            assert not (isinstance(v, str) and len(v) > 400), \
                f"input_summary should not carry big blobs, got {v[:80]}..."
        parsed = d.get("output_parsed") or {}
        assert "suggestions" in parsed

    def test_no_attachments_regression(self, tokens):
        """Phase 8 flow — description only — must still work."""
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 regression no-att " + str(time.time())},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "cheap"
        sm = d.get("input_summary") or {}
        atts = sm.get("attachments") or []
        assert atts == []

    def test_over_10mb_rejected_413(self, tokens):
        big = _fake_large_pdf_b64(11 * 1024 * 1024)  # ~11 MB raw
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 oversize check",
                                "attachments": [{
                                    "file_name": "TEST_iter22_big.pdf",
                                    "mime_type": "application/pdf",
                                    "file_base64": big}]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"


# =========================================================================
# 2. Quotation Compare — attachments
# =========================================================================

class TestQuotationCompareAttachments:
    def test_two_pdf_attachments_no_structured(self, tokens):
        pdf1 = _pdf_b64([
            "Vendor: TEST_iter22 Alpha Traders",
            "Quotation for CAT6 cable 305m box",
            "Rate: INR 8500 per box, GST 18%, Total INR 10030",
        ])
        pdf2 = _pdf_b64([
            "Vendor: TEST_iter22 Beta Cables",
            "Quotation for CAT6 UTP cable 305m",
            "Rate: INR 9000 per box, GST 18%, Total INR 10620",
        ])
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"context": "iter22 pdf-only compare",
                                "attachments": [
                                    {"file_name": "alpha.pdf",
                                     "mime_type": "application/pdf",
                                     "file_base64": pdf1},
                                    {"file_name": "beta.pdf",
                                     "mime_type": "application/pdf",
                                     "file_base64": pdf2}]},
                          headers=hdr(tokens, "purchase"), timeout=90)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "premium"
        sm = d.get("input_summary") or {}
        assert sm.get("attachment_count") == 2
        atts = sm.get("attachments") or []
        assert len(atts) == 2
        for a in atts:
            assert a.get("kind") == "pdf"
            assert a.get("chars", 0) > 0
            assert "file_base64" not in a

    def test_one_quote_plus_one_attachment_ok(self, tokens):
        pdf = _pdf_b64([
            "Vendor: TEST_iter22 Gamma Trading",
            "Item: HDMI cable 2m — Rate INR 250, GST 18%",
        ])
        quotes = [{"vendor_name": "TEST_iter22 Delta Suppliers", "currency": "INR",
                   "items": [{"description": "HDMI cable 2m", "qty": 10,
                              "unit": "nos", "rate": 275, "gst": 18}]}]
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"quotes": quotes,
                                "attachments": [{"file_name": "gamma.pdf",
                                                 "mime_type": "application/pdf",
                                                 "file_base64": pdf}]},
                          headers=hdr(tokens, "purchase"), timeout=90)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        sm = r.json().get("input_summary") or {}
        assert sm.get("attachment_count") == 1
        assert sm.get("quote_count") == 1

    def test_zero_quotes_one_attachment_400(self, tokens):
        pdf = _pdf_b64(["single attachment only"])
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"attachments": [{"file_name": "one.pdf",
                                                 "mime_type": "application/pdf",
                                                 "file_base64": pdf}]},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400, r.text

    def test_nine_attachments_rejected(self, tokens):
        pdfs = [{"file_name": f"q{i}.pdf",
                 "mime_type": "application/pdf",
                 "file_base64": _pdf_b64([f"vendor {i}"])} for i in range(9)]
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"attachments": pdfs},
                          headers=hdr(tokens, "purchase"), timeout=30)
        assert r.status_code == 400, r.text
        assert "8" in r.text or "max" in r.text.lower()


# =========================================================================
# 3. Reconcile — vendor invoice PDF attachment
# =========================================================================

def _find_po_with_grn(tokens) -> str:
    r = requests.get(f"{API}/grns", headers=hdr(tokens, "admin"), timeout=15)
    assert r.status_code == 200
    for g in r.json():
        if g.get("po_id"):
            return g["po_id"]
    pytest.skip("No PO with GRN available")


class TestReconcileAttachment:
    def test_reconcile_with_pdf(self, tokens):
        po_id = _find_po_with_grn(tokens)
        pdf = _pdf_b64([
            "Vendor Invoice INV/TEST_iter22/001",
            "PO Reference: iter22 test",
            "Line 1: item description qty 1 rate 100 amount 100",
            "GST 18% — Total 118",
        ])
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": po_id,
                                "attachments": [{"file_name": "inv.pdf",
                                                 "mime_type": "application/pdf",
                                                 "file_base64": pdf}]},
                          headers=hdr(tokens, "purchase"), timeout=120)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "premium"
        assert d.get("kind") == "reconcile"
        parsed = d.get("output_parsed") or {}
        assert isinstance(parsed, dict)
        # per_line is expected in the reconcile output structure
        assert "per_line" in parsed or "error" in parsed or "aggregate" in parsed
        # input_summary must record slim attachments (no base64)
        sm = d.get("input_summary") or {}
        atts = sm.get("attachments") or []
        assert len(atts) == 1
        assert atts[0].get("kind") == "pdf"
        assert atts[0].get("chars", 0) > 0
        assert "file_base64" not in atts[0]


# =========================================================================
# 4. Extraction — xlsx / csv / txt / unsupported
# =========================================================================

class TestAttachmentKinds:
    def test_xlsx_extracted(self, tokens):
        xlsx = _xlsx_b64([
            ["item", "qty", "rate"],
            ["TEST_iter22 xlsx probe row", 5, 123.45],
            ["another line", 2, 99.0],
        ])
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 xlsx kind test",
                                "attachments": [{
                                    "file_name": "TEST_iter22.xlsx",
                                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    "file_base64": xlsx}]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        atts = (r.json().get("input_summary") or {}).get("attachments") or []
        assert atts and atts[0]["kind"] == "xlsx"
        assert atts[0]["chars"] > 0

    def test_csv_extracted(self, tokens):
        csv_b64 = _csv_b64([["header1", "header2"],
                            ["TEST_iter22 csv row", "value"],
                            ["row2", "v2"]])
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 csv kind test",
                                "attachments": [{
                                    "file_name": "TEST_iter22.csv",
                                    "mime_type": "text/csv",
                                    "file_base64": csv_b64}]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        atts = (r.json().get("input_summary") or {}).get("attachments") or []
        assert atts and atts[0]["kind"] == "csv"
        assert atts[0]["chars"] > 0

    def test_txt_extracted(self, tokens):
        t = _txt_b64("TEST_iter22 plain text attachment content for kind detection.")
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 txt kind test",
                                "attachments": [{
                                    "file_name": "TEST_iter22.txt",
                                    "mime_type": "text/plain",
                                    "file_base64": t}]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        atts = (r.json().get("input_summary") or {}).get("attachments") or []
        assert atts and atts[0]["kind"] == "txt"
        assert atts[0]["chars"] > 0

    def test_image_unsupported(self, tokens):
        # bogus JPEG bytes
        raw = b"\xff\xd8\xff\xe0" + b"junk" * 40
        img_b64 = base64.b64encode(raw).decode()
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 image unsupported test",
                                "attachments": [{
                                    "file_name": "TEST_iter22.jpg",
                                    "mime_type": "image/jpeg",
                                    "file_base64": img_b64}]},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        atts = (r.json().get("input_summary") or {}).get("attachments") or []
        assert atts and atts[0]["kind"] == "unsupported"
        assert atts[0]["chars"] == 0


# =========================================================================
# 5. Workflow collections must NOT change
# =========================================================================

class TestWorkflowIsolationWithAttachments:
    def _counts(self, tokens) -> Dict[str, int]:
        out = {}
        for path, key in [("/mrf", "mrfs"), ("/pos", "pos"), ("/grns", "grns"),
                          ("/dc", "dcs"), ("/invoices", "invoices"),
                          ("/materials?status=all", "materials"),
                          ("/comparative-statement", "cs")]:
            try:
                r = requests.get(f"{API}{path}", headers=hdr(tokens, "admin"),
                                 timeout=15)
                if r.status_code == 200 and isinstance(r.json(), list):
                    out[key] = len(r.json())
            except Exception:
                pass
        return out

    def test_attachment_calls_do_not_mutate(self, tokens):
        before = self._counts(tokens)
        # 3 attachment-carrying LLM calls
        pdf = _pdf_b64(["iter22 workflow-isolation probe " + str(time.time())])
        r1 = requests.post(f"{API}/llm/item-standardise",
                           json={"description": "iso-att " + str(time.time()),
                                 "attachments": [{"file_name": "i.pdf",
                                                  "mime_type": "application/pdf",
                                                  "file_base64": pdf}]},
                           headers=hdr(tokens, "purchase"), timeout=60)
        r2 = requests.post(f"{API}/llm/quotation-compare",
                           json={"attachments": [
                               {"file_name": "a.pdf", "mime_type": "application/pdf",
                                "file_base64": _pdf_b64(["Vendor A rate 100"])},
                               {"file_name": "b.pdf", "mime_type": "application/pdf",
                                "file_base64": _pdf_b64(["Vendor B rate 110"])},
                           ]},
                           headers=hdr(tokens, "purchase"), timeout=90)
        po_id = _find_po_with_grn(tokens)
        r3 = requests.post(f"{API}/llm/reconcile",
                           json={"po_id": po_id,
                                 "attachments": [{"file_name": "inv.pdf",
                                                  "mime_type": "application/pdf",
                                                  "file_base64": pdf}]},
                           headers=hdr(tokens, "purchase"), timeout=120)
        for r in (r1, r2, r3):
            if r.status_code == 502:
                pytest.skip("LLM upstream unavailable")
        after = self._counts(tokens)
        for k in before:
            assert before[k] == after.get(k), \
                f"LLM attachment call mutated collection {k}: {before[k]} → {after.get(k)}"


# =========================================================================
# 6. Audit chars_in grows when attachment text is appended
# =========================================================================

class TestAuditCharsGrowsWithAttachment:
    def test_chars_in_grows(self, tokens):
        # baseline — same description, no attachment
        desc = "iter22 audit chars probe " + str(time.time())
        r1 = requests.post(f"{API}/llm/item-standardise",
                           json={"description": desc},
                           headers=hdr(tokens, "purchase"), timeout=60)
        if r1.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r1.status_code == 200
        # with a fat text attachment
        big_txt = _txt_b64("iter22 attachment context: " + ("lorem ipsum " * 500))
        r2 = requests.post(f"{API}/llm/item-standardise",
                           json={"description": desc,
                                 "attachments": [{"file_name": "big.txt",
                                                  "mime_type": "text/plain",
                                                  "file_base64": big_txt}]},
                           headers=hdr(tokens, "purchase"), timeout=60)
        if r2.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r2.status_code == 200
        # inspect audit rows
        alogs = requests.get(f"{API}/audit?entity=llm",
                             headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        rows = [x for x in rows if x.get("action") == "llm_call_item_standardise"]
        chars_ins = [(x.get("details") or {}).get("chars_in") for x in rows[:20]]
        chars_ins = [c for c in chars_ins if isinstance(c, int)]
        assert chars_ins, "no llm_call_item_standardise audit rows"
        # Max chars_in should be substantially greater than min (attachment appended)
        assert max(chars_ins) - min(chars_ins) > 500, \
            f"chars_in did not grow with attachment: samples={chars_ins[:5]}"


# =========================================================================
# 7. Cache regression — same prompt (no attachment) still hits
# =========================================================================

class TestCacheStillWorks:
    def test_identical_no_attachment_prompt_cached(self, tokens):
        payload = {"description": "iter22 cache regression static probe",
                   "context": "iter22-cache"}
        r1 = requests.post(f"{API}/llm/item-standardise", json=payload,
                           headers=hdr(tokens, "purchase"), timeout=60)
        if r1.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/llm/item-standardise", json=payload,
                           headers=hdr(tokens, "purchase"), timeout=15)
        assert r2.status_code == 200
        assert r1.json().get("output_raw") == r2.json().get("output_raw")


# =========================================================================
# 8. Suggestions list / decide still works (iter20 regression)
# =========================================================================

class TestSuggestionEndpointsRegression:
    def test_list_pending(self, tokens):
        r = requests.get(f"{API}/llm/suggestions?status=pending_review&limit=5",
                         headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_decide_accept(self, tokens):
        c = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "iter22 decide regression " + str(time.time())},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if c.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert c.status_code == 200
        sid = c.json()["suggestion_id"]
        r = requests.post(f"{API}/llm/suggestions/{sid}/decide",
                          json={"action": "accept", "reason": "iter22 ok"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "accepted"
