"""
Backend tests — Iteration 4: Project-wise team masters (site_engineers[], project_managers[])
Verifies access-control at:
  - GET /api/projects (role-based filtering + all=1 admin bypass)
  - POST /api/projects/{id}/team  (admin-only mutation)
  - POST /api/mrf                 (site_engineer must be on project team)
  - POST /api/mrf/{id}/approve    (project_manager must be on project team)
  - GET /api/mrf                  (PM sees only MRFs for their assigned projects)
Also regression checks for prior features (PO create, billing update, admin passthrough).
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_BACKEND_URL",
    "https://purchase-workflow-10.preview.emergentagent.com",
).rstrip("/")


# ---------- helpers ----------
def _login(email: str, role: str, name: str | None = None) -> tuple[str, dict]:
    r = requests.post(
        f"{BASE_URL}/api/auth/dev-login",
        json={"email": email, "role": role, "name": name or email.split("@")[0]},
        timeout=30,
    )
    assert r.status_code == 200, f"dev-login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["session_token"], d["user"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def seed():
    r = requests.post(f"{BASE_URL}/api/seed", timeout=60)
    assert r.status_code == 200, f"seed failed: {r.status_code}"
    return r.json()


@pytest.fixture(scope="module")
def tokens(seed):
    tokens = {}
    for role, email in [
        ("admin", "admin@vasu.dev"),
        ("site_engineer", "site@vasu.dev"),
        ("project_manager", "pm@vasu.dev"),
        ("purchase", "purchase@vasu.dev"),
        ("billing", "billing@vasu.dev"),
    ]:
        tok, user = _login(email, role)
        tokens[role] = {"token": tok, "user": user}
    return tokens


@pytest.fixture(scope="module")
def fresh_users():
    """Create fresh un-assigned site_engineer and project_manager for negative cases."""
    suffix = uuid.uuid4().hex[:6]
    fresh_se_email = f"TEST_new_site_{suffix}@vasu.dev"
    fresh_pm_email = f"TEST_new_pm_{suffix}@vasu.dev"
    se_tok, se_user = _login(fresh_se_email, "site_engineer", "TEST New Site")
    pm_tok, pm_user = _login(fresh_pm_email, "project_manager", "TEST New PM")
    return {
        "site_engineer": {"token": se_tok, "user": se_user, "email": fresh_se_email},
        "project_manager": {"token": pm_tok, "user": pm_user, "email": fresh_pm_email},
    }


# =====================================================
# Project model + seed
# =====================================================
class TestProjectSeed:
    def test_seed_projects_have_team_arrays(self, tokens):
        admin = tokens["admin"]
        r = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(admin["token"]), timeout=30)
        assert r.status_code == 200, r.text
        projects = r.json()
        assert isinstance(projects, list) and len(projects) >= 3, "expected >=3 seeded projects"
        seeded_codes = {"VIS-101", "VIS-102", "VIS-103"}
        seeded = [p for p in projects if p.get("code") in seeded_codes]
        assert len(seeded) == 3
        site_uid = tokens["site_engineer"]["user"]["user_id"]
        pm_uid = tokens["project_manager"]["user"]["user_id"]
        for p in seeded:
            assert isinstance(p.get("site_engineers"), list), f"{p['code']} site_engineers missing"
            assert isinstance(p.get("project_managers"), list), f"{p['code']} project_managers missing"
            assert site_uid in p["site_engineers"], f"{p['code']} missing seeded SE"
            assert pm_uid in p["project_managers"], f"{p['code']} missing seeded PM"

    def test_seed_idempotent_no_duplicates(self, tokens):
        # Call seed again
        r = requests.post(f"{BASE_URL}/api/seed", timeout=60)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        projects = r2.json()
        site_uid = tokens["site_engineer"]["user"]["user_id"]
        pm_uid = tokens["project_manager"]["user"]["user_id"]
        for p in projects:
            if p.get("code") in {"VIS-101", "VIS-102", "VIS-103"}:
                assert p["site_engineers"].count(site_uid) == 1, f"duplicate SE on {p['code']}"
                assert p["project_managers"].count(pm_uid) == 1, f"duplicate PM on {p['code']}"


# =====================================================
# GET /api/projects role-based filtering
# =====================================================
class TestProjectListFilter:
    def test_admin_sees_all(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["admin"]["token"]), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_admin_all_1_bypass(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_purchase_sees_all(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["purchase"]["token"]), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_billing_sees_all(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["billing"]["token"]), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_seeded_site_engineer_sees_assigned(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        assert r.status_code == 200
        codes = {p["code"] for p in r.json()}
        assert {"VIS-101", "VIS-102", "VIS-103"}.issubset(codes)

    def test_seeded_pm_sees_assigned(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["project_manager"]["token"]), timeout=30)
        assert r.status_code == 200
        codes = {p["code"] for p in r.json()}
        assert {"VIS-101", "VIS-102", "VIS-103"}.issubset(codes)

    def test_fresh_site_engineer_sees_none(self, fresh_users):
        r = requests.get(
            f"{BASE_URL}/api/projects",
            headers=_h(fresh_users["site_engineer"]["token"]),
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json() == [], f"fresh SE should see 0 projects, got {len(r.json())}"

    def test_fresh_pm_sees_none(self, fresh_users):
        r = requests.get(
            f"{BASE_URL}/api/projects",
            headers=_h(fresh_users["project_manager"]["token"]),
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json() == []


# =====================================================
# POST /api/projects/{id}/team — admin only
# =====================================================
class TestProjectTeamUpdate:
    def _first_project_id(self, admin_tok: str) -> str:
        r = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(admin_tok), timeout=30)
        for p in r.json():
            if p.get("code") == "VIS-101":
                return p["project_id"]
        return r.json()[0]["project_id"]

    def test_non_admin_forbidden(self, tokens, fresh_users):
        pid = self._first_project_id(tokens["admin"]["token"])
        for role in ["site_engineer", "project_manager", "purchase", "billing"]:
            r = requests.post(
                f"{BASE_URL}/api/projects/{pid}/team",
                headers=_h(tokens[role]["token"]),
                json={"site_engineers": [], "project_managers": []},
                timeout=30,
            )
            assert r.status_code == 403, f"{role} should be 403, got {r.status_code}"

    def test_admin_updates_team_and_persists(self, tokens, fresh_users):
        pid = self._first_project_id(tokens["admin"]["token"])
        # Save existing
        r0 = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        original = next(p for p in r0.json() if p["project_id"] == pid)
        orig_se = original["site_engineers"][:]
        orig_pm = original["project_managers"][:]

        fresh_se_uid = fresh_users["site_engineer"]["user"]["user_id"]
        fresh_pm_uid = fresh_users["project_manager"]["user"]["user_id"]
        new_se = list(set(orig_se + [fresh_se_uid]))
        new_pm = list(set(orig_pm + [fresh_pm_uid]))

        r = requests.post(
            f"{BASE_URL}/api/projects/{pid}/team",
            headers=_h(tokens["admin"]["token"]),
            json={"site_engineers": new_se, "project_managers": new_pm},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["project_id"] == pid
        assert fresh_se_uid in doc["site_engineers"]
        assert fresh_pm_uid in doc["project_managers"]

        # Verify fresh SE now sees this project
        r2 = requests.get(
            f"{BASE_URL}/api/projects",
            headers=_h(fresh_users["site_engineer"]["token"]),
            timeout=30,
        )
        assert any(p["project_id"] == pid for p in r2.json())

        # Verify fresh PM now sees this project
        r3 = requests.get(
            f"{BASE_URL}/api/projects",
            headers=_h(fresh_users["project_manager"]["token"]),
            timeout=30,
        )
        assert any(p["project_id"] == pid for p in r3.json())

    def test_admin_404_bad_project(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/projects/prj_does_not_exist_zzz/team",
            headers=_h(tokens["admin"]["token"]),
            json={"site_engineers": [], "project_managers": []},
            timeout=30,
        )
        assert r.status_code == 404

    def test_admin_empty_body_400(self, tokens):
        pid = self._first_project_id(tokens["admin"]["token"])
        r = requests.post(
            f"{BASE_URL}/api/projects/{pid}/team",
            headers=_h(tokens["admin"]["token"]),
            json={},
            timeout=30,
        )
        assert r.status_code == 400


# =====================================================
# MRF create restrictions by project membership
# =====================================================
def _sample_mrf_payload(project_id: str, site: str = "Test Site"):
    return {
        "project_id": project_id,
        "site": site,
        "required_by": "2026-05-01",
        "requesting_person": "TEST Person",
        "system_category": "Fire Alarm",
        "items": [{
            "description": "TEST Smoke Detector",
            "specification": "TEST spec",
            "part_number": "TESTPN1",
            "unit": "Nos",
            "qty_requested": 5,
            "purpose": "Test",
            "drawing_ref": "",
            "billable": True,
            "boq_ref": "",
            "remarks": "",
        }],
        "attachments": [],
        "remarks": "TEST_MRF",
    }


class TestMRFCreateGuard:
    def test_seeded_se_can_create_on_assigned(self, tokens):
        # Get an assigned project
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        pid = r.json()[0]["project_id"]
        r2 = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(tokens["site_engineer"]["token"]),
            json=_sample_mrf_payload(pid),
            timeout=30,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["project_id"] == pid
        assert r2.json()["status"] == "draft"

    def test_fresh_se_forbidden_on_unassigned(self, tokens, fresh_users):
        # Pick a project the fresh SE is NOT on (use VIS-102 – only seeded SE assigned there)
        r = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        unassigned = next(
            p for p in r.json()
            if p.get("code") == "VIS-102"
            and fresh_users["site_engineer"]["user"]["user_id"] not in (p.get("site_engineers") or [])
        )
        r2 = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(fresh_users["site_engineer"]["token"]),
            json=_sample_mrf_payload(unassigned["project_id"]),
            timeout=30,
        )
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"

    def test_fresh_se_allowed_after_assignment(self, tokens, fresh_users):
        # Assign fresh SE to VIS-102, then attempt create
        r = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        prj = next(p for p in r.json() if p["code"] == "VIS-102")
        fresh_uid = fresh_users["site_engineer"]["user"]["user_id"]
        new_se = list(set(prj["site_engineers"] + [fresh_uid]))
        ru = requests.post(
            f"{BASE_URL}/api/projects/{prj['project_id']}/team",
            headers=_h(tokens["admin"]["token"]),
            json={"site_engineers": new_se},
            timeout=30,
        )
        assert ru.status_code == 200
        r2 = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(fresh_users["site_engineer"]["token"]),
            json=_sample_mrf_payload(prj["project_id"]),
            timeout=30,
        )
        assert r2.status_code == 200, r2.text


# =====================================================
# MRF approve restrictions by PM team membership
# =====================================================
class TestMRFApproveGuard:
    @pytest.fixture(scope="class")
    def submitted_mrf(self, tokens):
        # Create + submit an MRF on VIS-101 (seeded SE assigned)
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        pid = next(p["project_id"] for p in r.json() if p["code"] == "VIS-101")
        r2 = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(tokens["site_engineer"]["token"]),
            json=_sample_mrf_payload(pid, "BLR"),
            timeout=30,
        )
        assert r2.status_code == 200
        mrf = r2.json()
        rs = requests.post(
            f"{BASE_URL}/api/mrf/{mrf['mrf_id']}/submit",
            headers=_h(tokens["site_engineer"]["token"]),
            timeout=30,
        )
        assert rs.status_code == 200
        return mrf

    def test_seeded_pm_can_approve(self, tokens, submitted_mrf):
        r = requests.post(
            f"{BASE_URL}/api/mrf/{submitted_mrf['mrf_id']}/approve",
            headers=_h(tokens["project_manager"]["token"]),
            json={"action": "approve", "comment": "ok"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    def test_fresh_pm_forbidden(self, tokens, fresh_users):
        # Create + submit new MRF for approval attempt
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        pid = next(p["project_id"] for p in r.json() if p["code"] == "VIS-103")
        r2 = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(tokens["site_engineer"]["token"]),
            json=_sample_mrf_payload(pid),
            timeout=30,
        )
        mrf = r2.json()
        requests.post(
            f"{BASE_URL}/api/mrf/{mrf['mrf_id']}/submit",
            headers=_h(tokens["site_engineer"]["token"]),
            timeout=30,
        )
        # Fresh PM is not assigned to VIS-103
        r3 = requests.post(
            f"{BASE_URL}/api/mrf/{mrf['mrf_id']}/approve",
            headers=_h(fresh_users["project_manager"]["token"]),
            json={"action": "approve"},
            timeout=30,
        )
        assert r3.status_code == 403, f"expected 403, got {r3.status_code}: {r3.text}"


# =====================================================
# GET /api/mrf filter for PM
# =====================================================
class TestMRFListPMFilter:
    def test_pm_lists_only_assigned(self, tokens, fresh_users):
        # Seeded PM: should see MRFs from VIS-101/102/103 (all assigned)
        r = requests.get(f"{BASE_URL}/api/mrf", headers=_h(tokens["project_manager"]["token"]), timeout=30)
        assert r.status_code == 200
        docs = r.json()
        # All returned MRFs must be on projects where seeded PM is assigned
        rp = requests.get(f"{BASE_URL}/api/projects?all=1", headers=_h(tokens["admin"]["token"]), timeout=30)
        assigned_pids = {
            p["project_id"] for p in rp.json()
            if tokens["project_manager"]["user"]["user_id"] in (p.get("project_managers") or [])
        }
        for d in docs:
            assert d["project_id"] in assigned_pids

    def test_fresh_pm_lists_only_assigned_projects(self, tokens, fresh_users):
        # fresh PM was assigned to VIS-101 earlier by TestProjectTeamUpdate.
        # PM MUST see only MRFs from projects where they are a PM.
        r = requests.get(
            f"{BASE_URL}/api/mrf",
            headers=_h(fresh_users["project_manager"]["token"]),
            timeout=30,
        )
        assert r.status_code == 200
        docs = r.json()
        rp = requests.get(f"{BASE_URL}/api/projects?all=1",
                          headers=_h(tokens["admin"]["token"]), timeout=30)
        fresh_pm_uid = fresh_users["project_manager"]["user"]["user_id"]
        allowed_pids = {
            p["project_id"] for p in rp.json()
            if fresh_pm_uid in (p.get("project_managers") or [])
        }
        # Every MRF returned must belong to a project the fresh PM is on
        for d in docs:
            assert d["project_id"] in allowed_pids, (
                f"MRF {d['mrf_id']} leaked project {d['project_id']} not in {allowed_pids}"
            )


# =====================================================
# Regression — prior features still work
# =====================================================
class TestRegression:
    def test_purchase_can_create_po_from_approved_mrf(self, tokens):
        # Create + submit + approve on VIS-101
        rprj = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        pid = next(p["project_id"] for p in rprj.json() if p["code"] == "VIS-101")
        r = requests.post(
            f"{BASE_URL}/api/mrf",
            headers=_h(tokens["site_engineer"]["token"]),
            json=_sample_mrf_payload(pid, "BLR-Regr"),
            timeout=30,
        )
        mrf = r.json()
        requests.post(f"{BASE_URL}/api/mrf/{mrf['mrf_id']}/submit",
                      headers=_h(tokens["site_engineer"]["token"]), timeout=30)
        ra = requests.post(
            f"{BASE_URL}/api/mrf/{mrf['mrf_id']}/approve",
            headers=_h(tokens["project_manager"]["token"]),
            json={"action": "approve"},
            timeout=30,
        )
        assert ra.status_code == 200
        # Vendor
        rv = requests.get(f"{BASE_URL}/api/vendors", headers=_h(tokens["purchase"]["token"]), timeout=30)
        vendor_id = rv.json()[0]["vendor_id"]
        item_line_id = mrf["items"][0]["item_line_id"]
        po_payload = {
            "vendor_id": vendor_id,
            "project_id": pid,
            "delivery_site": "BLR",
            "items": [{
                "mrf_id": mrf["mrf_id"],
                "item_line_id": item_line_id,
                "description": mrf["items"][0]["description"],
                "unit": "Nos",
                "qty": 5,
                "rate": 100,
                "discount": 0,
                "gst": 18,
            }],
        }
        rp = requests.post(f"{BASE_URL}/api/po", headers=_h(tokens["purchase"]["token"]),
                           json=po_payload, timeout=30)
        assert rp.status_code == 200, rp.text
        assert rp.json()["po_number"].startswith("PO/")
        assert rp.json()["total"] > 0

    def test_billing_update_still_works(self, tokens):
        # Find a billing item
        r = requests.get(f"{BASE_URL}/api/billing/items", headers=_h(tokens["billing"]["token"]), timeout=30)
        assert r.status_code == 200
        items = r.json()
        if not items:
            pytest.skip("no billing items yet")
        it = items[0]
        rb = requests.post(
            f"{BASE_URL}/api/billing/update",
            headers=_h(tokens["billing"]["token"]),
            json={"mrf_id": it["mrf_id"], "item_line_id": it["item_line_id"],
                  "qty_billed": 0, "billing_remarks": "TEST_regr"},
            timeout=30,
        )
        assert rb.status_code == 200

    def test_admin_passthrough_projects(self, tokens):
        r = requests.get(f"{BASE_URL}/api/projects", headers=_h(tokens["admin"]["token"]), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_dashboard_ok(self, tokens):
        r = requests.get(f"{BASE_URL}/api/reports/dashboard", headers=_h(tokens["admin"]["token"]), timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "total_mrf" in data and "total_po" in data
