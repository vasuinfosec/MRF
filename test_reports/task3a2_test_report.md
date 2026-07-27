# Task 3A.2 Test Report

- Scope: local code/staging only
- Generated: 2026-07-23T10:11:55.171810+00:00
- Result: **14 passed, 0 failed**
- Production contacted: **No**
- Task 3B started: **No**

## Security coverage

- Director protection
- Last active Director deactivation prevention
- Last active Director role-removal prevention
- Self-deactivation prevention
- Admin Director restrictions
- roles[] authority and secondary roles
- inactive Director denial
- self-elevation prevention
- role-free inactive-user listing
- /users/role closed in V2
- ACCESS_SECURITY_V2=0 compatibility

## Test results

| Test | Status |
|---|---|
| `test_active_director_may_manage_another_director` | PASSED |
| `test_admin_can_never_create_assign_or_modify_director` | PASSED |
| `test_admin_cannot_assign_director_on_activation_endpoint` | PASSED |
| `test_admin_cannot_create_director_invitation_endpoint` | PASSED |
| `test_admin_cannot_deactivate_director` | PASSED |
| `test_director_role_cannot_be_removed_from_last_active_director` | PASSED |
| `test_inactive_director_cannot_manage_directors` | PASSED |
| `test_last_active_director_cannot_be_deactivated` | PASSED |
| `test_legacy_users_role_is_closed_in_v2` | PASSED |
| `test_role_free_inactive_users_list_without_validation_error` | PASSED |
| `test_roles_array_is_authoritative_and_secondary_roles_work` | PASSED |
| `test_self_deactivation_is_blocked` | PASSED |
| `test_self_elevation_is_rejected` | PASSED |
| `test_v2_off_preserves_legacy_role_endpoint` | PASSED |

## Runner

`/Users/viveknarang/Documents/MRF Project/.venv/bin/python -u backend/tests/test_task3a2_access_security.py`
