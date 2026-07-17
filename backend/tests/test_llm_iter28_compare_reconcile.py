"""Iter-28 — Sonnet 4.5 removed from Compare & Reconcile; Deterministic engine
added to both. GPT-4o-mini is the only LLM tier here. Negotiate still supports
Sonnet 4.5 for Director only.

Run:
  pytest /app/backend/tests/test_llm_iter28_compare_reconcile.py -v \
    --junitxml=/app/test_reports/pytest/iter28_compare_reconcile.xml
"""
import os
import pytest
import requests
from typing import Dict

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ROLES = {
    "director": ("director@vasu.dev", "director", "Director"),
    "purchase": ("purchase@vasu.dev", "purchase", "Purchase"),
    "admin":    ("admin@vasu.dev",    "admin",    "Admin"),
    "pm":       ("pm@vasu.dev",       "pm",       "PM"),
}


def _login(role: str) -> str:
    email, r, name = ROLES[role]
    resp = requests.post(f"{API}/auth/dev-login",
                         json={"email": email, "role": r, "name": name},
                         timeout=15)
    assert resp.status_code == 200, resp.text
    return resp.json()["session_token"]


@pytest.fixture(scope="session")
def tokens() -> Dict[str, str]:
    return {r: _login(r) for r in ROLES}


def hdr(tokens, role):
    return {"Authorization": f"Bearer {tokens[role]}",
            "Content-Type": "application/json"}


# ------------------------------------------------------------------
# structured quotes fixture — L1 = 48000, L2 = 50000
# ------------------------------------------------------------------
def _quotes_two():
    return [
        {"vendor_name": "TEST_iter28 Alpha", "currency": "INR",
         "items": [{"description": "cable", "qty": 10, "rate": 5000, "gst": 0}]},
        {"vendor_name": "TEST_iter28 Beta", "currency": "INR",
         "items": [{"description": "cable", "qty": 10, "rate": 4800, "gst": 0}]},
    ]


# ====================================================================
# 1. Compare — deterministic
# ====================================================================

class TestCompareDeterministic:
    def test_deterministic_two_quotes(self, tokens):
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"tier": "deterministic",
                                "quotes": _quotes_two(),
                                "context": "iter28 det compare"},
                          headers=hdr(tokens, "purchase"), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "deterministic"
        assert d["model"] == "deterministic"
        assert (d.get("cost") or {}).get("cost_inr") == 0.0
        parsed = d["output_parsed"]
        assert parsed["_engine"] == "deterministic"
        ranking = parsed["ranking"]
        assert len(ranking) == 2
        # Beta is L1 (4800 * 10 = 48000)
        assert ranking[0]["vendor_name"] == "TEST_iter28 Beta"
        assert ranking[0]["rank"] == 1
        assert ranking[1]["rank"] == 2
        assert ranking[0]["total_with_tax"] <= ranking[1]["total_with_tax"]
        rec = parsed["recommendation"].lower()
        assert "%" in parsed["recommendation"] or "cheaper" in rec

    def test_deterministic_needs_two_vendors(self, tokens):
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"tier": "deterministic",
                                "quotes": [_quotes_two()[0]]},
                          headers=hdr(tokens, "purchase"), timeout=15)
        assert r.status_code == 400, r.text
        assert "2" in r.text or "at least" in r.text.lower()


# ====================================================================
# 2. Compare — cheap (gpt-4o-mini)
# ====================================================================

class TestCompareCheap:
    def test_cheap_two_quotes(self, tokens):
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"tier": "cheap",
                                "quotes": _quotes_two()},
                          headers=hdr(tokens, "purchase"), timeout=90)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "cheap"
        assert d["model"] == "gpt-4o-mini"

    def test_premium_silently_downshifts(self, tokens):
        """iter-28: premium request → cheap gpt-4o-mini (Sonnet retired here)."""
        # Test with Director too — must still downshift, not use Sonnet
        r = requests.post(f"{API}/llm/quotation-compare",
                          json={"tier": "premium",
                                "quotes": _quotes_two()},
                          headers=hdr(tokens, "director"), timeout=90)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "cheap", f"premium not silently downshifted, got tier={d.get('tier')}"
        assert d["model"] == "gpt-4o-mini"
        assert "sonnet" not in (d.get("model") or "").lower()


# ====================================================================
# 3. Reconcile — deterministic + cheap + premium-downshift
# ====================================================================

def _find_po_id(tokens) -> str:
    r = requests.get(f"{API}/grns", headers=hdr(tokens, "admin"), timeout=15)
    assert r.status_code == 200
    for g in r.json():
        if g.get("po_id"):
            return g["po_id"]
    # fallback — any PO
    r = requests.get(f"{API}/po", headers=hdr(tokens, "admin"), timeout=15)
    assert r.status_code == 200 and r.json(), "no PO available"
    return r.json()[0]["po_id"]


class TestReconcile:
    def test_deterministic(self, tokens):
        po_id = _find_po_id(tokens)
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": po_id, "tier": "deterministic"},
                          headers=hdr(tokens, "purchase"), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "deterministic"
        assert d["model"] == "deterministic"
        parsed = d["output_parsed"]
        assert parsed["_engine"] == "deterministic"
        assert isinstance(parsed["per_line"], list)
        if parsed["per_line"]:
            row0 = parsed["per_line"][0]
            for k in ("line", "po_qty", "invoice_qty", "status"):
                assert k in row0
        agg = parsed["aggregate"]
        for k in ("po_total", "grn_total_est", "invoice_total", "delta"):
            assert k in agg

    def test_cheap_default(self, tokens):
        po_id = _find_po_id(tokens)
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": po_id, "tier": "cheap"},
                          headers=hdr(tokens, "purchase"), timeout=120)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "cheap"
        assert d["model"] == "gpt-4o-mini"

    def test_premium_silently_downshifts(self, tokens):
        po_id = _find_po_id(tokens)
        r = requests.post(f"{API}/llm/reconcile",
                          json={"po_id": po_id, "tier": "premium"},
                          headers=hdr(tokens, "director"), timeout=120)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "cheap", f"Reconcile premium leaked Sonnet: {d}"
        assert d["model"] == "gpt-4o-mini"


# ====================================================================
# 4. Negotiate (purchase-analysis) — Sonnet 4.5 still available for Director
# ====================================================================

class TestNegotiateSonnetStillAllowed:
    def test_director_premium_uses_sonnet(self, tokens):
        payload = {
            "description": "TEST_iter28 CAT6 UTP cable 305m box",
            "make": "D-Link",
            "unit": "box",
            "qty": 10,
            "tier": "premium",
            "current_quote": {
                "vendor_name": "TEST_iter28 Vendor",
                "qty": 10,
                "rate": 8500,
                "gst": 18,
            },
        }
        r = requests.post(f"{API}/llm/purchase-analysis",
                          json=payload,
                          headers=hdr(tokens, "director"), timeout=120)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "premium", f"Negotiate premium not honored for director: tier={d.get('tier')}"
        assert d["model"] == "claude-sonnet-4-5-20250929", f"unexpected model {d.get('model')}"


# ====================================================================
# 5. Regression — item-standardise still returns gpt-4o-mini
# ====================================================================

class TestItemStandardiseRegression:
    def test_standardise_cheap(self, tokens):
        r = requests.post(f"{API}/llm/item-standardise",
                          json={"description": "TEST_iter28 CAT6 UTP cable"},
                          headers=hdr(tokens, "purchase"), timeout=60)
        if r.status_code == 502:
            pytest.skip("LLM upstream unavailable")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["tier"] == "cheap"
        assert d["model"] == "gpt-4o-mini"
