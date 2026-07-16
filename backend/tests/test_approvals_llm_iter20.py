"""Iteration 20 canonical regression suite.

Covers:
  A. Approval workflow: GRN, DC, Comparative Statement
  B. LLM Co-pilot (suggestion-only): item-standardise, quotation-compare,
     reconcile, list, decide, cache, audit logging, workflow-collection-safety.

Run:
  pytest /app/backend/tests/test_approvals_llm_iter20.py -v \
    --junitxml=/app/test_reports/pytest/iter20_approvals_llm.xml
"""
import os
import time
import base64
import pytest
import requests
from typing import Dict, Any, List

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                          "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ROLES = {
    "admin": ("admin@vasu.dev", "admin", "Admin"),
    "director": ("director@vasu.dev", "director", "Director"),
    "gm": ("gm@vasu.dev", "gm", "GM"),
    "pm": ("pm@vasu.dev", "pm", "PM"),
    "purchase": ("purchase@vasu.dev", "purchase", "Purchase"),
    "site_engineer": ("siteeng@vasu.dev", "site_engineer", "SE"),
    "store": ("store@vasu.dev", "store", "Store"),
}


def _login(role: str) -> str:
    email, role_name, name = ROLES[role]
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": email, "role": role_name, "name": name},
                      timeout=15)
    assert r.status_code == 200, f"dev-login failed for {role}: {r.status_code} {r.text}"
    return r.json()["session_token"]


def _h(role: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_login(role)}",
            "Content-Type": "application/json"}


# ---------- session-scoped headers so we don't relogin every test ----------
@pytest.fixture(scope="session")
def tokens() -> Dict[str, str]:
    return {r: _login(r) for r in ROLES}


def hdr(tokens: Dict[str, str], role: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tokens[role]}",
            "Content-Type": "application/json"}


# =========================================================================
# Helpers to create fresh workflow objects
# =========================================================================

@pytest.fixture(scope="module")
def project_for_dc(tokens):
    """Reuse first accessible project (admin has full access)."""
    r = requests.get(f"{API}/projects", headers=hdr(tokens, "admin"), timeout=15)
    assert r.status_code == 200
    projs = r.json()
    assert projs, "no projects seeded"
    return projs[0]


@pytest.fixture(scope="module")
def po_with_grn(tokens):
    """PO known to have a GRN (from iter18 smoke test)."""
    # Try po_29138a4399ed first — per iter19 report has grn_2bdb739a88ea.
    r = requests.get(f"{API}/po/po_29138a4399ed/grns",
                     headers=hdr(tokens, "admin"), timeout=15)
    if r.status_code == 200 and r.json():
        return "po_29138a4399ed"
    # Fallback: find any PO that has GRNs
    grns = requests.get(f"{API}/grns", headers=hdr(tokens, "admin"), timeout=15).json()
    for g in grns:
        if g.get("po_id"):
            return g["po_id"]
    pytest.skip("No PO with GRN available for reconcile tests")


def _create_dc(tokens, project) -> dict:
    body = {
        "project_id": project["project_id"],
        "customer_id": project.get("customer_id") or "",
        "dc_type": "outbound",
        "from_location": "Warehouse",
        "to_location": "Site",
        "dispatch_date": "2026-01-15",
        "items": [{"description": "TEST_ITER20 item", "unit": "nos",
                   "qty": 1.0, "rate": 100.0, "gst": 18.0}],
    }
    r = requests.post(f"{API}/dc", json=body, headers=hdr(tokens, "admin"),
                      timeout=20)
    assert r.status_code == 200, f"create dc failed: {r.status_code} {r.text}"
    return r.json()


