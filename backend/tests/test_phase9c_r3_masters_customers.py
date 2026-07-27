"""Phase 9C round 3 — Masters + Customers router extraction regression.

Validates the two newly-extracted routers (`masters.py`, `customers.py`)
behave byte-identically to their in-`server.py` predecessors.

Covers:
  P0 Masters:  /materials CRUD+workflow+bulk+import, /variants, /master-audit,
               /systems, /masters generic
  P0 Customers: /customers CRUD, /customer/{cid}/pos, attachment, cascade rename
  P1 Cross-router: POST /api/mrf with MAT-* material_id still validates
  P2 OpenAPI presence for 20+ paths
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid
from typing import Dict, Any, Optional

import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_BACKEND_URL")
        or os.environ.get("VASU_BASE_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


# --------------------------------------------------------------------------- helpers
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
    s.session_token = tok["session_token"]  # type: ignore[attr-defined]
    return s


@pytest.fixture(scope="module")
def sessions():
    admin = _sess("admin")
    admin.post(f"{API}/seed", timeout=30)
    roles = ["director", "gm", "pm", "purchase", "site_engineer", "store", "admin"]
    return {r: _sess(r) for r in roles}


def _uniq(prefix: str) -> str:
    return f"TEST_{prefix}_{uuid.uuid4().hex[:8]}"


# =========================================================================== P0 Masters — /materials
class TestMaterialsList:
    def test_default_returns_approved_only(self, sessions):
        r = sessions["admin"].get(f"{API}/materials", timeout=15)
        assert r.status_code == 200
        docs = r.json()
        assert isinstance(docs, list)
        for d in docs:
            assert d.get("status") == "approved", f"non-approved in default list: {d.get('material_uid')}={d.get('status')}"

    def test_status_all(self, sessions):
        r = sessions["admin"].get(f"{API}/materials", params={"status": "all"}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_status_pending_filter(self, sessions):
        r = sessions["admin"].get(f"{API}/materials", params={"status": "pending_pm_review"}, timeout=15)
        assert r.status_code == 200
        for d in r.json():
            assert d.get("status") == "pending_pm_review"

    def test_q_free_text(self, sessions):
        r = sessions["admin"].get(f"{API}/materials", params={"status": "all", "q": "MAT-"}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_counts_shape(self, sessions):
        r = sessions["admin"].get(f"{API}/materials/counts", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


class TestMaterialsCreateRBAC:
    def test_forbidden_roles(self, sessions):
        payload = {"description": _uniq("desc") + " Widget", "unit": "Nos"}
        for role in ("site_engineer", "pm", "gm", "store"):
            r = sessions[role].post(f"{API}/materials", json=payload, timeout=10)
            assert r.status_code == 403, f"{role}: expected 403 got {r.status_code}"

    def test_empty_description_400(self, sessions):
        r = sessions["purchase"].post(f"{API}/materials",
                                        json={"description": "  ", "unit": "Nos"},
                                        timeout=10)
        assert r.status_code == 400

    def test_word_limit_exceeded_400(self, sessions):
        long_desc = " ".join(["word"] * 150)
        r = sessions["purchase"].post(f"{API}/materials",
                                        json={"description": long_desc},
                                        timeout=10)
        assert r.status_code == 400

    def test_purchase_creates_pending_pm(self, sessions):
        desc = _uniq("mat") + " Sensor Photoelectric"
        r = sessions["purchase"].post(f"{API}/materials",
                                       json={"description": desc, "unit": "Nos", "gst_rate": 18},
                                       timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "pending_pm_review"
        assert d["material_uid"].startswith("MAT-")

    def test_duplicate_description_400(self, sessions):
        desc = _uniq("dup") + " Panel"
        r1 = sessions["purchase"].post(f"{API}/materials", json={"description": desc}, timeout=10)
        assert r1.status_code == 200, r1.text
        r2 = sessions["purchase"].post(f"{API}/materials",
                                        json={"description": desc.upper()}, timeout=10)
        assert r2.status_code == 400

    def test_admin_creates_approved(self, sessions):
        desc = _uniq("admin") + " Cable"
        r = sessions["admin"].post(f"{API}/materials",
                                     json={"description": desc, "unit": "Mtr"},
                                     timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"


class TestMaterialsUpdate:
    def _create(self, sessions, role="admin"):
        r = sessions[role].post(f"{API}/materials",
                                 json={"description": _uniq("upd") + " Item"},
                                 timeout=10)
        return r.json()

    def test_missing_reason_400(self, sessions):
        m = self._create(sessions, "admin")
        r = sessions["admin"].put(f"{API}/materials/{m['material_uid']}",
                                    json={"description": _uniq("new") + " Renamed"},
                                    timeout=10)
        assert r.status_code == 400

    def test_purchase_edit_approved_flips_to_gm(self, sessions):
        m = self._create(sessions, "admin")  # approved
        new_desc = _uniq("pchg") + " Renamed"
        r = sessions["purchase"].put(f"{API}/materials/{m['material_uid']}",
                                       json={"description": new_desc, "reason": "typo fix"},
                                       timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_gm_approval"

    def test_admin_edit_stays_approved(self, sessions):
        m = self._create(sessions, "admin")
        new_desc = _uniq("achg") + " Fixed"
        r = sessions["admin"].put(f"{API}/materials/{m['material_uid']}",
                                    json={"description": new_desc, "reason": "correction"},
                                    timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_dedup_on_rename(self, sessions):
        m1 = self._create(sessions, "admin")
        m2 = self._create(sessions, "admin")
        r = sessions["admin"].put(f"{API}/materials/{m2['material_uid']}",
                                    json={"description": m1["description"], "reason": "test"},
                                    timeout=10)
        assert r.status_code == 400


class TestMaterialsAction:
    def _create_pending(self, sessions):
        r = sessions["purchase"].post(f"{API}/materials",
                                        json={"description": _uniq("pmact") + " Widget"},
                                        timeout=10)
        return r.json()

    def test_pm_approve(self, sessions):
        m = self._create_pending(sessions)
        r = sessions["pm"].post(f"{API}/materials/{m['material_uid']}/action",
                                  json={"action": "approve", "reason": "ok"},
                                  timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_forbidden_roles(self, sessions):
        m = self._create_pending(sessions)
        for role in ("purchase", "gm"):
            r = sessions[role].post(f"{API}/materials/{m['material_uid']}/action",
                                      json={"action": "approve"}, timeout=10)
            assert r.status_code == 403

    def test_wrong_status_400(self, sessions):
        # Admin creates → approved directly, can't be PM-approved
        r0 = sessions["admin"].post(f"{API}/materials",
                                      json={"description": _uniq("appr") + " X"},
                                      timeout=10)
        uid = r0.json()["material_uid"]
        r = sessions["pm"].post(f"{API}/materials/{uid}/action",
                                  json={"action": "approve"}, timeout=10)
        assert r.status_code == 400


class TestMaterialsGMApprove:
    def test_gm_only(self, sessions):
        # Create → PM approve → Purchase edit → pending_gm_approval
        r0 = sessions["purchase"].post(f"{API}/materials",
                                         json={"description": _uniq("gm") + " Cable"},
                                         timeout=10)
        uid = r0.json()["material_uid"]
        sessions["pm"].post(f"{API}/materials/{uid}/action",
                              json={"action": "approve"}, timeout=10)
        sessions["purchase"].put(f"{API}/materials/{uid}",
                                   json={"description": _uniq("gmrn") + " Renamed",
                                         "reason": "test"}, timeout=10)
        # forbidden for purchase
        r_forbid = sessions["purchase"].post(f"{API}/materials/{uid}/gm-approve",
                                              json={"action": "approve"}, timeout=10)
        assert r_forbid.status_code == 403
        # gm approves
        r = sessions["gm"].post(f"{API}/materials/{uid}/gm-approve",
                                  json={"action": "approve", "reason": "ok"},
                                  timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_wrong_status_400(self, sessions):
        r0 = sessions["admin"].post(f"{API}/materials",
                                      json={"description": _uniq("gmerr") + " X"},
                                      timeout=10)
        uid = r0.json()["material_uid"]
        r = sessions["gm"].post(f"{API}/materials/{uid}/gm-approve",
                                  json={"action": "approve"}, timeout=10)
        assert r.status_code == 400


class TestMaterialsBulk:
    def test_bulk_action_pm(self, sessions):
        uids = []
        for _ in range(3):
            r = sessions["purchase"].post(f"{API}/materials",
                                            json={"description": _uniq("blk") + " N"},
                                            timeout=10)
            uids.append(r.json()["material_uid"])
        # add one bogus + one already-approved
        r_appr = sessions["admin"].post(f"{API}/materials",
                                          json={"description": _uniq("skip") + " Y"},
                                          timeout=10)
        skip_uid = r_appr.json()["material_uid"]
        r = sessions["pm"].post(f"{API}/materials/bulk-action",
                                  json={"action": "approve",
                                        "material_uids": uids + [skip_uid, "MAT-XXXX"],
                                        "reason": "bulk test"},
                                  timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] == 3
        assert body["skipped"] == 2


class TestMaterialsImport:
    def test_template_download(self, sessions):
        r = sessions["purchase"].get(f"{API}/import/materials/template", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml"
        )
        assert len(r.content) > 500  # xlsx bytes

    def test_template_token_query(self, sessions):
        # unauthenticated fetch using ?token=
        token = sessions["purchase"].session_token
        r = requests.get(f"{API}/import/materials/template",
                          params={"token": token}, timeout=15)
        assert r.status_code == 200

    def test_import_rows_mixed(self, sessions):
        rows = [
            {"Material Description": _uniq("imp") + " OK", "Unit": "Nos", "GST Rate %": 18},
            {"Material Description": ""},                                    # error
            {"Material Description": " ".join(["w"] * 150)},                 # needs_correction
        ]
        # duplicate: first take one existing
        existing = sessions["admin"].get(f"{API}/materials", timeout=15).json()
        if existing:
            rows.append({"Material Description": existing[0]["description"]})
        r = sessions["purchase"].post(f"{API}/import/materials",
                                        json={"rows": rows}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("created", "duplicates", "errors", "needs_correction", "summary"):
            assert k in body
        assert body["summary"]["created"] >= 1
        assert body["summary"]["errors"] >= 1
        assert body["summary"]["flagged_word_limit"] >= 1


class TestVariants:
    def test_dup_variant_returns_same(self, sessions):
        # find an approved material
        mats = sessions["admin"].get(f"{API}/materials", timeout=10).json()
        assert mats, "no approved materials seeded"
        uid = mats[0]["material_uid"]
        make = "TESTMAKE_" + uuid.uuid4().hex[:6]
        model = "TESTMODEL_" + uuid.uuid4().hex[:6]
        r1 = sessions["purchase"].post(f"{API}/variants",
                                         json={"material_uid": uid, "make": make, "model": model},
                                         timeout=10)
        assert r1.status_code == 200, r1.text
        r2 = sessions["purchase"].post(f"{API}/variants",
                                         json={"material_uid": uid, "make": make, "model": model},
                                         timeout=10)
        assert r2.status_code == 200
        assert r1.json().get("variant_uid") == r2.json().get("variant_uid")

    def test_list(self, sessions):
        r = sessions["admin"].get(f"{API}/variants", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestMasterAuditRBAC:
    def test_admin_ok(self, sessions):
        r = sessions["admin"].get(f"{API}/master-audit", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_others_forbidden(self, sessions):
        for role in ("pm", "purchase", "gm", "site_engineer", "store"):
            r = sessions[role].get(f"{API}/master-audit", timeout=10)
            assert r.status_code == 403, f"{role}: {r.status_code}"


class TestSystems:
    def test_returns_list(self, sessions):
        r = sessions["pm"].get(f"{API}/systems", timeout=10)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        assert len(arr) >= 5  # at least a handful of categories


class TestGenericMasters:
    def test_list_grouped(self, sessions):
        r = sessions["admin"].get(f"{API}/masters", timeout=10)
        assert r.status_code == 200
        j = r.json()
        assert "unit" in j and "brand" in j and "system" in j

    def test_create_forbidden_for_purchase(self, sessions):
        r = sessions["purchase"].post(f"{API}/masters",
                                        json={"item_id": _uniq("ms"), "category": "unit",
                                              "name": "TESTUNIT"},
                                        timeout=10)
        assert r.status_code == 403

    def test_create_update_soft_delete(self, sessions):
        iid = _uniq("ms")
        name = _uniq("nm")
        r = sessions["admin"].post(f"{API}/masters",
                                     json={"item_id": iid, "category": "unit", "name": name},
                                     timeout=10)
        assert r.status_code == 200, r.text
        # dup case-insensitive
        r_dup = sessions["admin"].post(f"{API}/masters",
                                         json={"item_id": _uniq("ms2"),
                                               "category": "unit", "name": name.upper()},
                                         timeout=10)
        assert r_dup.status_code == 400
        # update
        r_up = sessions["admin"].put(f"{API}/masters/{iid}",
                                       json={"name": name + "_v2", "reason": "rename"},
                                       timeout=10)
        assert r_up.status_code == 200
        # delete (soft)
        r_del = sessions["admin"].delete(f"{API}/masters/{iid}", timeout=10)
        assert r_del.status_code == 200
        assert r_del.json() == {"ok": True}

    def test_update_needs_reason(self, sessions):
        iid = _uniq("ms")
        sessions["admin"].post(f"{API}/masters",
                                 json={"item_id": iid, "category": "brand",
                                       "name": _uniq("br")}, timeout=10)
        r = sessions["admin"].put(f"{API}/masters/{iid}",
                                    json={"name": "X"}, timeout=10)
        assert r.status_code == 400


# =========================================================================== P0 Customers
class TestCustomersList:
    def test_list_default_active_only_with_po_count(self, sessions):
        r = sessions["admin"].get(f"{API}/customers", timeout=10)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        for c in arr:
            assert c.get("active", True) is True
            assert "po_count" in c

    def test_include_inactive(self, sessions):
        r = sessions["admin"].get(f"{API}/customers",
                                    params={"include_inactive": "true"}, timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestCustomersCRUD:
    @pytest.fixture(scope="class")
    def state(self):
        return {}

    def _new_cid(self):
        # customer_id validator generally requires uppercase-alphanumeric
        return "TESTC" + uuid.uuid4().hex[:5].upper()

    def test_create_forbidden(self, sessions):
        for role in ("pm", "purchase", "gm"):
            r = sessions[role].post(f"{API}/customers",
                                      json={"customer_id": self._new_cid(),
                                            "name": _uniq("cust")}, timeout=10)
            assert r.status_code == 403, f"{role}: {r.status_code}"

    def test_create_and_get(self, sessions, state):
        cid = self._new_cid()
        name = _uniq("cname")
        r = sessions["admin"].post(f"{API}/customers",
                                     json={"customer_id": cid, "name": name},
                                     timeout=10)
        assert r.status_code == 200, r.text
        state["cid"] = cid
        state["name"] = name
        # dup on id (case-insensitive)
        r_dup_id = sessions["admin"].post(f"{API}/customers",
                                            json={"customer_id": cid.lower(),
                                                  "name": _uniq("y")}, timeout=10)
        assert r_dup_id.status_code == 400
        # dup on name (case-insensitive)
        r_dup_name = sessions["admin"].post(f"{API}/customers",
                                              json={"customer_id": self._new_cid(),
                                                    "name": name.upper()}, timeout=10)
        assert r_dup_name.status_code == 400
        # GET
        g = sessions["admin"].get(f"{API}/customers/{cid}", timeout=10)
        assert g.status_code == 200
        body = g.json()
        assert body["customer_id"] == cid
        assert "customer_pos" in body

    def test_update_needs_reason(self, sessions, state):
        cid = state["cid"]
        r = sessions["admin"].put(f"{API}/customers/{cid}",
                                    json={"name": _uniq("upd")}, timeout=10)
        assert r.status_code == 400

    def test_add_customer_po_and_redact(self, sessions, state):
        cid = state["cid"]
        cpo_id = "cpo_" + uuid.uuid4().hex[:8]
        b64 = base64.b64encode(b"HELLO PDF" * 10).decode()
        r = sessions["admin"].post(f"{API}/customers/{cid}/pos",
                                     json={"cpo_id": cpo_id,
                                           "customer_id": cid,
                                           "po_number": "PO/TEST/001",
                                           "value": 100000,
                                           "attachment_name": "test.pdf",
                                           "attachment_b64": b64},
                                     timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "attachment_b64" not in d
        state["cpo_id"] = cpo_id
        # attachment endpoint returns raw
        att = sessions["admin"].get(f"{API}/customers/{cid}/pos/{cpo_id}/attachment", timeout=10)
        assert att.status_code == 200
        assert att.json()["content_b64"] == b64
        # GET customer should include po in list without attachment_b64
        g = sessions["admin"].get(f"{API}/customers/{cid}", timeout=10)
        pos = g.json().get("customer_pos", [])
        assert any(p["cpo_id"] == cpo_id for p in pos)
        for p in pos:
            assert "attachment_b64" not in p

    def test_update_customer_po_audit_redacts(self, sessions, state):
        cid = state["cid"]
        cpo_id = state["cpo_id"]
        r = sessions["admin"].put(f"{API}/customers/{cid}/pos/{cpo_id}",
                                    json={"po_number": "PO/TEST/002",
                                          "attachment_b64": base64.b64encode(b"NEW").decode(),
                                          "reason": "amend"},
                                    timeout=10)
        assert r.status_code == 200
        assert "attachment_b64" not in r.json()

    def test_attachment_404(self, sessions, state):
        cid = state["cid"]
        r = sessions["admin"].get(f"{API}/customers/{cid}/pos/cpo_missing/attachment",
                                    timeout=10)
        assert r.status_code == 404

    def test_cascade_rename(self, sessions, state):
        cid = state["cid"]
        new_cid = "TESTR" + uuid.uuid4().hex[:5].upper()
        r = sessions["admin"].put(f"{API}/customers/{cid}",
                                    json={"customer_id": new_cid,
                                          "reason": "rename cascade"},
                                    timeout=10)
        assert r.status_code == 200, r.text
        # old should 404
        g_old = sessions["admin"].get(f"{API}/customers/{cid}", timeout=10)
        assert g_old.status_code == 404
        # new should exist and still have the cpo attached
        g_new = sessions["admin"].get(f"{API}/customers/{new_cid}", timeout=10)
        assert g_new.status_code == 200
        pos = g_new.json().get("customer_pos", [])
        assert any(p["cpo_id"] == state["cpo_id"] for p in pos), \
            "Customer PO cascade update failed"
        state["cid"] = new_cid

    def test_soft_delete(self, sessions, state):
        cid = state["cid"]
        r = sessions["admin"].delete(f"{API}/customers/{cid}", timeout=10)
        assert r.status_code == 200
        # not in default list
        arr = sessions["admin"].get(f"{API}/customers", timeout=10).json()
        assert not any(c["customer_id"] == cid for c in arr)
        # is in include_inactive
        arr2 = sessions["admin"].get(f"{API}/customers",
                                       params={"include_inactive": "true"},
                                       timeout=10).json()
        assert any(c["customer_id"] == cid for c in arr2)


# =========================================================================== P1 Cross-router integration
class TestCrossRouterMRF:
    def test_mrf_resolves_material_from_masters_router(self, sessions):
        # Use MAT-0001 (seeded material) as material_id in an MRF
        # Need a real project first
        projects = sessions["admin"].get(f"{API}/projects", timeout=10).json()
        if not projects:
            pytest.skip("no projects seeded")
        pid = projects[0]["project_id"]
        payload = {
            "project_id": pid,
            "site": "TestSite",
            "priority": "medium",
            "required_by": "2026-12-31",
            "requesting_person": "Site Eng Test",
            "system_category": "Fire Alarm",
            "items": [{
                "material_id": "MAT-0001",
                "description": "Seeded material 1",
                "qty_requested": 2,
                "unit": "Nos",
            }],
        }
        r = sessions["admin"].post(f"{API}/mrf", json=payload, timeout=15)
        assert r.status_code in (200, 201), \
            f"MRF create failed (masters router resolution issue?): {r.status_code} {r.text[:400]}"


# =========================================================================== P2 OpenAPI presence
class TestOpenAPI:
    EXTRACTED = [
        ("/api/materials", "get"),
        ("/api/materials", "post"),
        ("/api/materials/counts", "get"),
        ("/api/materials/{material_uid}", "put"),
        ("/api/materials/{material_uid}/action", "post"),
        ("/api/materials/{material_uid}/gm-approve", "post"),
        ("/api/materials/bulk-action", "post"),
        ("/api/import/materials/template", "get"),
        ("/api/import/materials", "post"),
        ("/api/variants", "get"),
        ("/api/variants", "post"),
        ("/api/master-audit", "get"),
        ("/api/systems", "get"),
        ("/api/masters", "get"),
        ("/api/masters", "post"),
        ("/api/masters/{item_id}", "put"),
        ("/api/masters/{item_id}", "delete"),
        ("/api/customers", "get"),
        ("/api/customers", "post"),
        ("/api/customers/{customer_id}", "get"),
        ("/api/customers/{customer_id}", "put"),
        ("/api/customers/{customer_id}", "delete"),
        ("/api/customers/{customer_id}/pos", "post"),
        ("/api/customers/{customer_id}/pos/{cpo_id}", "put"),
        ("/api/customers/{customer_id}/pos/{cpo_id}/attachment", "get"),
    ]

    def test_all_extracted_paths_present(self):
        r = requests.get(f"{BASE}/openapi.json", timeout=15)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        missing = []
        for p, method in self.EXTRACTED:
            if p not in paths or method not in paths[p]:
                missing.append(f"{method.upper()} {p}")
        assert not missing, f"Missing from OpenAPI: {missing}"
