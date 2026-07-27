"""Task 3A.2 authorization regression tests (local/staging only)."""
import asyncio
import importlib
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "mrf_task3a2_local_tests")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The optional hosted-LLM SDK is unrelated to authorization and is not needed
# in the local test environment. Stub only its import surface.
emergent = ModuleType("emergentintegrations")
emergent_llm = ModuleType("emergentintegrations.llm")
emergent_chat = ModuleType("emergentintegrations.llm.chat")
emergent_chat.LlmChat = type("LlmChat", (), {})
emergent_chat.UserMessage = type("UserMessage", (), {})
sys.modules.setdefault("emergentintegrations", emergent)
sys.modules.setdefault("emergentintegrations.llm", emergent_llm)
sys.modules.setdefault("emergentintegrations.llm.chat", emergent_chat)

server = importlib.import_module("server")
auth = importlib.import_module("routers.auth")
access = importlib.import_module("routers.access_security_v2")


def run(awaitable):
    return asyncio.run(awaitable)


def user(uid, role, roles=None, active=True):
    return server.UserOut(
        user_id=uid,
        email=f"{uid}@example.test",
        name=uid,
        role=role,
        roles=[role] if roles is None else roles,
        is_active=active,
    )


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    async def to_list(self, _limit):
        return [dict(row) for row in self.rows]


class Collection:
    def __init__(self, rows=(), count_result=1):
        self.rows = [dict(row) for row in rows]
        self.count_result = count_result
        self.updates = []

    async def find_one(self, query, *_args):
        return next(
            (dict(row) for row in self.rows
             if all(row.get(k) == v for k, v in query.items())),
            None,
        )

    def find(self, *_args):
        return Cursor(self.rows)

    async def update_one(self, query, update):
        row = await self.find_one(query)
        if row:
            for original in self.rows:
                if original.get("user_id") == row.get("user_id"):
                    original.update(update.get("$set", {}))
        self.updates.append((query, update))
        return SimpleNamespace(matched_count=1 if row else 0)

    async def delete_many(self, *_args):
        return SimpleNamespace(deleted_count=0)

    async def count_documents(self, *_args):
        return self.count_result


def assert_http(status, call):
    try:
        call()
    except HTTPException as exc:
        if exc.status_code != status:
            raise AssertionError(f"expected HTTP {status}, got {exc.status_code}") from exc
        return
    raise AssertionError(f"expected HTTP {status}")


def capture_http(status, call):
    try:
        call()
    except HTTPException as exc:
        if exc.status_code != status:
            raise AssertionError(f"expected HTTP {status}, got {exc.status_code}") from exc
        return exc
    raise AssertionError(f"expected HTTP {status}")


