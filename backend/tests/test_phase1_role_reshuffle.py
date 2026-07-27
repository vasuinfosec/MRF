"""Phase 1 — Role Reshuffle tests for Vasu Infosec MRF/PO backend.

Covers:
- New roles: director / pm / gm / purchase / admin via /auth/dev-login and /auth/me
- Legacy role auto-migration (site_engineer -> pm, project_manager -> pm, billing -> purchase)
- MRF approve authorisation matrix (pm/gm/director/admin can, purchase cannot)
- PO /received restricted to purchase/director/admin
- /audit is admin-only (director gets 403)
- /users emails visibility per role
- Seed idempotency & VIS-101/102/103 pm@vasu.dev membership
"""
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
             or os.environ.get("EXPO_BACKEND_URL")
             or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


# ---------------- helpers ----------------
def dev_login(email: str, role: str, name: str = None):
    r = requests.post(f"{API}/auth/dev-login", json={
        "email": email, "role": role, "name": name or email.split("@")[0]
    }, timeout=15)
    return r


def h(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def admin_token():
    r = dev_login("admin@vasu.dev", "admin", "Admin")
    assert r.status_code == 200, r.text
    tok = r.json()["session_token"]
    # Ensure seed data present (idempotent)
    seed = requests.post(f"{API}/seed", headers=h(tok), timeout=30)
    assert seed.status_code == 200, seed.text
    return tok


@pytest.fixture(scope="module")
def tokens(admin_token):
    """Login all canonical seeded users."""
    out = {"admin": admin_token}
    for role, email in [
        ("director", "director@vasu.dev"),
        ("pm", "pm@vasu.dev"),
        ("gm", "gm@vasu.dev"),
        ("purchase", "purchase@vasu.dev"),
    ]:
        r = dev_login(email, role)
        assert r.status_code == 200, f"{role} login failed: {r.text}"
        out[role] = r.json()["session_token"]
    return out


# ---------------- module: new canonical roles ----------------
class TestNewRoles:
    def test_director_dev_login_and_me(self):
        r = dev_login("director@vasu.dev", "director", "Director")
        assert r.status_code == 200
        tok = r.json()["session_token"]
        assert r.json()["user"]["role"] == "director"
        me = requests.get(f"{API}/auth/me", headers=h(tok))
        assert me.status_code == 200
        assert me.json()["role"] == "director"

    def test_gm_dev_login_and_me(self):
        r = dev_login("gm@vasu.dev", "gm", "GM")
        assert r.status_code == 200
        tok = r.json()["session_token"]
        me = requests.get(f"{API}/auth/me", headers=h(tok))
        assert me.status_code == 200
        assert me.json()["role"] == "gm"

    def test_invalid_role_rejected(self):
        # Phase 2: site_engineer is now a VALID canonical role. Use a truly invalid one.
        r = dev_login(f"bogus_{uuid.uuid4().hex[:6]}@vasu.dev", "not_a_real_role", "Bogus")
        # dev_login validates role against ROLES
        assert r.status_code == 400, r.text


# ---------------- module: legacy role migration ----------------
class TestLegacyMigration:
    """dev-login only accepts canonical roles; migration happens on /auth/me for users
    who already have legacy roles persisted. Simulate that by writing directly through
    a fresh user creation then patching via admin, OR by creating an old-role session
    directly. Since we can't hit DB, we test the read-time migration path by:
    seeding a user via dev-login with a canonical role, then manually flipping their
    role via /users/role to a canonical value is limited — /users/role rejects legacy.
    So we exercise via a direct DB-less route: we cannot inject legacy roles from an
    external test without DB access. Instead we assert the LEGACY_ROLE_MAP semantics
    through the endpoint contract: dev-login rejects legacy roles (proves canonical
    boundary), and describe that any pre-existing legacy user is migrated on /auth/me.

    To still validate migration end-to-end, we go through the DB via Mongo.
    """

    @pytest.fixture(scope="class")
    def mongo(self):
        from motor.motor_asyncio import AsyncIOMotorClient  # noqa
        # Use sync pymongo for tests to avoid asyncio boilerplate
        import pymongo
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        c = pymongo.MongoClient(mongo_url)
        return c[db_name]

    def _create_legacy_user(self, mongo, legacy_role: str):
        email = f"TEST_legacy_{legacy_role}_{uuid.uuid4().hex[:6]}@vasu.dev"
        uid = f"user_{uuid.uuid4().hex[:12]}"
        from datetime import datetime, timezone, timedelta
        mongo.users.insert_one({
            "user_id": uid, "email": email,
            "name": f"Legacy {legacy_role}", "picture": "",
            "role": legacy_role, "is_active": True,
            "created_at": datetime.now(timezone.utc),
        })
        token = f"dev_{uuid.uuid4().hex}"
        mongo.user_sessions.insert_one({
            "session_token": token, "user_id": uid,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            "created_at": datetime.now(timezone.utc),
        })
        return uid, email, token

    def test_site_engineer_stays_site_engineer(self, mongo):
        # Phase 2: site_engineer is now a FIRST-CLASS role. It is NOT migrated to pm.
        uid, email, tok = self._create_legacy_user(mongo, "site_engineer")
        me = requests.get(f"{API}/auth/me", headers=h(tok))
        assert me.status_code == 200, me.text
        assert me.json()["role"] == "site_engineer"
        # persisted
        u = mongo.users.find_one({"user_id": uid})
        assert u["role"] == "site_engineer"
        mongo.users.delete_one({"user_id": uid})
        mongo.user_sessions.delete_one({"session_token": tok})

    def test_project_manager_migrates_to_pm(self, mongo):
        uid, email, tok = self._create_legacy_user(mongo, "project_manager")
        me = requests.get(f"{API}/auth/me", headers=h(tok))
        assert me.status_code == 200
        assert me.json()["role"] == "pm"
        assert mongo.users.find_one({"user_id": uid})["role"] == "pm"
        mongo.users.delete_one({"user_id": uid})
        mongo.user_sessions.delete_one({"session_token": tok})

    def test_billing_migrates_to_purchase(self, mongo):
        uid, email, tok = self._create_legacy_user(mongo, "billing")
        me = requests.get(f"{API}/auth/me", headers=h(tok))
        assert me.status_code == 200
        assert me.json()["role"] == "purchase"
        assert mongo.users.find_one({"user_id": uid})["role"] == "purchase"
        mongo.users.delete_one({"user_id": uid})
        mongo.user_sessions.delete_one({"session_token": tok})


# ---------------- module: /users email visibility ----------------
class TestUsersEmailVisibility:
    def test_admin_sees_emails(self, tokens):
        r = requests.get(f"{API}/users", headers=h(tokens["admin"]))
        assert r.status_code == 200
        users = r.json()
        assert any(u["email"] == "director@vasu.dev" for u in users), \
            "admin should see director@vasu.dev email"
        assert all(u["email"] for u in users), "admin should get full emails"

    @pytest.mark.parametrize("role", ["pm", "gm", "purchase", "director"])
    def test_non_admin_gets_empty_emails(self, tokens, role):
        r = requests.get(f"{API}/users", headers=h(tokens[role]))
        assert r.status_code == 200, r.text
        users = r.json()
        assert users, "should still return user directory"
        assert all(u["email"] == "" for u in users), \
            f"{role} must see empty emails, got {[u['email'] for u in users if u['email']][:3]}"


# ---------------- module: /audit admin-only ----------------
class TestAuditAdminOnly:
    def test_admin_can_access(self, tokens):
        r = requests.get(f"{API}/audit", headers=h(tokens["admin"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.parametrize("role", ["director", "pm", "gm", "purchase"])
    def test_others_forbidden(self, tokens, role):
        r = requests.get(f"{API}/audit", headers=h(tokens[role]))
        assert r.status_code == 403, f"{role} got {r.status_code}: {r.text}"


# ---------------- module: seeded PM on projects ----------------
class TestSeededPMOnProjects:
    def test_pm_user_in_project_managers(self, admin_token, tokens):
        # find pm user_id
        r = requests.get(f"{API}/users", headers=h(admin_token))
        pm = next(u for u in r.json() if u["email"] == "pm@vasu.dev")
        # fetch projects
        rp = requests.get(f"{API}/projects?all=true", headers=h(admin_token))
        assert rp.status_code == 200
        projects = {p["code"]: p for p in rp.json()}
        for code in ("VIS-101", "VIS-102", "VIS-103"):
            assert code in projects, f"{code} not seeded"
            assert pm["user_id"] in (projects[code].get("project_managers") or []), \
                f"pm@vasu.dev missing from {code} project_managers"


# ---------------- module: MRF approve authorisation ----------------
class TestMRFApprove:
    """Create an MRF under VIS-101 (pm@vasu.dev is PM there) and test approve matrix."""

    @pytest.fixture(scope="class")
    def mrf_context(self, admin_token, tokens):
        # Get VIS-101 project id
        rp = requests.get(f"{API}/projects?all=true", headers=h(admin_token))
        proj = next(p for p in rp.json() if p["code"] == "VIS-101")
        return proj

    def _create_mrf(self, admin_token, project_id):
        body = {
            "project_id": project_id,
            "site": "Bangalore Whitefield",
            "required_by": "2026-06-01",
            "requesting_person": "TEST_Requester",
            "system_category": "Fire Alarm",
            "items": [{
                "description": "TEST_Smoke Detector",
                "unit": "Nos",
                "qty_requested": 10,
                "billable": True,
            }],
            "remarks": "TEST_mrf",
        }
        r = requests.post(f"{API}/mrf", headers=h(admin_token), json=body)
        assert r.status_code == 200, r.text
        return r.json()["mrf_id"]

    def _approve(self, token, mrf_id):
        return requests.post(f"{API}/mrf/{mrf_id}/approve",
                             headers=h(token),
                             json={"action": "approve", "comment": "TEST"})

    def test_pm_assigned_can_approve(self, admin_token, tokens, mrf_context):
        mid = self._create_mrf(admin_token, mrf_context["project_id"])
        r = self._approve(tokens["pm"], mid)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    def test_pm_not_on_project_forbidden(self, admin_token, tokens, mrf_context):
        # Create a new project the seeded pm is NOT on
        new_code = f"TEST-{uuid.uuid4().hex[:6]}"
        newp = requests.post(f"{API}/projects", headers=h(admin_token), json={
            "code": new_code, "name": "TEST_project", "site": "TestSite",
            "client": "TESTC", "site_engineers": [], "project_managers": [],
        })
        assert newp.status_code == 200, newp.text
        proj = newp.json()
        mid = self._create_mrf(admin_token, proj["project_id"])
        r = self._approve(tokens["pm"], mid)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_gm_can_approve_any(self, admin_token, tokens, mrf_context):
        mid = self._create_mrf(admin_token, mrf_context["project_id"])
        r = self._approve(tokens["gm"], mid)
        assert r.status_code == 200, r.text

    def test_director_can_approve_any(self, admin_token, tokens, mrf_context):
        mid = self._create_mrf(admin_token, mrf_context["project_id"])
        r = self._approve(tokens["director"], mid)
        assert r.status_code == 200, r.text

    def test_admin_can_approve(self, admin_token, tokens, mrf_context):
        mid = self._create_mrf(admin_token, mrf_context["project_id"])
        r = self._approve(tokens["admin"], mid)
        assert r.status_code == 200, r.text

    def test_purchase_forbidden(self, admin_token, tokens, mrf_context):
        mid = self._create_mrf(admin_token, mrf_context["project_id"])
        r = self._approve(tokens["purchase"], mid)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ---------------- module: PO /received role restriction ----------------
class TestPOReceived:
    @pytest.fixture(scope="class")
    def po_id(self, admin_token, tokens):
        # Reuse VIS-101 project + create a fresh MRF, approve, create PO
        rp = requests.get(f"{API}/projects?all=true", headers=h(admin_token))
        proj = next(p for p in rp.json() if p["code"] == "VIS-101")
        rv = requests.get(f"{API}/vendors", headers=h(admin_token))
        assert rv.status_code == 200 and rv.json(), "no vendors seeded"
        vendor = rv.json()[0]

        mrf_body = {
            "project_id": proj["project_id"],
            "site": proj["site"], "required_by": "2026-06-15",
            "requesting_person": "TEST_R", "system_category": "Fire Alarm",
            "items": [{"description": "TEST_Panel", "unit": "Nos",
                       "qty_requested": 5, "billable": True}],
        }
        rm = requests.post(f"{API}/mrf", headers=h(admin_token), json=mrf_body)
        assert rm.status_code == 200, rm.text
        mrf = rm.json()
        # approve as admin
        ap = requests.post(f"{API}/mrf/{mrf['mrf_id']}/approve",
                           headers=h(admin_token), json={"action": "approve"})
        assert ap.status_code == 200, ap.text
        # create PO
        po_body = {
            "vendor_id": vendor["vendor_id"],
            "project_id": proj["project_id"],
            "delivery_site": proj["site"],
            "items": [{
                "mrf_id": mrf["mrf_id"],
                "item_line_id": mrf["items"][0]["item_line_id"],
                "description": "TEST_Panel", "unit": "Nos",
                "qty": 5, "rate": 100, "discount": 0, "gst": 18,
            }],
        }
        rpo = requests.post(f"{API}/po", headers=h(tokens["purchase"]), json=po_body)
        assert rpo.status_code == 200, rpo.text
        return rpo.json()["po_id"]

    def _received(self, token, po_id):
        return requests.post(f"{API}/po/{po_id}/received",
                             headers=h(token), json={})

    def test_pm_forbidden(self, tokens, po_id):
        # Phase 2: PM assigned to the project CAN record GRN (spec includes PM in GRN_ROLES).
        r = self._received(tokens["pm"], po_id)
        assert r.status_code == 200, f"pm got {r.status_code}: {r.text}"

    def test_gm_forbidden(self, tokens, po_id):
        r = self._received(tokens["gm"], po_id)
        assert r.status_code == 403, f"gm got {r.status_code}: {r.text}"

    def test_director_allowed_or_flag(self, tokens, po_id):
        """Spec says: purchase/director/admin -> 200. Code currently allows only
        purchase and admin. Report exact status."""
        r = self._received(tokens["director"], po_id)
        # Spec ask: confirm director allowed (200). Fail loudly if not.
        assert r.status_code == 200, (
            f"SPEC EXPECTS director allowed on /po/received but got "
            f"{r.status_code}: {r.text}"
        )

    def test_purchase_allowed(self, admin_token, tokens):
        # fresh PO so we're not receiving twice
        po_id2 = TestPOReceived.po_id.__wrapped__(self, admin_token, tokens) \
            if hasattr(TestPOReceived.po_id, "__wrapped__") else None
        # Simpler: purchase uses same PO — after director attempt already fully received,
        # receiving again returns 200 with no change (any_received=False path).
        rp = requests.get(f"{API}/projects?all=true", headers=h(admin_token))
        proj = next(p for p in rp.json() if p["code"] == "VIS-101")
        r = requests.get(f"{API}/po?project_id=" + proj["project_id"],
                         headers=h(admin_token))
        assert r.status_code == 200 and r.json()
        # Use most recent PO
        po = r.json()[0]
        rr = self._received(tokens["purchase"], po["po_id"])
        assert rr.status_code == 200, rr.text

    def test_admin_allowed(self, admin_token, tokens):
        rp = requests.get(f"{API}/projects?all=true", headers=h(admin_token))
        proj = next(p for p in rp.json() if p["code"] == "VIS-101")
        r = requests.get(f"{API}/po?project_id=" + proj["project_id"],
                         headers=h(admin_token))
        po = r.json()[0]
        rr = self._received(admin_token, po["po_id"])
        assert rr.status_code == 200, rr.text
