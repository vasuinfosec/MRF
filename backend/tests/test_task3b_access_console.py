"""Task 3B backend integration/security tests (local/staging only)."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "mrf_task3b_local_tests")
sys.path.insert(0, os.path.dirname(__file__))

from test_task3a2_access_security import access, assert_http, capture_http, user


def run(awaitable):
    return asyncio.run(awaitable)


def matches(row, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(row, part) for part in expected):
                return False
            continue
        if key == "$and":
            if not all(matches(row, part) for part in expected):
                return False
            continue
        value = row
        exists = True
        for part in key.split("."):
            if isinstance(value, list) and part.isdigit():
                index = int(part)
                exists = index < len(value)
                value = value[index] if exists else None
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                exists = False
                value = None
                break
        if isinstance(expected, dict):
            if "$exists" in expected and exists != expected["$exists"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$nin" in expected and value in expected["$nin"]:
                return False
            continue
        if isinstance(value, list) and not isinstance(expected, list):
            if expected not in value:
                return False
        elif value != expected:
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
    def __init__(self, rows=(), deleted_count=None):
        self.rows = [dict(row) for row in rows]
        self.deleted_count = deleted_count
        self.updates = []
        self.deleted_queries = []

    async def find_one(self, query, *_args):
        return next((dict(row) for row in self.rows if matches(row, query)), None)

    def find(self, query, *_args):
        return Cursor([row for row in self.rows if matches(row, query)])

    async def update_one(self, query, update):
        matched = 0
        for row in self.rows:
            if matches(row, query):
                row.update(update.get("$set", {}))
                matched += 1
                break
        self.updates.append((query, update))
        return SimpleNamespace(matched_count=matched)

    async def delete_many(self, query):
        self.deleted_queries.append(query)
        if self.deleted_count is not None:
            count = self.deleted_count
        else:
            count = sum(matches(row, query) for row in self.rows)
        return SimpleNamespace(deleted_count=count)


class Task3BBackendTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {
            "ACCESS_SECURITY_V2": "1",
            "COMPANY_EMAIL_DOMAINS": "vasuinfosec.com,vasu.staging",
        })
        self.flag.start()
        self.actor = user("manager", "admin", ["admin"])
        self.audit_events = []

        async def current(_authorization):
            return self.actor

        async def record_audit(entity, entity_id, action, actor, details=None):
            self.audit_events.append({
                "entity": entity, "entity_id": entity_id,
                "action": action, "actor": actor.user_id,
                "details": details or {},
            })

        self.current_patch = patch.object(access, "get_current_user", current)
        self.audit_patch = patch.object(access, "audit", record_audit)
        self.current_patch.start()
        self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.current_patch.stop()
        self.flag.stop()

    def test_reject_pending_request_updates_state_and_audit(self):
        pending = Collection([{
            "request_id": "req-1", "email": "person@vasuinfosec.com",
            "name": "Person", "attempt_count": 2,
        }])
        with patch.object(
            access, "db", SimpleNamespace(pending_access_requests=pending)
        ):
            result = run(access.reject_pending_request(
                "req-1", access.RejectRequestIn(reason="Not approved"),
                "Bearer test",
            ))
        self.assertTrue(result["rejected"])
        self.assertTrue(pending.rows[0]["rejected"])
        self.assertEqual(self.audit_events[0]["action"], "reject")

    def test_access_user_list_normalizes_legacy_roles(self):
        users = Collection([
            {
                "user_id": "legacy", "email": "legacy@vasuinfosec.com",
                "name": "Legacy", "role": "pm", "is_active": True,
            },
            {
                "user_id": "inactive", "email": "inactive@vasuinfosec.com",
                "name": "Inactive", "role": "purchase", "roles": ["purchase"],
                "is_active": False,
            },
        ])
        with patch.object(access, "db", SimpleNamespace(users=users)):
            result = run(access.list_access_users("Bearer test"))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["roles"], ["pm"])
        self.assertFalse(result[1]["is_active"])

    def test_session_revocation_returns_deleted_count_and_audits(self):
        users = Collection([{
            "user_id": "target", "email": "target@vasuinfosec.com",
            "name": "Target", "role": "pm", "roles": ["pm"],
            "is_active": True,
        }])
        sessions = Collection(deleted_count=3)
        with patch.object(
            access, "db", SimpleNamespace(users=users, user_sessions=sessions)
        ):
            result = run(access.revoke_user_sessions("target", "Bearer test"))
        self.assertEqual(result["revoked_sessions"], 3)
        self.assertEqual(sessions.deleted_queries, [{"user_id": "target"}])
        self.assertEqual(self.audit_events[0]["action"], "sessions_revoked")

    def test_admin_cannot_revoke_director_sessions(self):
        users = Collection([{
            "user_id": "director", "email": "director@vasuinfosec.com",
            "name": "Director", "role": "director", "roles": ["director"],
            "is_active": True,
        }])
        sessions = Collection(deleted_count=2)
        with patch.object(
            access, "db", SimpleNamespace(users=users, user_sessions=sessions)
        ):
            assert_http(
                403,
                lambda: run(access.revoke_user_sessions("director", "Bearer test")),
            )
        self.assertEqual(sessions.deleted_queries, [])

    def test_active_director_can_revoke_other_director_sessions(self):
        self.actor = user("manager", "director", ["director"])
        users = Collection([{
            "user_id": "director", "email": "director@vasuinfosec.com",
            "name": "Director", "role": "director", "roles": ["director"],
            "is_active": True,
        }])
        sessions = Collection(deleted_count=1)
        with patch.object(
            access, "db", SimpleNamespace(users=users, user_sessions=sessions)
        ):
            result = run(access.revoke_user_sessions("director", "Bearer test"))
        self.assertEqual(result["revoked_sessions"], 1)

    def test_access_history_returns_target_and_audit_rows(self):
        users = Collection([{
            "user_id": "target", "email": "target@vasuinfosec.com",
            "name": "Target", "role": "pm", "roles": ["pm"],
            "is_active": True,
        }])
        audit_logs = Collection([{
            "audit_id": "aud-1", "entity": "user", "entity_id": "target",
            "action": "roles_set", "user_id": "manager",
        }])
        with patch.object(
            access, "db", SimpleNamespace(users=users, audit_logs=audit_logs)
        ):
            result = run(access.get_user_access_history("target", "Bearer test"))
        self.assertEqual(result["user"]["user_id"], "target")
        self.assertEqual(result["history"][0]["action"], "roles_set")

    def test_external_email_invitation_is_rejected(self):
        exc = capture_http(
            400,
            lambda: run(access.create_invitation(
                access.InvitationIn(email="person@gmail.com", role="pm"),
                "Bearer test",
            )),
        )
        self.assertIn("company email", str(exc.detail).lower())

    def test_v2_off_hides_console_endpoints(self):
        with patch.dict(os.environ, {"ACCESS_SECURITY_V2": "0"}):
            assert_http(
                404,
                lambda: run(access.list_access_users("Bearer legacy")),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