class Task3A2SecurityTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {"ACCESS_SECURITY_V2": "1"})
        self.flag.start()

    def tearDown(self):
        self.flag.stop()

    def test_roles_array_is_authoritative_and_secondary_roles_work(self):
        actor = user("mixed", "pm", ["pm", "director"])
        self.assertEqual(server.permission_roles(actor), {"pm", "director"})
        access._requires_mgmt(actor)
        stale_scalar = user("stale", "director", ["pm"])
        self.assertEqual(server.permission_roles(stale_scalar), {"pm"})
        assert_http(403, lambda: access._requires_mgmt(stale_scalar))

    def test_inactive_director_cannot_manage_directors(self):
        inactive = user("inactive", "director", ["director"], active=False)
        assert_http(403, lambda: access._requires_mgmt(inactive))

    def test_admin_can_never_create_assign_or_modify_director(self):
        admin = user("admin", "admin", ["admin"])
        cases = [
            ({"director"}, {"pm"}),
            ({"pm"}, {"director"}),
            ({"director"}, {"director", "pm"}),
        ]
        for old_roles, new_roles in cases:
            with self.subTest(old=old_roles, new=new_roles):
                assert_http(
                    403,
                    lambda: access._requires_director_for_director_change(
                        admin, old_roles=old_roles, new_roles=new_roles
                    ),
                )

    def test_admin_cannot_create_director_invitation_endpoint(self):
        actor = user("admin", "admin", ["admin"])

        async def current(_authorization):
            return actor

        with patch.object(access, "get_current_user", current):
            assert_http(
                403,
                lambda: run(access.create_invitation(
                    access.InvitationIn(
                        email="new-director@example.com", role="director"
                    ),
                    "Bearer test",
                )),
            )

    def test_admin_cannot_assign_director_on_activation_endpoint(self):
        actor = user("admin", "admin", ["admin"])
        users = Collection([{
            "user_id": "target", "email": "target@example.test",
            "name": "Target", "role": "", "roles": [], "is_active": False,
        }])

        async def current(_authorization):
            return actor

        with (
            patch.object(access, "get_current_user", current),
            patch.object(access, "db", SimpleNamespace(users=users)),
        ):
            assert_http(
                403,
                lambda: run(access.activate_user(
                    "target", access.ActivateIn(role="director"), "Bearer test"
                )),
            )
        self.assertEqual(users.updates, [])

    def test_active_director_may_manage_another_director(self):
        director = user("director-a", "pm", ["pm", "director"])
        access._requires_mgmt(director)
        access._requires_director_for_director_change(
            director, old_roles={"director"}, new_roles={"director", "pm"}
        )

    def test_self_elevation_is_rejected(self):
        actor = user("same", "director", ["director"])

        async def current(_authorization):
            return actor

        with patch.object(access, "get_current_user", current):
            assert_http(
                400,
                lambda: run(access.set_user_roles(
                    "same", access.RolesIn(roles=["director", "admin"]),
                    "Bearer test",
                )),
            )

    def test_admin_cannot_deactivate_director(self):
        actor = user("admin", "admin", ["admin"])
        users = Collection([{
            "user_id": "target", "email": "d@example.test", "name": "Director",
            "role": "director", "roles": ["director"], "is_active": True,
        }])

        async def current(_authorization):
            return actor

        with (
            patch.object(access, "get_current_user", current),
            patch.object(access, "db", SimpleNamespace(users=users)),
        ):
            assert_http(
                403,
                lambda: run(access.deactivate_user(
                    "target", "blocked", "Bearer test"
                )),
            )
        self.assertEqual(users.updates, [])

    def test_last_active_director_cannot_be_deactivated(self):
        actor = user("operator", "director", ["director"])
        users = Collection([{
            "user_id": "last-director", "email": "last@example.test",
            "name": "Last Director", "role": "director",
            "roles": ["director"], "is_active": True,
        }], count_result=0)

        async def current(_authorization):
            return actor

        with (
            patch.object(access, "get_current_user", current),
            patch.object(access, "db", SimpleNamespace(users=users)),
        ):
            exc = capture_http(
                400,
                lambda: run(access.deactivate_user(
                    "last-director", "must remain active", "Bearer test"
                )),
            )
        self.assertIn("last_director_protected", str(exc.detail))
        self.assertEqual(users.updates, [])

    def test_director_role_cannot_be_removed_from_last_active_director(self):
        actor = user("operator", "director", ["director"])
        users = Collection([{
            "user_id": "last-director", "email": "last@example.test",
            "name": "Last Director", "role": "director",
            "roles": ["director"], "is_active": True,
        }], count_result=0)

        async def current(_authorization):
            return actor

        with (
            patch.object(access, "get_current_user", current),
            patch.object(access, "db", SimpleNamespace(users=users)),
        ):
            exc = capture_http(
                400,
                lambda: run(access.set_user_roles(
                    "last-director", access.RolesIn(roles=["pm"]),
                    "Bearer test",
                )),
            )
        self.assertIn("last_director_protected", str(exc.detail))
        self.assertEqual(users.updates, [])

    def test_self_deactivation_is_blocked(self):
        actor = user("same-director", "director", ["director"])

        async def current(_authorization):
            return actor

        with patch.object(access, "get_current_user", current):
            exc = capture_http(
                400,
                lambda: run(access.deactivate_user(
                    "same-director", "self request", "Bearer test"
                )),
            )
        self.assertIn("Cannot deactivate yourself", str(exc.detail))

    def test_role_free_inactive_users_list_without_validation_error(self):
        actor = user("admin", "admin", ["admin"])
        users = Collection([{
            "user_id": "pending", "email": "pending@example.test",
            "name": "Pending", "role": None, "roles": [], "is_active": False,
        }])

        async def current(_authorization):
            return actor

        with (
            patch.object(auth, "get_current_user", current),
            patch.object(auth, "db", SimpleNamespace(users=users)),
        ):
            listed = run(auth.list_users("Bearer test"))
        self.assertEqual(listed[0].role, "")
        self.assertEqual(listed[0].roles, [])
        self.assertFalse(listed[0].is_active)

    def test_legacy_users_role_is_closed_in_v2(self):
        async def must_not_auth(_authorization):
            raise AssertionError("V2 bypass checked after authentication")

        with patch.object(auth, "get_current_user", must_not_auth):
            assert_http(
                404,
                lambda: run(auth.set_role(
                    server.RoleUpdate(user_id="target", role="director"),
                    "Bearer test",
                )),
            )

    def test_v2_off_preserves_legacy_role_endpoint(self):
        actor = user("admin", "admin", ["pm"])
        users = Collection([{
            "user_id": "target", "email": "target@example.test",
            "name": "Target", "role": "pm", "roles": ["pm"],
            "is_active": True,
        }])

        async def current(_authorization):
            return actor

        with (
            patch.dict(os.environ, {"ACCESS_SECURITY_V2": "0"}),
            patch.object(auth, "get_current_user", current),
            patch.object(auth, "db", SimpleNamespace(users=users)),
        ):
            changed = run(auth.set_role(
                server.RoleUpdate(user_id="target", role="director"),
                "Bearer legacy",
            ))
            self.assertEqual(server.permission_roles(actor), {"admin"})
        self.assertEqual(changed.role, "director")
        self.assertEqual(changed.roles, ["director"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
