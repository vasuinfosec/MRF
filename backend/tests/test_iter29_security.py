"""iter-29 security fixes validation.

Covers SEC-001 (dev-login host guard), SEC-002 (customer RBAC),
SEC-003 (short-lived download tokens).
"""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                      "https://purchase-workflow-10.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
LOCAL = "http://localhost:8001/api"


def _dev_login(email, role, name=None, base=API):
    r = requests.post(f"{base}/auth/dev-login",
                      json={"email": email, "role": role,
                            "name": name or email.split("@")[0]}, timeout=15)
    return r


@pytest.fixture(scope="session")
def tokens():
    out = {}
    for email, role in [
        ("director@vasu.dev", "director"),
        ("pm@vasu.dev", "pm"),
        ("siteeng@vasu.dev", "site_engineer"),
        ("purchase@vasu.dev", "purchase"),
        ("admin@vasu.dev", "admin"),
        ("gm@vasu.dev", "gm"),
        ("store@vasu.dev", "store"),
    ]:
        r = _dev_login(email, role)
        assert r.status_code == 200, f"dev-login for {role} failed: {r.status_code} {r.text}"
        out[role] = r.json()["session_token"]
    return out


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# =========================================================================
# SEC-001: Dev-login host guard
# =========================================================================
class TestSec001DevLoginHostGuard:
    def test_preview_host_allowed_200(self):
        r = _dev_login("admin@vasu.dev", "admin", base=API)
        assert r.status_code == 200
        assert r.json().get("session_token", "").startswith("dev_")

    def test_localhost_allowed_200(self):
        r = requests.post(f"{LOCAL}/auth/dev-login",
                          json={"email": "admin@vasu.dev", "role": "admin",
                                "name": "Admin"}, timeout=10)
        assert r.status_code == 200, r.text

    def test_production_host_blocked_404(self):
        # Send to localhost but pretend to be production via BOTH headers.
        r = requests.post(f"{LOCAL}/auth/dev-login",
                          json={"email": "admin@vasu.dev", "role": "admin",
                                "name": "Admin"},
                          headers={
                              "Host": "myapp.production.com",
                              "X-Forwarded-Host": "myapp.production.com",
                          }, timeout=10)
        assert r.status_code == 404, f"expected 404, got {r.status_code}"

    def test_audit_log_records_block(self, tokens):
        # Fire another blocked request to guarantee an entry.
        requests.post(f"{LOCAL}/auth/dev-login",
                      json={"email": "attacker@evil.com", "role": "admin"},
                      headers={"Host": "evil.production.com",
                               "X-Forwarded-Host": "evil.production.com"},
                      timeout=10)
        r = requests.get(f"{API}/audit",
                         params={"action": "dev_login_blocked", "limit": 5},
                         headers=_hdr(tokens["admin"]), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("items", data.get("rows", []))
        assert len(rows) >= 1, f"no dev_login_blocked audit rows: {data}"
        assert any(row.get("action") == "dev_login_blocked" for row in rows)


# =========================================================================
# SEC-002: Customer endpoint RBAC
# =========================================================================
class TestSec002CustomerRBAC:
    def test_site_engineer_blocked_list(self, tokens):
        r = requests.get(f"{API}/customers", headers=_hdr(tokens["site_engineer"]), timeout=10)
        assert r.status_code == 403
        assert "management" in r.json().get("detail", "").lower()

    def test_store_blocked_list(self, tokens):
        r = requests.get(f"{API}/customers", headers=_hdr(tokens["store"]), timeout=10)
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["pm", "purchase", "gm", "director", "admin"])
    def test_management_roles_allowed_list(self, tokens, role):
        r = requests.get(f"{API}/customers", headers=_hdr(tokens[role]), timeout=15)
        assert r.status_code == 200, f"{role} got {r.status_code}: {r.text[:200]}"
        assert isinstance(r.json(), list)

    def test_site_engineer_blocked_detail(self, tokens):
        # Grab a customer id via admin to have a real one.
        r = requests.get(f"{API}/customers", headers=_hdr(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        customers = r.json()
        if not customers:
            pytest.skip("no customers seeded")
        cid = customers[0]["customer_id"]
        r2 = requests.get(f"{API}/customers/{cid}",
                          headers=_hdr(tokens["site_engineer"]), timeout=10)
        assert r2.status_code == 403

    def test_site_engineer_blocked_attachment(self, tokens):
        # cpo_id is guessable; RBAC must reject before the DB lookup.
        r = requests.get(f"{API}/customers/CUST-ANY/pos/CPO-ANY/attachment",
                         headers=_hdr(tokens["site_engineer"]), timeout=10)
        assert r.status_code == 403


# =========================================================================
# SEC-003: Short-lived, single-use download tokens
# =========================================================================
class TestSec003DownloadToken:
    def _mint(self, tok):
        r = requests.post(f"{API}/auth/download-token", headers=_hdr(tok), timeout=10)
        assert r.status_code == 200, r.text
        return r.json()

    def test_mint_shape(self, tokens):
        j = self._mint(tokens["pm"])
        assert j.get("expires_in") == 300
        t = j.get("token", "")
        assert t.startswith("dt_") and len(t) >= 30, f"bad token: {t!r}"

    def test_single_use_enforcement_header(self, tokens):
        j = self._mint(tokens["pm"])
        dt = j["token"]
        r1 = requests.get(f"{API}/customers", headers=_hdr(dt), timeout=10)
        assert r1.status_code == 200, r1.text
        r2 = requests.get(f"{API}/customers", headers=_hdr(dt), timeout=10)
        assert r2.status_code == 401
        assert "already used" in r2.json().get("detail", "").lower()

    def test_query_param_export_mrf(self, tokens):
        j = self._mint(tokens["admin"])
        dt = j["token"]
        r = requests.get(f"{API}/export/mrf", params={"token": dt}, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        ct = r.headers.get("Content-Type", "")
        assert ("spreadsheet" in ct) or ("excel" in ct) or ("octet" in ct), ct

    def test_legacy_session_token_query_still_works(self, tokens):
        # Backward-compat: raw session token via ?token= must still work
        r = requests.get(f"{API}/export/mrf",
                         params={"token": tokens["admin"]}, timeout=60)
        assert r.status_code == 200, r.text[:200]

    def test_legacy_session_token_header_still_works(self, tokens):
        r = requests.get(f"{API}/export/mrf",
                         headers=_hdr(tokens["admin"]), timeout=60)
        assert r.status_code == 200

    def test_ttl_index_present(self, tokens):
        # Structural check via mongo directly (server is on localhost)
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        async def _check():
            client = AsyncIOMotorClient("mongodb://localhost:27017")
            db = client["test_database"]
            idx = await db.download_tokens.list_indexes().to_list(None)
            client.close()
            return idx
        idx = asyncio.get_event_loop().run_until_complete(_check()) \
            if not asyncio.get_event_loop().is_running() else None
        if idx is None:
            # Fallback: use a fresh loop
            idx = asyncio.new_event_loop().run_until_complete(_check())
        ttl = [i for i in idx if i.get("expireAfterSeconds") is not None]
        assert ttl, f"no TTL index on download_tokens: {idx}"
        assert any("expires_at" in i.get("key", {}) for i in ttl)
