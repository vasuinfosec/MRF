#!/usr/bin/env python3
"""Run Task 3A.2 local tests and write JSON/Markdown evidence."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "backend/tests/test_task3a2_access_security.py"
REPORT_DIR = ROOT / "test_reports"
REPORT_DIR.mkdir(exist_ok=True)

env = os.environ.copy()
env.update({
    "MONGO_URL": "mongodb://127.0.0.1:27017",
    "DB_NAME": "mrf_task3a2_local_tests",
    "ACCESS_SECURITY_V2": "1",
})
proc = subprocess.run(
    [sys.executable, "-u", str(TEST)],
    cwd=ROOT,
    env=env,
    text=True,
    capture_output=True,
)
output = (proc.stdout or "") + (proc.stderr or "")
matches = re.findall(r"^(test_\S+) .* \.\.\. (ok|FAIL|ERROR)$", output, re.MULTILINE)
tests = [
    {"name": name, "status": "passed" if status == "ok" else "failed"}
    for name, status in matches
]
passed = sum(t["status"] == "passed" for t in tests)
failed = len(tests) - passed
stamp = datetime.now(timezone.utc).isoformat()
report = {
    "task": "3A.2",
    "scope": "local code/staging only",
    "production_contacted": False,
    "task_3b_started": False,
    "generated_at_utc": stamp,
    "command": f"{sys.executable} -u {TEST.relative_to(ROOT)}",
    "exit_code": proc.returncode,
    "summary": {"total": len(tests), "passed": passed, "failed": failed},
    "coverage": [
        "Director protection",
        "Last active Director deactivation prevention",
        "Last active Director role-removal prevention",
        "Self-deactivation prevention",
        "Admin Director restrictions",
        "roles[] authority and secondary roles",
        "inactive Director denial",
        "self-elevation prevention",
        "role-free inactive-user listing",
        "/users/role closed in V2",
        "ACCESS_SECURITY_V2=0 compatibility",
    ],
    "tests": tests,
    "raw_output": output,
}

json_path = REPORT_DIR / "task3a2_test_report.json"
md_path = REPORT_DIR / "task3a2_test_report.md"
json_path.write_text(json.dumps(report, indent=2) + "\n")

rows = "\n".join(
    f"| `{t['name']}` | {t['status'].upper()} |" for t in tests
)
md_path.write_text(
    f"""# Task 3A.2 Test Report

- Scope: local code/staging only
- Generated: {stamp}
- Result: **{passed} passed, {failed} failed**
- Production contacted: **No**
- Task 3B started: **No**

## Security coverage

{chr(10).join(f"- {item}" for item in report["coverage"])}

## Test results

| Test | Status |
|---|---|
{rows}

## Runner

`{report["command"]}`
"""
)
print(json.dumps({
    "exit_code": proc.returncode,
    "passed": passed,
    "failed": failed,
    "json": str(json_path),
    "markdown": str(md_path),
}, indent=2))
raise SystemExit(proc.returncode)
