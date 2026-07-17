"""Backend tests for the AI Cost-Control & Supplier Performance feature set (iter 27).

Covers:
  - GET /api/llm/my-budget            (director unlimited; pm capped ₹200; premium_allowed)
  - GET /api/llm/purchase-analysis/route (model_labels, premium_allowed)
  - POST /api/llm/purchase-analysis (deterministic mode never touches budget)
  - POST /api/llm/purchase-analysis (premium tier: silent downgrade for non-director)
  - POST /api/llm/purchase-analysis (premium tier: works for director)
  - GET /api/llm/admin/spend-monthly (director/admin only)
  - GET /api/llm/admin/supplier-performance (director/admin/gm/purchase; site_engineer 403)
  - Regression: standard MRF/PO/vendors list endpoints still respond.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"
API = f"{BASE_URL}/api"


# ---------- fixtures ----------
def _login(role: str, email: str) -> str:
    r = requests.post(
        f"{API}/auth/dev-login",
        json={"email": email, "role": role, "name": role.title()},
        timeout=20,
    )
    assert r.status_code == 200, f"dev-login({role}) failed: {r.status_code} {r.text}"
    tok = r.json()["session_token"]
    assert tok
    return tok


@pytest.fixture(scope="module")
def tokens():
    return {
        "director": _login("director", "director@vasu.dev"),
        "pm": _login("pm", "pm@vasu.dev"),
        "admin": _login("admin", "admin@vasu.dev"),
        "purchase": _login("purchase", "purchase@vasu.dev"),
        "site_engineer": _login("site_engineer", "siteeng@vasu.dev"),
        "gm": _login("gm", "gm@vasu.dev"),
    }


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- 1) /api/llm/my-budget ----------
class TestMyBudget:
    def test_director_unlimited(self, tokens):
        r = requests.get(f"{API}/llm/my-budget", headers=_h(tokens["director"]), timeout=20)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["role"] == "director"
        assert b["unlimited"] is True
        assert b["limit_inr"] is None
        assert b["remaining_inr"] is None
        assert b["premium_allowed"] is True

    def test_pm_capped_200(self, tokens):
        r = requests.get(f"{API}/llm/my-budget", headers=_h(tokens["pm"]), timeout=20)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["role"] == "pm"
        assert b["unlimited"] is False
        assert b["limit_inr"] == 200.0
        assert b["remaining_inr"] is not None
        assert 0 <= b["remaining_inr"] <= 200.0
        # remaining = limit - spent (approx)
        assert round(b["remaining_inr"] + b["spent_inr"], 2) == 200.0
        assert b["premium_allowed"] is False


# ---------- 2) /api/llm/purchase-analysis/route ----------
class TestRoute:
    def test_director_has_all_labels(self, tokens):
        r = requests.get(
            f"{API}/llm/purchase-analysis/route",
            params={"description": "cat6 cable", "qty": 10, "rate": 5000},
            headers=_h(tokens["director"]),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("model_labels"), dict)
        for k in ("deterministic", "cheap", "premium"):
            assert k in j["model_labels"], f"missing label {k}"
        assert j["premium_allowed"] is True

    def test_pm_premium_disallowed(self, tokens):
        r = requests.get(
            f"{API}/llm/purchase-analysis/route",
            params={"description": "cat6 cable", "qty": 10, "rate": 5000},
            headers=_h(tokens["pm"]),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["premium_allowed"] is False


# ---------- 3) Deterministic mode (never triggers budget) ----------
class TestDeterministicMode:
    payload = {
        "description": "cat6 cable",
        "qty": 10,
        "tier": "deterministic",
        "current_quote": {
            "vendor_name": "ABC", "rate": 5000, "qty": 10,
            "gst": 18, "freight": 0,
        },
    }

    def test_pm_deterministic_no_budget_error(self, tokens):
        r = requests.post(
            f"{API}/llm/purchase-analysis",
            headers=_h(tokens["pm"]),
            json=self.payload,
            timeout=60,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        d = r.json()
        assert d.get("tier") == "deterministic"
        assert d.get("model") == "deterministic"
        parsed = d.get("output_parsed") or {}
        assert parsed.get("_engine") == "deterministic"
        assert parsed.get("decision") in (
            "ok_current", "negotiate_more", "reject_and_retender", "issue_at_target"
        )
        cost = d.get("cost") or {}
        assert cost.get("cost_inr") == 0.0

    def test_director_deterministic_works(self, tokens):
        r = requests.post(
            f"{API}/llm/purchase-analysis",
            headers=_h(tokens["director"]),
            json=self.payload,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "deterministic"
        assert (d.get("output_parsed") or {}).get("_engine") == "deterministic"


# ---------- 4) Premium tier: silent downgrade for non-director ----------
class TestPremiumDowngrade:
    def test_pm_premium_downgraded_to_cheap(self, tokens):
        body = {
            "description": "cat6 cable",
            "qty": 10,
            "tier": "premium",
            "current_quote": {
                "vendor_name": "ABC", "rate": 5000, "qty": 10,
                "gst": 18, "freight": 0,
            },
        }
        r = requests.post(
            f"{API}/llm/purchase-analysis",
            headers=_h(tokens["pm"]),
            json=body,
            timeout=90,
        )
        # If pm's monthly budget is exhausted from earlier runs, expect 402;
        # otherwise expect 200 with a downgrade flag.
        if r.status_code == 402:
            pytest.skip("PM budget already exhausted for this month; downgrade path unreachable without reset")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "cheap", f"expected effective tier=cheap after downgrade, got {d.get('tier')}"
        assert d.get("model") == "gpt-4o-mini"
        parsed = d.get("output_parsed") or {}
        routing = (parsed.get("_computed_by_server") or {}).get("routing") or {}
        assert routing.get("downgraded") is True
        assert "Director" in (routing.get("downgrade_reason") or ""), routing


# ---------- 5) Premium tier: works for director ----------
class TestPremiumDirector:
    def test_director_premium_ok(self, tokens):
        body = {
            "description": "cat6 cable",
            "qty": 10,
            "tier": "premium",
            "current_quote": {
                "vendor_name": "ABC", "rate": 5000, "qty": 10,
                "gst": 18, "freight": 0,
            },
        }
        r = requests.post(
            f"{API}/llm/purchase-analysis",
            headers=_h(tokens["director"]),
            json=body,
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("tier") == "premium", d
        assert d.get("model") == "claude-sonnet-4-5-20250929", d


# ---------- 6) /api/llm/admin/spend-monthly ----------
class TestAdminSpend:
    def test_director_ok(self, tokens):
        r = requests.get(
            f"{API}/llm/admin/spend-monthly?months=3",
            headers=_h(tokens["director"]),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("period_start_this_month", "grand_total_inr_this_month",
                  "period_range", "by_user", "by_model", "budget_config",
                  "premium_allowed_roles"):
            assert k in j, f"missing key {k}"
        assert isinstance(j["period_range"], list)
        assert isinstance(j["by_user"], list)
        assert isinstance(j["by_model"], list)
        assert j["premium_allowed_roles"] == ["director"]
        # by_user rows must carry limit/remaining/role
        for row in j["by_user"]:
            for k in ("limit_inr", "remaining_inr", "role"):
                assert k in row, f"by_user row missing {k}: {row}"

    def test_admin_ok(self, tokens):
        r = requests.get(
            f"{API}/llm/admin/spend-monthly?months=3",
            headers=_h(tokens["admin"]),
            timeout=30,
        )
        assert r.status_code == 200, r.text

    def test_pm_forbidden(self, tokens):
        r = requests.get(
            f"{API}/llm/admin/spend-monthly?months=3",
            headers=_h(tokens["pm"]),
            timeout=30,
        )
        assert r.status_code == 403, r.text


# ---------- 7) /api/llm/admin/supplier-performance ----------
class TestSupplierPerf:
    def test_director_ok(self, tokens):
        r = requests.get(
            f"{API}/llm/admin/supplier-performance",
            headers=_h(tokens["director"]),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        if rows:
            row = rows[0]
            for k in ("total_orders", "completed_orders", "on_time_pct",
                      "avg_delay_days", "last_order_date"):
                assert k in row, f"missing {k}"

    @pytest.mark.parametrize("role", ["admin", "gm", "purchase"])
    def test_other_privileged_ok(self, tokens, role):
        r = requests.get(
            f"{API}/llm/admin/supplier-performance",
            headers=_h(tokens[role]),
            timeout=30,
        )
        assert r.status_code == 200, f"{role}: {r.status_code} {r.text}"
        assert isinstance(r.json(), list)

    def test_site_engineer_forbidden(self, tokens):
        r = requests.get(
            f"{API}/llm/admin/supplier-performance",
            headers=_h(tokens["site_engineer"]),
            timeout=30,
        )
        assert r.status_code == 403, r.text


# ---------- 8) Regression: standard endpoints still work ----------
class TestRegressionEndpoints:
    def test_mrfs_list(self, tokens):
        r = requests.get(f"{API}/mrf", headers=_h(tokens["director"]), timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_pos_list(self, tokens):
        r = requests.get(f"{API}/po", headers=_h(tokens["director"]), timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_vendors_list(self, tokens):
        r = requests.get(f"{API}/vendors", headers=_h(tokens["director"]), timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
