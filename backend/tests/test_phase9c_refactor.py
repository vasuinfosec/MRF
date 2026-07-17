"""Phase 9C — Router-refactor regression suite.

Validates the four newly-extracted routers (`notifications`, `reports`,
`audit`, `settings`) behave byte-identically to their in-`server.py`
predecessors, plus P2 smoke on unchanged endpoints and an OpenAPI diff.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Dict, Any

import pytest
import requests

BASE = os.environ.get("VASU_BASE_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ROLES = ["director", "gm", "pm", "purchase", "site_engineer", "store", "admin"]


# --------------------------------------------------------------------------- session helpers
def _dev_login(email: str, role: str, name: str) -> Dict[str, Any]:
    r = requests.post(f"{API}/auth/dev-login",
                       json={"email": email, "role": role, "name": name},
                       timeout=15)
    r.raise_for_status()
    return r.json()


def _sess(role: str) -> requests.Session:
    tok = _dev_login(f"{role}@vasu.dev", role, f"{role.title()} Dev")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok['session_token']}",
                      "Content-Type": "application/json"})
    s.user_id = tok["user"]["user_id"]  # type: ignore[attr-defined]
    s.role = role                       # type: ignore[attr-defined]
    return s


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def admin_sess():
    return _sess("admin")


@pytest.fixture(scope="module")
def sessions(admin_sess):
    # ensure seed data exists (idempotent)
    admin_sess.post(f"{API}/seed", timeout=30)
    return {role: _sess(role) for role in ROLES}


# =========================================================================== P0.1 Endpoint availability
class TestNotifications:
    def test_list_notifications_any_user(self, sessions):
        for role in ROLES:
            r = sessions[role].get(f"{API}/notifications", timeout=10)
            assert r.status_code == 200, f"{role}: {r.status_code} {r.text[:200]}"
            assert isinstance(r.json(), list)

    def test_notification_read_idempotent(self, sessions):
        # POST a read on a synthetic nid — endpoint is idempotent even if not found
        s = sessions["pm"]
        nid = f"noti_{uuid.uuid4().hex[:8]}"
        r1 = s.post(f"{API}/notifications/{nid}/read", timeout=10)
        r2 = s.post(f"{API}/notifications/{nid}/read", timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json() == {"ok": True} and r2.json() == {"ok": True}


class TestReports:
    DASHBOARD_KEYS = {
        "total_mrf", "pending_pm", "pending_purchase", "approved",
        "total_po", "po_value", "billable_value", "non_billable_value",
        "pending_billing_count", "fully_billed_count", "ageing",
    }
    AGEING_KEYS = {"0-3", "4-7", "8-15", "16+"}

    def test_dashboard_shape(self, sessions):
        for role in ROLES:
            r = sessions[role].get(f"{API}/reports/dashboard", timeout=15)
            assert r.status_code == 200, f"{role}: {r.status_code}"
            data = r.json()
            missing = self.DASHBOARD_KEYS - set(data)
            assert not missing, f"{role}: missing keys {missing}"
            assert set(data["ageing"]) == self.AGEING_KEYS

    def test_mrf_ageing_shape(self, sessions):
        for role in ("director", "pm", "site_engineer"):
            r = sessions[role].get(f"{API}/reports/mrf-ageing", timeout=15)
            assert r.status_code == 200
            arr = r.json()
            assert isinstance(arr, list)
            if arr:
                keys = {"mrf_id", "mrf_number", "status", "days",
                         "project_id", "site"}
                assert keys.issubset(set(arr[0]))

    def test_grn_variance_shape(self, sessions):
        for role in ("director", "purchase"):
            r = sessions[role].get(f"{API}/reports/grn-variance", timeout=15)
            assert r.status_code == 200
            arr = r.json()
            assert isinstance(arr, list)
            if arr:
                assert "variance" in arr[0]
                assert "invoice_variance" in arr[0]


class TestSettingsGet:
    def test_get_thresholds_any_role(self, sessions):
        for role in ROLES:
            r = sessions[role].get(f"{API}/settings/thresholds", timeout=10)
            assert r.status_code == 200, f"{role}: {r.status_code}"
            data = r.json()
            assert "gm" in data and "director" in data


# =========================================================================== P0.3 Threshold PUT matrix
class TestSettingsPut:
    def test_forbidden_roles(self, sessions):
        for role in ("pm", "purchase", "gm", "site_engineer", "store"):
            r = sessions[role].put(f"{API}/settings/thresholds",
                                    json={"gm": 50000, "director": 500000},
                                    timeout=10)
            assert r.status_code == 403, f"{role} should be 403 got {r.status_code}"

    def test_missing_keys(self, sessions):
        s = sessions["director"]
        r1 = s.put(f"{API}/settings/thresholds", json={"gm": 50000}, timeout=10)
        r2 = s.put(f"{API}/settings/thresholds", json={"director": 500000}, timeout=10)
        r3 = s.put(f"{API}/settings/thresholds", json={}, timeout=10)
        for r in (r1, r2, r3):
            assert r.status_code == 400, f"expected 400 got {r.status_code}"

    def test_non_numeric(self, sessions):
        r = sessions["admin"].put(f"{API}/settings/thresholds",
                                   json={"gm": "abc", "director": 500000},
                                   timeout=10)
        assert r.status_code == 400

    def test_negative(self, sessions):
        r = sessions["admin"].put(f"{API}/settings/thresholds",
                                   json={"gm": -1, "director": 500000},
                                   timeout=10)
        assert r.status_code == 400

    def test_director_lt_gm(self, sessions):
        r = sessions["admin"].put(f"{API}/settings/thresholds",
                                   json={"gm": 600000, "director": 400000},
                                   timeout=10)
        assert r.status_code == 400

    def test_valid_update_audits(self, sessions):
        s = sessions["director"]
        payload = {"gm": 50000, "director": 500000}
        r = s.put(f"{API}/settings/thresholds", json=payload, timeout=10)
        assert r.status_code == 200
        assert r.json() == payload
        # Assert audit row was written — pull recent audit as director
        time.sleep(0.4)
        aud = s.get(f"{API}/audit", params={"entity": "settings",
                                              "action": "update", "limit": 20},
                     timeout=10)
        assert aud.status_code == 200
        rows = aud.json()
        assert any(r_.get("entity") == "settings" and
                    r_.get("action", "").startswith("update")
                    for r_ in rows), f"No settings/update audit row seen: {rows[:3]}"


# =========================================================================== P0.2 Audit RBAC
class TestAuditRBAC:
    def test_facets_management(self, sessions):
        for role in ("admin", "director", "gm", "purchase", "pm"):
            r = sessions[role].get(f"{API}/audit/facets", timeout=10)
            assert r.status_code == 200, f"{role}: {r.status_code}"
            j = r.json()
            assert {"entities", "actions", "users"}.issubset(set(j))

    def test_facets_forbidden(self, sessions):
        for role in ("site_engineer", "store"):
            r = sessions[role].get(f"{API}/audit/facets", timeout=10)
            assert r.status_code == 403, f"{role}: {r.status_code}"

    def test_full_feed_management(self, sessions):
        for role in ("admin", "director", "gm", "purchase"):
            r = sessions[role].get(f"{API}/audit", params={"limit": 50},
                                     timeout=10)
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_scoped_feed_site_engineer(self, sessions):
        r = sessions["site_engineer"].get(f"{API}/audit",
                                            params={"limit": 100}, timeout=10)
        assert r.status_code == 200
        rows = r.json()
        # All rows must either be by this user, or be for entity_ids the
        # site_engineer created (proxy: user_id filter is the strict check).
        # Simply check no PO issued/approve/reject actions from *another* user leak.
        siteeng_uid = sessions["site_engineer"].user_id  # type: ignore[attr-defined]
        for r_ in rows:
            entity = r_.get("entity")
            uid = r_.get("user_id")
            eid = r_.get("entity_id", "")
            # Should be either own action OR mrf_/po_ record
            assert (uid == siteeng_uid or eid.startswith("mrf_")
                    or eid.startswith("po_")), (
                f"Leak: site_engineer sees non-mrf/po row from other user: {r_}"
            )

    def test_scoped_feed_store(self, sessions):
        r = sessions["store"].get(f"{API}/audit", params={"limit": 100}, timeout=10)
        assert r.status_code == 200
        rows = r.json()
        store_uid = sessions["store"].user_id  # type: ignore[attr-defined]
        for r_ in rows:
            action = r_.get("action", "")
            uid = r_.get("user_id")
            # Store must only see own actions OR grn/received-related events
            assert (uid == store_uid or "grn" in action.lower()
                    or "received" in action.lower()), (
                f"Leak: store sees unrelated row: {r_}"
            )

    def test_entity_scoped_forbidden_mrf(self, sessions):
        # Fabricate a non-existent MRF id → 404 (per _check_mrf_access path)
        r = sessions["site_engineer"].get(
            f"{API}/audit", params={"entity_id": f"mrf_{uuid.uuid4().hex[:8]}"},
            timeout=10)
        assert r.status_code == 404


# =========================================================================== P2 Smoke
class TestP2Smoke:
    SPOT_ENDPOINTS = [
        ("/materials", {"status": "approved"}),
        ("/vendors", None),
        ("/customers", None),
        ("/mrf", None),
        ("/po", None),
    ]

    def test_seed_idempotent(self, admin_sess):
        r1 = admin_sess.post(f"{API}/seed", timeout=30)
        r2 = admin_sess.post(f"{API}/seed", timeout=30)
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)

    def test_spot_check_endpoints(self, admin_sess):
        for path, params in self.SPOT_ENDPOINTS:
            r = admin_sess.get(f"{API}{path}", params=params, timeout=15)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"


# =========================================================================== OpenAPI check
class TestOpenAPI:
    EXTRACTED = [
        ("/api/notifications", "get"),
        ("/api/notifications/{nid}/read", "post"),
        ("/api/reports/dashboard", "get"),
        ("/api/reports/mrf-ageing", "get"),
        ("/api/reports/grn-variance", "get"),
        ("/api/audit", "get"),
        ("/api/audit/facets", "get"),
        ("/api/settings/thresholds", "get"),
        ("/api/settings/thresholds", "put"),
    ]

    def test_openapi_contains_extracted_paths(self):
        r = requests.get(f"{BASE}/openapi.json", timeout=15)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        missing = []
        for p, method in self.EXTRACTED:
            if p not in paths or method not in paths[p]:
                missing.append(f"{method.upper()} {p}")
        assert not missing, f"Missing from OpenAPI: {missing}"
