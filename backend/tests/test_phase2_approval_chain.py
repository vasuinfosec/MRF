"""Phase 2 — Site Engineer + PO Threshold Approval Chain regression suite.

Covers the full review request:
- Strict operational chain: Site Engineer -> PM -> Purchase -> GM -> Director
- PO threshold approval (settings/thresholds + POST /po/{id}/approve)
- GRN blocked while PO is pending approval / rejected
- Role visibility for MRFs, POs, Projects
- Cross-role denials
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_BACKEND_URL",
    os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001"),
).rstrip("/")
API = f"{BASE_URL}/api"

DEFAULT_GM = 50000.0
DEFAULT_DIRECTOR = 500000.0


# ---------------- helpers ----------------
def dev_login(email, role, name=None):
    return requests.post(
        f"{API}/auth/dev-login",
        json={"email": email, "role": role, "name": name or email.split("@")[0]},
        timeout=15,
    )


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def tokens():
    """Login all six canonical roles + admin. Site-engineer is first-class."""
    r = dev_login("admin@vasu.dev", "admin", "Admin")
    assert r.status_code == 200, r.text
    admin_tok = r.json()["session_token"]
    # Idempotent seed
    seed = requests.post(f"{API}/seed", headers=h(admin_tok), timeout=30)
    assert seed.status_code == 200, seed.text

    # Reset thresholds to defaults so tests are deterministic
    reset = requests.put(
        f"{API}/settings/thresholds",
        headers=h(admin_tok),
        json={"gm": DEFAULT_GM, "director": DEFAULT_DIRECTOR},
    )
    assert reset.status_code == 200, reset.text

    out = {"admin": admin_tok}
    for role, email in [
        ("director", "director@vasu.dev"),
        ("gm", "gm@vasu.dev"),
        ("pm", "pm@vasu.dev"),
        ("purchase", "purchase@vasu.dev"),
        ("site_engineer", "siteeng@vasu.dev"),
    ]:
        r = dev_login(email, role)
        assert r.status_code == 200, f"{role} login failed: {r.text}"
        assert r.json()["user"]["role"] == role, (
            f"{role} came back as {r.json()['user']['role']}"
        )
        out[role] = r.json()["session_token"]
    return out


@pytest.fixture(scope="module")
def project(tokens):
    """VIS-101 with siteeng@vasu.dev present as site_engineer."""
    rp = requests.get(f"{API}/projects?all=true", headers=h(tokens["admin"]))
    assert rp.status_code == 200, rp.text
    proj = next(p for p in rp.json() if p["code"] == "VIS-101")

    # Ensure site engineer user is in project.site_engineers (seed appends but
    # keep the assertion explicit).
    ru = requests.get(f"{API}/users", headers=h(tokens["admin"]))
    se_user = next(u for u in ru.json() if u["email"] == "siteeng@vasu.dev")
    if se_user["user_id"] not in (proj.get("site_engineers") or []):
        r = requests.post(
            f"{API}/projects/{proj['project_id']}/team",
            headers=h(tokens["admin"]),
            json={
                "site_engineers": list(
                    set((proj.get("site_engineers") or []) + [se_user["user_id"]])
                )
            },
        )
        assert r.status_code == 200, r.text
        proj = r.json()
    proj["_se_user_id"] = se_user["user_id"]
    return proj


@pytest.fixture(scope="module")
def vendor(tokens):
    rv = requests.get(f"{API}/vendors", headers=h(tokens["admin"]))
    assert rv.status_code == 200 and rv.json(), "no vendors seeded"
    return rv.json()[0]


# ---------------- helpers to make MRFs / POs ----------------
def _make_mrf_body(project_id, site, desc="TEST_SmokeDetector", qty=10):
    return {
        "project_id": project_id,
        "site": site,
        "required_by": "2026-06-01",
        "requesting_person": "TEST_Requester",
        "system_category": "Fire Alarm",
        "items": [{"description": desc, "unit": "Nos", "qty_requested": qty,
                   "billable": True}],
        "remarks": "TEST_phase2",
    }


def _po_body(project_id, site, vendor_id, mrf, qty, rate):
    return {
        "vendor_id": vendor_id,
        "project_id": project_id,
        "delivery_site": site,
        "items": [{
            "mrf_id": mrf["mrf_id"],
            "item_line_id": mrf["items"][0]["item_line_id"],
            "description": mrf["items"][0]["description"],
            "unit": "Nos",
            "qty": qty,
            "rate": rate,
            "discount": 0,
            "gst": 0,   # keep math simple: total = qty*rate + freight/other
            "remarks": "",
        }],
        "freight": 0,
        "other_charges": 0,
    }


# ======================================================================
#  E2E happy path (steps 1..14 of the review request)
# ======================================================================
class TestFullE2E:
    @pytest.fixture(scope="class")
    def ctx(self, tokens, project, vendor):
        return {"tokens": tokens, "project": project, "vendor": vendor,
                "mrf": None, "small_po": None, "mid_po": None, "large_po": None}

    # 2 — Site Engineer creates MRF
    def test_02_site_engineer_creates_mrf(self, ctx):
        body = _make_mrf_body(ctx["project"]["project_id"], ctx["project"]["site"])
        r = requests.post(f"{API}/mrf", headers=h(ctx["tokens"]["site_engineer"]),
                          json=body)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"
        assert r.json()["created_by"] == ctx["project"]["_se_user_id"]
        ctx["mrf"] = r.json()

    # 3 — Site Engineer submits MRF
    def test_03_site_engineer_submits_mrf(self, ctx):
        mid = ctx["mrf"]["mrf_id"]
        r = requests.post(f"{API}/mrf/{mid}/submit",
                          headers=h(ctx["tokens"]["site_engineer"]))
        assert r.status_code == 200, r.text
        get_r = requests.get(f"{API}/mrf/{mid}",
                             headers=h(ctx["tokens"]["admin"]))
        assert get_r.json()["status"] == "pm_review"

    # 4 — Site Engineer approves MRF -> 403
    def test_04_site_engineer_cannot_approve(self, ctx):
        mid = ctx["mrf"]["mrf_id"]
        r = requests.post(
            f"{API}/mrf/{mid}/approve",
            headers=h(ctx["tokens"]["site_engineer"]),
            json={"action": "approve", "comment": "TEST"},
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    # 5 — PM approves MRF
    def test_05_pm_approves_mrf(self, ctx):
        mid = ctx["mrf"]["mrf_id"]
        r = requests.post(
            f"{API}/mrf/{mid}/approve",
            headers=h(ctx["tokens"]["pm"]),
            json={"action": "approve", "comment": "TEST_ok"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    # 6 — Purchase creates small PO (auto-issued)
    def test_06_purchase_small_po_issued(self, ctx):
        # 10 units * 1000 = 10000  <= 50000 -> issued
        body = _po_body(ctx["project"]["project_id"], ctx["project"]["site"],
                        ctx["vendor"]["vendor_id"], ctx["mrf"], qty=10, rate=1000)
        r = requests.post(f"{API}/po", headers=h(ctx["tokens"]["purchase"]),
                          json=body)
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "issued", f"got {po['status']}, total={po['total']}"
        assert po["total"] == 10000.0
        ctx["small_po"] = po
        # MRF qty_ordered updated
        m = requests.get(f"{API}/mrf/{ctx['mrf']['mrf_id']}",
                         headers=h(ctx["tokens"]["admin"])).json()
        assert float(m["items"][0]["qty_ordered"]) == 10.0

    # 7 — mid PO (needs GM) — MRF qty_ordered NOT updated
    def test_07_mid_po_pending_gm(self, ctx):
        # Need a fresh approved MRF because prior one is fully_ordered
        b = _make_mrf_body(ctx["project"]["project_id"], ctx["project"]["site"],
                           desc="TEST_MidItem", qty=5)
        rm = requests.post(f"{API}/mrf", headers=h(ctx["tokens"]["site_engineer"]),
                           json=b)
        mrf_mid = rm.json()
        requests.post(f"{API}/mrf/{mrf_mid['mrf_id']}/submit",
                      headers=h(ctx["tokens"]["site_engineer"]))
        ap = requests.post(f"{API}/mrf/{mrf_mid['mrf_id']}/approve",
                           headers=h(ctx["tokens"]["pm"]),
                           json={"action": "approve"})
        assert ap.status_code == 200, ap.text

        # 5 * 20000 = 100000 (50k < 100k <= 500k) -> pending_gm_approval
        body = _po_body(ctx["project"]["project_id"], ctx["project"]["site"],
                        ctx["vendor"]["vendor_id"], mrf_mid, qty=5, rate=20000)
        r = requests.post(f"{API}/po", headers=h(ctx["tokens"]["purchase"]),
                          json=body)
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "pending_gm_approval", po
        assert po["total"] == 100000.0
        # MRF qty_ordered NOT yet updated
        m2 = requests.get(f"{API}/mrf/{mrf_mid['mrf_id']}",
                          headers=h(ctx["tokens"]["admin"])).json()
        assert float(m2["items"][0]["qty_ordered"]) == 0.0, (
            f"qty_ordered should be 0 while pending; got "
            f"{m2['items'][0]['qty_ordered']}"
        )
        ctx["mid_po"] = po
        ctx["mid_mrf"] = mrf_mid

    # 8 — Site Engineer tries to receive mid PO before approval -> 400
    def test_08_grn_blocked_while_pending(self, ctx):
        po_id = ctx["mid_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/received",
                          headers=h(ctx["tokens"]["site_engineer"]),
                          json={})
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    # 9 — GM approves mid PO -> issued, MRF qty_ordered updated
    def test_09_gm_approves_mid_po(self, ctx):
        po_id = ctx["mid_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/approve",
                          headers=h(ctx["tokens"]["gm"]),
                          json={"action": "approve", "comment": "ok"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "issued"
        m3 = requests.get(f"{API}/mrf/{ctx['mid_mrf']['mrf_id']}",
                          headers=h(ctx["tokens"]["admin"])).json()
        assert float(m3["items"][0]["qty_ordered"]) == 5.0

    # 10 — Purchase creates large PO -> pending_director_approval
    def test_10_large_po_pending_director(self, ctx):
        b = _make_mrf_body(ctx["project"]["project_id"], ctx["project"]["site"],
                           desc="TEST_LargeItem", qty=10)
        rm = requests.post(f"{API}/mrf", headers=h(ctx["tokens"]["site_engineer"]),
                           json=b)
        mrf_l = rm.json()
        requests.post(f"{API}/mrf/{mrf_l['mrf_id']}/submit",
                      headers=h(ctx["tokens"]["site_engineer"]))
        requests.post(f"{API}/mrf/{mrf_l['mrf_id']}/approve",
                      headers=h(ctx["tokens"]["pm"]),
                      json={"action": "approve"})
        # 10 * 100000 = 1_000_000 > 500_000 -> pending_director_approval
        body = _po_body(ctx["project"]["project_id"], ctx["project"]["site"],
                        ctx["vendor"]["vendor_id"], mrf_l, qty=10, rate=100000)
        r = requests.post(f"{API}/po", headers=h(ctx["tokens"]["purchase"]),
                          json=body)
        assert r.status_code == 200, r.text
        po = r.json()
        assert po["status"] == "pending_director_approval", po
        assert po["total"] == 1_000_000.0
        ctx["large_po"] = po
        ctx["large_mrf"] = mrf_l

    # 11 — GM tries to approve large PO -> 403
    def test_11_gm_cannot_approve_director_po(self, ctx):
        po_id = ctx["large_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/approve",
                          headers=h(ctx["tokens"]["gm"]),
                          json={"action": "approve"})
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    # 12 — Director approves large PO
    def test_12_director_approves_large_po(self, ctx):
        po_id = ctx["large_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/approve",
                          headers=h(ctx["tokens"]["director"]),
                          json={"action": "approve"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "issued"

    # 13 — Site Engineer records GRN on issued PO
    def test_13_site_engineer_records_grn(self, ctx):
        # Use the small PO (issued, MRF was created by SE)
        po_id = ctx["small_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/received",
                          headers=h(ctx["tokens"]["site_engineer"]),
                          json={})
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        assert r.json().get("grn_number"), "GRN should be created"

    # 14 — Purchase records GRN
    def test_14_purchase_records_grn(self, ctx):
        po_id = ctx["mid_po"]["po_id"]
        r = requests.post(f"{API}/po/{po_id}/received",
                          headers=h(ctx["tokens"]["purchase"]),
                          json={})
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"


# ======================================================================
#  Thresholds settings (15..19)
# ======================================================================
class TestThresholds:
    def test_15_site_engineer_cannot_put(self, tokens):
        r = requests.put(f"{API}/settings/thresholds",
                         headers=h(tokens["site_engineer"]),
                         json={"gm": 60000, "director": 600000})
        assert r.status_code == 403, r.text

    def test_16_admin_put_ok(self, tokens):
        r = requests.put(f"{API}/settings/thresholds",
                         headers=h(tokens["admin"]),
                         json={"gm": 60000, "director": 600000})
        assert r.status_code == 200, r.text
        assert r.json()["gm"] == 60000
        assert r.json()["director"] == 600000

    def test_17_director_put_ok(self, tokens):
        r = requests.put(f"{API}/settings/thresholds",
                         headers=h(tokens["director"]),
                         json={"gm": 70000, "director": 700000})
        assert r.status_code == 200, r.text
        # restore defaults for downstream tests
        rr = requests.put(f"{API}/settings/thresholds",
                          headers=h(tokens["admin"]),
                          json={"gm": DEFAULT_GM, "director": DEFAULT_DIRECTOR})
        assert rr.status_code == 200

    def test_18_director_less_than_gm_rejected(self, tokens):
        r = requests.put(f"{API}/settings/thresholds",
                         headers=h(tokens["director"]),
                         json={"gm": 100000, "director": 50000})
        assert r.status_code == 400, r.text

    @pytest.mark.parametrize("role",
                             ["site_engineer", "pm", "purchase", "gm",
                              "director", "admin"])
    def test_19_any_authed_get_thresholds(self, tokens, role):
        r = requests.get(f"{API}/settings/thresholds", headers=h(tokens[role]))
        assert r.status_code == 200, r.text
        j = r.json()
        assert "gm" in j and "director" in j


# ======================================================================
#  Role visibility (20..26)
# ======================================================================
class TestVisibility:
    def test_20_site_engineer_lists_own_mrfs_only(self, tokens):
        r = requests.get(f"{API}/mrf", headers=h(tokens["site_engineer"]))
        assert r.status_code == 200
        mrfs = r.json()
        # figure out own user_id
        me = requests.get(f"{API}/auth/me",
                          headers=h(tokens["site_engineer"])).json()
        assert mrfs, "SE should have MRFs from the E2E flow"
        assert all(m["created_by"] == me["user_id"] for m in mrfs)

    def test_21_pm_lists_only_managed_mrfs(self, tokens):
        me = requests.get(f"{API}/auth/me", headers=h(tokens["pm"])).json()
        # projects PM manages
        pr = requests.get(f"{API}/projects", headers=h(tokens["pm"]))
        assert pr.status_code == 200
        managed = {p["project_id"] for p in pr.json()}
        # PM's MRFs
        r = requests.get(f"{API}/mrf", headers=h(tokens["pm"]))
        assert r.status_code == 200
        assert all(m["project_id"] in managed for m in r.json())
        assert managed  # not empty

    @pytest.mark.parametrize("role", ["purchase", "gm", "director", "admin"])
    def test_22_privileged_roles_see_all_mrfs(self, tokens, role):
        r_priv = requests.get(f"{API}/mrf", headers=h(tokens[role]))
        r_admin = requests.get(f"{API}/mrf", headers=h(tokens["admin"]))
        assert r_priv.status_code == 200 and r_admin.status_code == 200
        assert len(r_priv.json()) == len(r_admin.json()), (
            f"{role} sees {len(r_priv.json())} vs admin {len(r_admin.json())}"
        )

    def test_23_site_engineer_lists_own_pos_only(self, tokens):
        r = requests.get(f"{API}/po", headers=h(tokens["site_engineer"]))
        assert r.status_code == 200
        pos = r.json()
        # own mrfs
        my_mrfs = requests.get(f"{API}/mrf",
                               headers=h(tokens["site_engineer"])).json()
        my_ids = {m["mrf_id"] for m in my_mrfs}
        assert pos, "SE should see POs from own MRFs after E2E"
        for p in pos:
            assert my_ids.intersection(p.get("mrf_refs") or []), (
                f"PO {p['po_number']} has no MRF from SE"
            )

    def test_24_pm_lists_pos_managed_projects_only(self, tokens):
        pr = requests.get(f"{API}/projects", headers=h(tokens["pm"]))
        managed = {p["project_id"] for p in pr.json()}
        r = requests.get(f"{API}/po", headers=h(tokens["pm"]))
        assert r.status_code == 200
        assert all(p["project_id"] in managed for p in r.json())

    @pytest.mark.parametrize("role", ["purchase", "gm", "director", "admin"])
    def test_25_privileged_roles_see_all_pos(self, tokens, role):
        r_priv = requests.get(f"{API}/po", headers=h(tokens[role]))
        r_admin = requests.get(f"{API}/po", headers=h(tokens["admin"]))
        assert r_priv.status_code == 200 and r_admin.status_code == 200
        assert len(r_priv.json()) == len(r_admin.json())

    def test_26_site_engineer_projects_scoped(self, tokens):
        r = requests.get(f"{API}/projects", headers=h(tokens["site_engineer"]))
        assert r.status_code == 200
        me = requests.get(f"{API}/auth/me",
                          headers=h(tokens["site_engineer"])).json()
        for p in r.json():
            assigned_top = me["user_id"] in (p.get("site_engineers") or [])
            assigned_sub = any(
                me["user_id"] in (s.get("site_engineers") or [])
                for s in (p.get("sites") or []) if s.get("active", True)
            )
            assert assigned_top or assigned_sub, (
                f"SE sees unassigned project {p['code']}"
            )


# ======================================================================
#  Cross-role denials (27..30)
# ======================================================================
class TestCrossRoleDenials:
    @pytest.fixture(scope="class")
    def mrf_id(self, tokens, project):
        """Approved MRF PM/site-engineer can use for negative POST /po test."""
        b = _make_mrf_body(project["project_id"], project["site"],
                           desc="TEST_DenyItem")
        rm = requests.post(f"{API}/mrf",
                           headers=h(tokens["site_engineer"]), json=b)
        assert rm.status_code == 200
        mid = rm.json()["mrf_id"]
        requests.post(f"{API}/mrf/{mid}/submit",
                      headers=h(tokens["site_engineer"]))
        requests.post(f"{API}/mrf/{mid}/approve",
                      headers=h(tokens["pm"]),
                      json={"action": "approve"})
        return rm.json()

    def _po_payload(self, project, vendor, mrf):
        return _po_body(project["project_id"], project["site"],
                        vendor["vendor_id"], mrf, qty=1, rate=100)

    def test_27_site_engineer_cannot_post_po(self, tokens, project, vendor,
                                             mrf_id):
        r = requests.post(
            f"{API}/po", headers=h(tokens["site_engineer"]),
            json=self._po_payload(project, vendor, mrf_id),
        )
        assert r.status_code == 403, r.text

    def test_28_pm_cannot_post_po(self, tokens, project, vendor, mrf_id):
        r = requests.post(
            f"{API}/po", headers=h(tokens["pm"]),
            json=self._po_payload(project, vendor, mrf_id),
        )
        assert r.status_code == 403, r.text

    def test_29_purchase_cannot_approve_mrf(self, tokens, mrf_id):
        # need a submitted MRF; mrf_id is already approved -> the approve
        # endpoint would still check role first (role 403 before status check).
        r = requests.post(f"{API}/mrf/{mrf_id['mrf_id']}/approve",
                          headers=h(tokens["purchase"]),
                          json={"action": "approve"})
        assert r.status_code == 403, r.text

    def test_30_site_engineer_cannot_put_vendor(self, tokens, vendor):
        r = requests.put(f"{API}/vendors/{vendor['vendor_id']}",
                         headers=h(tokens["site_engineer"]),
                         json={"contact": "9999999999"})
        assert r.status_code == 403, r.text