def _create_cs(tokens, project) -> dict:
    xlsx_b64 = base64.b64encode(b"PK\x05\x06" + b"\x00" * 40).decode()
    # find an mrf under this project — else use first available
    mrfs = requests.get(f"{API}/mrf", headers=hdr(tokens, "purchase"),
                        timeout=15).json()
    mrf_id = ""
    for m in mrfs:
        if m.get("project_id") == project["project_id"]:
            mrf_id = m["mrf_id"]; break
    if not mrf_id and mrfs:
        mrf_id = mrfs[0]["mrf_id"]
    payload = {
        "mrf_id": mrf_id,
        "title": "TEST_ITER20 CS",
        "file_name": "test.xlsx",
        "file_base64": xlsx_b64,
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    r = requests.post(f"{API}/comparative-statement", json=payload,
                      headers=hdr(tokens, "purchase"), timeout=20)
    assert r.status_code == 200, f"create cs failed: {r.status_code} {r.text}"
    return r.json()


def _get_any_pending_grn(tokens) -> str:
    r = requests.get(f"{API}/grns", headers=hdr(tokens, "admin"), timeout=15)
    for g in r.json():
        if g.get("status") in (None, "pending_approval", "rejected"):
            return g["grn_id"]
    pytest.skip("No pending GRN available")


# =========================================================================
# A. Approval workflow — GRN
# =========================================================================

class TestGrnApproval:
    def test_get_grn_endpoint_admin(self, tokens):
        grn_id = _get_any_pending_grn(tokens)
        r = requests.get(f"{API}/grn/{grn_id}",
                         headers=hdr(tokens, "admin"), timeout=15)
        assert r.status_code == 200
        assert r.json()["grn_id"] == grn_id

    def test_get_grn_404(self, tokens):
        r = requests.get(f"{API}/grn/grn_does_not_exist",
                         headers=hdr(tokens, "admin"), timeout=15)
        assert r.status_code == 404

    def test_grn_approve_purchase_forbidden(self, tokens):
        grn_id = _get_any_pending_grn(tokens)
        r = requests.post(f"{API}/grn/{grn_id}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 403

    def test_grn_approve_pm_forbidden(self, tokens):
        grn_id = _get_any_pending_grn(tokens)
        r = requests.post(f"{API}/grn/{grn_id}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "pm"), timeout=15)
        assert r.status_code == 403

    def test_grn_approve_director_ok_and_audit(self, tokens):
        grn_id = _get_any_pending_grn(tokens)
        # snapshot old status
        old = requests.get(f"{API}/grn/{grn_id}",
                           headers=hdr(tokens, "admin"), timeout=15).json()
        old_status = old.get("status") or "pending_approval"
        r = requests.post(f"{API}/grn/{grn_id}/approve",
                          json={"action": "approve", "comment": "iter20-approve"},
                          headers=hdr(tokens, "director"), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved"
        assert body.get("approval_history"), "approval_history should be populated"
        last = body["approval_history"][-1]
        assert last["action"] == "approve"
        assert last["user_role"] == "director"
        # Audit
        alogs = requests.get(f"{API}/audit?entity=grn&entity_id={grn_id}",
                             headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        approve_rows = [x for x in rows if x.get("action") == "grn_approve"]
        assert approve_rows, "grn_approve audit row missing"
        det = approve_rows[0].get("details") or {}
        assert det.get("old_value", {}).get("status") == old_status
        assert det.get("new_value", {}).get("status") == "approved"

    def test_grn_reapprove_already_approved_400(self, tokens):
        # Take the freshly approved GRN
        grn_id = None
        for g in requests.get(f"{API}/grns",
                              headers=hdr(tokens, "admin"),
                              timeout=15).json():
            if g.get("status") == "approved":
                grn_id = g["grn_id"]; break
        assert grn_id
        r = requests.post(f"{API}/grn/{grn_id}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "director"), timeout=15)
        assert r.status_code == 400


# =========================================================================
# A. Approval workflow — DC
# =========================================================================

class TestDcApproval:
    def test_dc_approve_purchase_403(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        r = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 403

    def test_dc_approve_pm_403(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        r = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "pm"), timeout=15)
        assert r.status_code == 403

    def test_dc_approve_director_ok_audit(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        old_status = dc.get("status", "pending_approval")
        r = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                          json={"action": "approve", "comment": "iter20 director ok"},
                          headers=hdr(tokens, "director"), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved"
        assert body.get("approval_history"), "approval_history missing"
        # Audit
        alogs = requests.get(
            f"{API}/audit?entity=dc&entity_id={dc['dc_id']}",
            headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        approve_rows = [x for x in rows if x.get("action") == "dc_approve"]
        assert approve_rows
        det = approve_rows[0].get("details") or {}
        assert det.get("old_value", {}).get("status") == old_status
        assert det.get("new_value", {}).get("status") == "approved"

    def test_dc_already_approved_cannot_reapprove(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        r1 = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                           json={"action": "approve"},
                           headers=hdr(tokens, "admin"), timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                           json={"action": "approve"},
                           headers=hdr(tokens, "admin"), timeout=15)
        assert r2.status_code == 400

    def test_dc_reject_then_reapprove(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        # Reject
        r1 = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                           json={"action": "reject", "comment": "bad qty"},
                           headers=hdr(tokens, "admin"), timeout=15)
        assert r1.status_code == 200
        assert r1.json()["status"] == "rejected"
        # Re-approve
        r2 = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                           json={"action": "approve"},
                           headers=hdr(tokens, "director"), timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "approved"

    def test_dc_reject_missing_comment_still_allowed(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        r = requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                          json={"action": "reject"},
                          headers=hdr(tokens, "admin"), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    def test_dc_locked_after_approval_for_purchase(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        # approve
        requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                      json={"action": "approve"},
                      headers=hdr(tokens, "admin"), timeout=15)
        # purchase tries to PUT
        r = requests.put(f"{API}/dc/{dc['dc_id']}",
                         json={"remarks": "should be locked"},
                         headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400, r.text
        assert "lock" in r.text.lower()

    def test_dc_admin_can_edit_after_approval(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        requests.post(f"{API}/dc/{dc['dc_id']}/approve",
                      json={"action": "approve"},
                      headers=hdr(tokens, "admin"), timeout=15)
        r = requests.put(f"{API}/dc/{dc['dc_id']}",
                         json={"remarks": "admin override"},
                         headers=hdr(tokens, "admin"), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["remarks"] == "admin override"


# =========================================================================
# A. Approval workflow — Comparative Statement
# =========================================================================

class TestCsApproval:
    def test_cs_approve_purchase_403(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        r = requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 403

    def test_cs_approve_admin_403(self, tokens, project_for_dc):
        # spec: admin only uploads/edits — CS approver is PM/GM/Director
        cs = _create_cs(tokens, project_for_dc)
        r = requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "admin"), timeout=15)
        assert r.status_code == 403

    def test_cs_approve_director_ok(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        r = requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                          json={"action": "approve", "comment": "ok"},
                          headers=hdr(tokens, "director"), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # audit
        alogs = requests.get(
            f"{API}/audit?entity=comparative_statement&entity_id={cs['cs_id']}",
            headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        assert any(x.get("action") == "cs_approve" for x in rows)

    def test_cs_approve_gm_ok(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        r = requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "gm"), timeout=15)
        assert r.status_code == 200

    def test_cs_approve_pm_ok(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        r = requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                          json={"action": "approve"},
                          headers=hdr(tokens, "pm"), timeout=15)
        assert r.status_code == 200

    def test_cs_locked_after_approval_for_purchase(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        requests.post(f"{API}/comparative-statement/{cs['cs_id']}/approve",
                      json={"action": "approve"},
                      headers=hdr(tokens, "director"), timeout=15)
        # PUT by purchase after approval — should be locked (400)
        r = requests.put(f"{API}/comparative-statement/{cs['cs_id']}",
                         json={"title": "should not"},
                         headers=hdr(tokens, "purchase"), timeout=15)
        # Iteration 20 spec: PUT on approved CS by purchase → 400 'locked'
        assert r.status_code == 400, r.text


# =========================================================================
# B. LLM Co-pilot
# =========================================================================

class TestLlmItemStandardise:
    def test_site_engineer_forbidden(self, tokens):
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "CCTV camera 2MP"},
                          headers=hdr(tokens, "site_engineer"), timeout=15)
        assert r.status_code == 403

    def test_missing_description_400(self, tokens):
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": ""},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400

    def test_returns_suggestion_and_no_hallucinations(self, tokens):
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "CCTV 2MP dome camera",
                                "context": "MRF Fire Safety"},
                          headers=hdr(tokens, "purchase"), timeout=45)
        if r.status_code == 502:
            pytest.skip(f"LLM upstream unavailable: {r.text}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("suggestion_id")
        assert d.get("status") == "pending_review"
        assert d.get("tier") == "cheap"
        assert d.get("model") == "claude-haiku-4-5-20251001"
        # No hallucinated material_uids
        approved = requests.get(f"{API}/materials?status=approved",
                                headers=hdr(tokens, "admin"), timeout=15).json()
        known = {m["material_uid"] for m in approved}
        for s in (d.get("output_parsed") or {}).get("suggestions", []):
            muid = s.get("material_uid")
            if muid:
                assert muid in known, f"Hallucinated UID {muid}"

    def test_audit_log_written(self, tokens):
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "audit-test-item-iter20"},
                          headers=hdr(tokens, "purchase"), timeout=45)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200
        alogs = requests.get(f"{API}/audit?entity=llm",
                             headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        matches = [x for x in rows if x.get("action") == "llm_call_item_standardise"]
        assert matches, "no llm_call_item_standardise audit row"
        det = matches[0].get("details") or {}
        assert det.get("tier") == "cheap"
        assert det.get("model") == "claude-haiku-4-5-20251001"
        assert isinstance(det.get("chars_in"), int)
        assert isinstance(det.get("chars_out"), int)


class TestLlmQuotationCompare:
    def test_one_quote_400(self, tokens):
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"quotes": [{"vendor_name": "A", "items": []}]},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400

    def test_seven_quotes_400(self, tokens):
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"quotes": [{"vendor_name": f"V{i}", "items": []}
                                            for i in range(7)]},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400

    def test_two_quotes_ok(self, tokens):
        quotes = [
            {"vendor_name": "V1", "currency": "INR",
             "items": [{"description": "Item X", "qty": 1, "unit": "nos",
                        "rate": 100, "gst": 18}]},
            {"vendor_name": "V2", "currency": "INR",
             "items": [{"description": "Item X", "qty": 1, "unit": "nos",
                        "rate": 110, "gst": 18}]},
        ]
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"quotes": quotes, "context": "iter20"},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "premium"
        assert d.get("model") == "claude-sonnet-4-5-20250929"
        assert d.get("status") == "pending_review"


class TestLlmReconcile:
    def test_site_engineer_forbidden(self, tokens):
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": "po_x"},
                          headers=hdr(tokens, "site_engineer"), timeout=15)
        assert r.status_code == 403

    def test_invalid_po_404(self, tokens):
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": "po_definitely_not_found"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 404

    def test_valid_po_ok(self, tokens, po_with_grn):
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": po_with_grn},
                          headers=hdr(tokens, "purchase"), timeout=90)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "premium"
        assert d.get("kind") == "reconcile"
        parsed = d.get("output_parsed") or {}
        # Should have a 3-way structure — 'per_line' or 'aggregate' expected
        assert isinstance(parsed, dict)


class TestLlmSuggestionsList:
    def test_site_engineer_forbidden(self, tokens):
        r = requests.get(f"{API}/llm/suggestions?status=pending_review",
                         headers=hdr(tokens, "site_engineer"), timeout=15)
        assert r.status_code == 403

    def test_purchase_can_list_pending(self, tokens):
        r = requests.get(f"{API}/llm/suggestions?status=pending_review&limit=25",
                         headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for x in rows:
            assert x.get("status") == "pending_review"


class TestLlmDecide:
    @pytest.fixture(scope="class")
    def pending_suggestion(self, tokens):
        # Try creating a new one; use item-standardise as cheapest
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "decide-test unique iter20-XYZ-" + str(time.time())},
                          headers=hdr(tokens, "purchase"), timeout=45)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200
        return r.json()

    def test_accept_updates_status_and_audits(self, tokens, pending_suggestion):
        sid = pending_suggestion["suggestion_id"]
        r = requests.post(f"{API}/llm/suggestions/{sid}/decide",
                          json={"action": "accept", "reason": "looks good"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "accepted"
        assert d.get("decided_by")
        # Audit row
        alogs = requests.get(f"{API}/audit?entity=llm_suggestion&entity_id={sid}",
                             headers=hdr(tokens, "admin"), timeout=15).json()
        rows = alogs if isinstance(alogs, list) else alogs.get("rows", [])
        accept_rows = [x for x in rows if x.get("action") == "llm_accept"]
        assert accept_rows
        det = accept_rows[0].get("details") or {}
        assert det.get("old_value", {}).get("status") == "pending_review"
        assert det.get("new_value", {}).get("status") == "accepted"

    def test_already_decided_400(self, tokens, pending_suggestion):
        sid = pending_suggestion["suggestion_id"]
        r = requests.post(f"{API}/llm/suggestions/{sid}/decide",
                          json={"action": "reject", "reason": "second try"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400

    def test_reject_new_suggestion(self, tokens):
        c = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "reject-test iter20-" + str(time.time())},
                          headers=hdr(tokens, "purchase"), timeout=45)
        if c.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        sid = c.json()["suggestion_id"]
        r = requests.post(f"{API}/llm/suggestions/{sid}/decide",
                          json={"action": "reject", "reason": "not relevant"},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


class TestLlmCache:
    def test_identical_prompt_returns_same_output(self, tokens):
        payload = {"description": "cache-test iter20 static",
                   "context": "cache-check"}
        r1 = requests.post(f"{API}/llm/item-standardise", json=payload,
                           headers=hdr(tokens, "purchase"), timeout=60)
        if r1.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/llm/item-standardise", json=payload,
                           headers=hdr(tokens, "purchase"), timeout=15)
        assert r2.status_code == 200
        # Cache should give identical output_raw
        assert r1.json().get("output_raw") == r2.json().get("output_raw")


class TestLlmWorkflowIsolation:
    """LLM MUST NOT mutate workflow collections."""

    def _counts(self, tokens) -> Dict[str, int]:
        c = {}
        for path, key in [("/mrf", "mrfs"), ("/pos", "pos"), ("/grns", "grns"),
                          ("/dc", "dcs"), ("/invoices", "invoices"),
                          ("/materials?status=all", "materials"),
                          ("/variants", "variants"),
                          ("/customers", "customers"),
                          ("/vendors", "vendors"),
                          ("/comparative-statement", "cs")]:
            try:
                r = requests.get(f"{API}{path}", headers=hdr(tokens, "admin"),
                                 timeout=15)
                if r.status_code == 200 and isinstance(r.json(), list):
                    c[key] = len(r.json())
            except Exception:
                pass
        return c

    def test_llm_calls_do_not_mutate_workflow(self, tokens, po_with_grn):
        before = self._counts(tokens)
        # item-standardise
        r1 = requests.post(f"{API}/llm/item-standardise",
                           json={"description": "isolation-test iter20-" + str(time.time())},
                           headers=hdr(tokens, "purchase"), timeout=45)
        # quotation-compare
        r2 = requests.post(f"{API}/llm/quotation-compare",
                           json={"quotes": [
                               {"vendor_name": "A", "items": [{"description": "x", "qty": 1, "unit": "nos", "rate": 10}]},
                               {"vendor_name": "B", "items": [{"description": "x", "qty": 1, "unit": "nos", "rate": 12}]}]},
                           headers=hdr(tokens, "purchase"), timeout=60)
        # reconcile
        r3 = requests.post(f"{API}/llm/reconcile",
                           json={"po_id": po_with_grn},
                           headers=hdr(tokens, "purchase"), timeout=90)
        # If any is 502, skip
        for r in (r1, r2, r3):
            if r.status_code == 502:
                pytest.skip("LLM upstream unavailable")
        after = self._counts(tokens)
        # Verify no counts changed across workflow collections
        for k in before:
            assert before[k] == after.get(k), \
                f"LLM mutated {k}: before={before[k]} after={after.get(k)}"


# =========================================================================
# Regression — iter19 export dispatchers still work
# =========================================================================

class TestRegressionIter19:
    def test_grn_export_pdf(self, tokens):
        grn_id = None
        for g in requests.get(f"{API}/grns", headers=hdr(tokens, "admin"),
                              timeout=15).json():
            grn_id = g["grn_id"]; break
        assert grn_id
        r = requests.get(f"{API}/grn/{grn_id}/export?format=pdf&force=1",
                         headers=hdr(tokens, "admin"), timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_dc_export_pdf(self, tokens, project_for_dc):
        dc = _create_dc(tokens, project_for_dc)
        r = requests.get(f"{API}/dc/{dc['dc_id']}/export?format=pdf&force=1",
                         headers=hdr(tokens, "admin"), timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_cs_download(self, tokens, project_for_dc):
        cs = _create_cs(tokens, project_for_dc)
        r = requests.get(f"{API}/comparative-statement/{cs['cs_id']}/download",
                         headers=hdr(tokens, "purchase"), timeout=20)
        assert r.status_code == 200
