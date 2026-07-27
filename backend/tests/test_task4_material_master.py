"""Task 4 Material Master/UOM local integration and security tests."""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "mrf_task4_local_tests")
os.environ.setdefault("ACCESS_SECURITY_V2", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The hosted LLM integration is unrelated to Material Master testing.
emergent = ModuleType("emergentintegrations")
emergent_llm = ModuleType("emergentintegrations.llm")
emergent_chat = ModuleType("emergentintegrations.llm.chat")
emergent_chat.LlmChat = type("LlmChat", (), {})
emergent_chat.UserMessage = type("UserMessage", (), {})
sys.modules.setdefault("emergentintegrations", emergent)
sys.modules.setdefault("emergentintegrations.llm", emergent_llm)
sys.modules.setdefault("emergentintegrations.llm.chat", emergent_chat)

server = importlib.import_module("server")
task4 = importlib.import_module("routers.material_master")
masters = importlib.import_module("routers.masters")


def run(awaitable):
    return asyncio.run(awaitable)


def user(uid="admin", role="admin", roles=None, active=True):
    return server.UserOut(
        user_id=uid,
        email=f"{uid}@example.test",
        name=uid,
        role=role,
        roles=[role] if roles is None else roles,
        is_active=active,
    )


def matches(row, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(row, clause) for clause in expected):
                return False
            continue
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$exists" in expected and (key in row) != bool(expected["$exists"]):
                return False
            if "$regex" in expected:
                import re
                flags = re.I if expected.get("$options") == "i" else 0
                if not re.search(expected["$regex"], str(actual or ""), flags):
                    return False
        elif actual != expected:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    async def to_list(self, limit):
        return [dict(row) for row in self.rows[:limit]]


class Collection:
    def __init__(self, rows=()):
        self.rows = [dict(row) for row in rows]
        self.updates = []
        self.inserts = []

    async def find_one(self, query, *_args):
        return next((dict(row) for row in self.rows if matches(row, query)), None)

    def find(self, query=None, *_args):
        query = query or {}
        return Cursor([row for row in self.rows if matches(row, query)])

    async def insert_one(self, document):
        row = dict(document)
        self.rows.append(row)
        self.inserts.append(row)
        return SimpleNamespace(inserted_id=len(self.rows))

    async def update_one(self, query, update, upsert=False):
        original = next((row for row in self.rows if matches(row, query)), None)
        if original is None and upsert:
            original = {
                key: value for key, value in query.items()
                if not isinstance(value, dict)
            }
            self.rows.append(original)
        if original is not None:
            original.update(update.get("$set", {}))
        self.updates.append((query, update, upsert))
        return SimpleNamespace(
            matched_count=1 if original is not None else 0,
            modified_count=1 if original is not None else 0,
        )


def assert_http(testcase, status, call, detail=""):
    with testcase.assertRaises(HTTPException) as caught:
        call()
    testcase.assertEqual(caught.exception.status_code, status)
    if detail:
        testcase.assertIn(detail, str(caught.exception.detail))


class Task4MaterialMasterTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {"ACCESS_SECURITY_V2": "1"})
        self.flag.start()
        self.actor = user("task4-admin", "pm", ["pm", "admin"])
        self.categories = Collection([{
            "category_id": "mcat-electrical",
            "name": "Electrical",
            "name_norm": "electrical",
            "active": True,
        }])
        self.uoms = Collection([{
            "uom_id": "uom-nos",
            "name": "Nos",
            "name_norm": "nos",
            "code": "nos",
            "code_norm": "nos",
            "conversion_quantity": 1.0,
            "base_uom_id": "",
            "active": True,
        }])
        self.materials = Collection()
        self.settings = Collection([{
            "_id": "task4",
            "low_value_threshold_inr": 100.0,
        }])
        self.db = SimpleNamespace(
            material_categories=self.categories,
            uoms=self.uoms,
            materials=self.materials,
            material_settings=self.settings,
        )
        self.variants = []
        self.audit_events = []

        async def current(_authorization):
            return self.actor

        async def sequence(_name):
            return 42

        async def ensure_variant(material_uid, make, model, _actor_id):
            self.variants.append((material_uid, make, model))

        async def audit(*args):
            self.audit_events.append(args)

        self.patches = [
            patch.object(task4, "db", self.db),
            patch.object(task4, "get_current_user", current),
            patch.object(task4, "_next_seq", sequence),
            patch.object(task4, "_ensure_variant", ensure_variant),
            patch.object(task4, "master_audit", audit),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.flag.stop()

    def body(self, **overrides):
        values = {
            "category_id": "mcat-electrical",
            "item": "Cable tie",
            "specification": "200 mm black",
            "description": "UV resistant cable tie",
            "make": "Acme",
            "model": "CT200",
            "uom_id": "uom-nos",
            "unit_value": 25,
            "is_consumable": True,
            "force_traceable": False,
            "amc_material": False,
            "billing_option": "either",
        }
        values.update(overrides)
        return values

    def test_secondary_admin_role_is_authorised_and_stale_scalar_is_denied(self):
        run(task4.get_material_settings("Bearer local"))
        self.actor = user("stale", "admin", ["purchase"])
        assert_http(
            self, 403,
            lambda: run(task4.get_material_settings("Bearer local")),
            "active Admin",
        )

    def test_inactive_admin_is_denied(self):
        self.actor = user("inactive", "admin", ["admin"], active=False)
        assert_http(
            self, 403,
            lambda: run(task4.list_material_categories("Bearer local")),
        )

    def test_normalized_category_duplicate_is_blocked(self):
        assert_http(
            self, 400,
            lambda: run(task4.create_material_category(
                {"name": "  ELECTRICAL  "}, "Bearer local"
            )),
            "already exists",
        )

    def test_box_and_lot_require_positive_conversion_and_base_uom(self):
        for code, quantity, base in [
            ("box", 0, "uom-nos"),
            ("lot", -1, "uom-nos"),
            ("box", 12, ""),
            ("box", float("nan"), "uom-nos"),
            ("box", float("inf"), "uom-nos"),
        ]:
            with self.subTest(code=code, quantity=quantity, base=base):
                assert_http(
                    self, 400,
                    lambda c=code, q=quantity, b=base: run(task4.create_uom({
                        "name": c.title(),
                        "code": c,
                        "conversion_quantity": q,
                        "base_uom_id": b,
                    }, "Bearer local")),
                )

    def test_base_uom_cannot_be_deactivated_while_packaging_conversion_is_active(self):
        self.uoms.rows.append({
            "uom_id": "uom-box",
            "name": "Box",
            "name_norm": "box",
            "code": "box",
            "code_norm": "box",
            "conversion_quantity": 10.0,
            "base_uom_id": "uom-nos",
            "active": True,
        })
        assert_http(
            self, 400,
            lambda: run(task4.set_uom_status(
                "uom-nos", {"active": False}, "Bearer local"
            )),
            "active box/lot conversion",
        )

    def test_valid_box_conversion_is_persisted(self):
        result = run(task4.create_uom({
            "name": "Box",
            "code": "box",
            "conversion_quantity": 50,
            "base_uom_id": "uom-nos",
        }, "Bearer local"))
        self.assertEqual(result["conversion_quantity"], 50)
        self.assertEqual(result["base_uom_id"], "uom-nos")
        self.assertTrue(result["approved"])

    def test_description_is_limited_to_one_hundred_words(self):
        assert_http(
            self, 400,
            lambda: run(task4.create_admin_material(
                self.body(description=" ".join(["word"] * 101)),
                "Bearer local",
            )),
            "100 words",
        )

    def test_normalized_composite_duplicate_is_blocked(self):
        key = task4._material_key(
            "mcat-electrical", "cable tie", "200 mm black", "acme", "ct200"
        )
        self.materials.rows.append({
            "material_uid": "MAT-0001",
            "material_key": key,
        })
        assert_http(
            self, 400,
            lambda: run(task4.create_admin_material(self.body(
                item="  CABLE   TIE ",
                specification="200 MM BLACK",
                make="ACME",
                model="ct200",
            ), "Bearer local")),
            "MAT-0001",
        )

    def test_material_creation_generates_uid_and_preserves_mrf_contract(self):
        result = run(task4.create_admin_material(
            self.body(amc_material=True, billing_option="not_billed"),
            "Bearer local",
        ))
        self.assertEqual(result["material_uid"], "MAT-0042")
        self.assertEqual(result["category"], "Electrical")
        self.assertEqual(result["unit"], "Nos")
        self.assertEqual(result["status"], "approved")
        self.assertTrue(result["active"])
        self.assertTrue(result["amc_material"])
        self.assertEqual(result["billing_option"], "not_billed")
        self.assertEqual(self.variants, [("MAT-0042", "Acme", "CT200")])

    def test_low_value_consumable_needs_no_reconciliation(self):
        result = run(task4.create_admin_material(self.body(unit_value=99.99), "Bearer local"))
        self.assertEqual(result["classification"], "low_value_consumable")
        self.assertFalse(result["reconciliation_required"])

    def test_fasteners_remain_traceable_below_threshold(self):
        result = run(task4.create_admin_material(self.body(
            item="Stainless steel fastener",
            specification="M4",
            description="Fastener for equipment rack",
            make="",
            model="",
            unit_value=2,
        ), "Bearer local"))
        self.assertTrue(result["fastener_protected"])
        self.assertTrue(result["reconciliation_required"])
        self.assertEqual(result["classification"], "traceable")

    def test_high_value_and_force_traceable_materials_are_reconciled(self):
        high = task4._classification(
            threshold=100,
            category="General",
            item="Cleaning liquid",
            specification="5 litre",
            description="Consumable",
            unit_value=100,
            is_consumable=True,
            force_traceable=False,
        )
        forced = task4._classification(
            threshold=100,
            category="General",
            item="Cleaning liquid",
            specification="1 litre",
            description="Consumable",
            unit_value=10,
            is_consumable=True,
            force_traceable=True,
        )
        self.assertTrue(high["reconciliation_required"])
        self.assertTrue(forced["reconciliation_required"])

    def test_admin_can_edit_threshold_only_with_positive_value_and_reason(self):
        assert_http(
            self, 400,
            lambda: run(task4.update_material_settings(
                {"low_value_threshold_inr": 0, "reason": "invalid"},
                "Bearer local",
            )),
            "greater than zero",
        )
        assert_http(
            self, 400,
            lambda: run(task4.update_material_settings(
                {"low_value_threshold_inr": 125}, "Bearer local"
            )),
            "Reason",
        )
        result = run(task4.update_material_settings({
            "low_value_threshold_inr": 125,
            "reason": "Approved policy revision",
        }, "Bearer local"))
        self.assertEqual(result["low_value_threshold_inr"], 125)
        self.assertEqual(self.settings.rows[0]["low_value_threshold_inr"], 125)

    def test_deactivation_retains_historical_material_record(self):
        self.materials.rows.append({
            "material_uid": "MAT-0099",
            "description": "Used historical material",
            "active": True,
        })
        result = run(task4.set_material_status(
            "MAT-0099",
            {"active": False, "reason": "No longer purchased"},
            "Bearer local",
        ))
        self.assertFalse(result["active"])
        self.assertTrue(result["historical_records_retained"])
        self.assertEqual(len(self.materials.rows), 1)
        self.assertFalse(self.materials.rows[0]["active"])

    def test_task4_registers_no_delete_endpoints(self):
        task4_routes = [
            route for route in server.api.routes
            if getattr(route, "path", "").startswith("/api/admin/material-master")
        ]
        self.assertTrue(task4_routes)
        self.assertTrue(all("DELETE" not in route.methods for route in task4_routes))

    def test_mrf_picker_hides_deactivated_and_keeps_legacy_active_rows(self):
        material_rows = Collection([
            {
                "material_uid": "MAT-LEGACY",
                "description": "Legacy genuine record",
                "unit": "Nos",
                "status": "approved",
            },
            {
                "material_uid": "MAT-INACTIVE",
                "description": "Retained inactive record",
                "unit": "Nos",
                "status": "approved",
                "active": False,
            },
        ])

        async def current(_authorization):
            return self.actor

        with (
            patch.object(masters, "db", SimpleNamespace(materials=material_rows)),
            patch.object(masters, "get_current_user", current),
        ):
            result = run(masters.list_materials(
                status="approved", authorization="Bearer local"
            ))
        self.assertEqual([row["material_uid"] for row in result], ["MAT-LEGACY"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
