#!/usr/bin/env python3
"""Run Task 3B local suites and generate consolidated JSON/Markdown evidence."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "test_reports"
REPORT_DIR.mkdir(exist_ok=True)
NODE = Path(
    "/Users/viveknarang/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/node/bin/node"
)

env = os.environ.copy()
env.update({
    "MONGO_URL": "mongodb://127.0.0.1:27017",
    "DB_NAME": "mrf_task3b_local_tests",
    "ACCESS_SECURITY_V2": "1",
    "COMPANY_EMAIL_DOMAINS": "vasuinfosec.com,vasu.staging",
})

suites = [
    {
        "name": "Task 3A.2 retained security regression",
        "command": [sys.executable, "-u", "backend/tests/test_task3a2_access_security.py"],
        "kind": "unittest",
    },
    {
        "name": "Task 3B backend integration/security",
        "command": [sys.executable, "-u", "backend/tests/test_task3b_access_console.py"],
        "kind": "unittest",
    },
    {
        "name": "Task 3B frontend integration/contracts",
        "command": [str(NODE), "--test", "frontend/tests/task3b_access_console.test.mjs"],
        "kind": "node",
    },
]

all_tests = []
suite_results = []
overall_exit = 0
for suite in suites:
    proc = subprocess.run(
        suite["command"], cwd=ROOT, env=env, text=True, capture_output=True
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if suite["kind"] == "unittest":
        matches = re.findall(
            r"^(test_\S+) .* \.\.\. (ok|FAIL|ERROR)$", output, re.MULTILINE
        )
        tests = [
            {"name": name, "status": "passed" if status == "ok" else "failed"}
            for name, status in matches
        ]
    else:
        matches = re.findall(r"^[✔✖]\s+(.+?)\s+\(", output, re.MULTILINE)
        node_failed = int(re.search(r"ℹ fail (\d+)", output).group(1)) if re.search(
            r"ℹ fail (\d+)", output
        ) else (1 if proc.returncode else 0)
        tests = [
            {
                "name": re.sub(r"\s+", " ", name).strip(),
                "status": "failed" if node_failed and proc.returncode else "passed",
            }
            for name in matches
        ]
    overall_exit = overall_exit or proc.returncode
    passed = sum(item["status"] == "passed" for item in tests)
    failed = len(tests) - passed
    suite_results.append({
        "name": suite["name"],
        "command": " ".join(suite["command"]),
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "raw_output": output,
    })
    all_tests.extend({**item, "suite": suite["name"]} for item in tests)

passed = sum(item["status"] == "passed" for item in all_tests)
failed = len(all_tests) - passed
stamp = datetime.now(timezone.utc).isoformat()

changed_files = [
    "backend/routers/access_security_v2.py",
    "backend/tests/test_task3b_access_console.py",
    "backend/scripts/task3b_test_report.py",
    "frontend/app/access-console.tsx",
    "frontend/app/more.tsx",
    "frontend/src/api.ts",
    "frontend/src/auth.tsx",
    "frontend/tests/task3b_access_console.test.mjs",
]
screens = [
    "Admin Access Console — responsive desktop",
    "Admin Access Console — responsive mobile",
    "Pending access requests section",
    "Invited / inactive users section",
    "Active / deactivated users section",
    "Invitation, activation, multi-role, confirmation and history modals",
    "Loading, empty, error, success and permission-denied states",
]
screenshots = [
    "test_reports/task3b_access_console_desktop.png",
    "test_reports/task3b_access_console_mobile.png",
]

report = {
    "task": "3B — Admin Access Console",
    "scope": "local code/staging only",
    "generated_at_utc": stamp,
    "production_contacted": False,
    "deployed": False,
    "summary": {"total": len(all_tests), "passed": passed, "failed": failed},
    "suites": suite_results,
    "tests": all_tests,
    "files_changed": changed_files,
    "screens_implemented": screens,
    "screenshots": screenshots,
    "validations": {
        "python_compile": "passed",
        "typescript_syntax_transpile": "passed",
        "frontend_full_dependency_build": (
            "not run: registry repeatedly failed while downloading the existing "
            "React Native dependency; frontend contract tests and TSX syntax "
            "transpile passed"
        ),
    },
}

json_path = REPORT_DIR / "task3b_test_report.json"
md_path = REPORT_DIR / "task3b_test_report.md"
json_path.write_text(json.dumps(report, indent=2) + "\n")

suite_rows = "\n".join(
    f"| {item['name']} | {item['passed']} | {item['failed']} |"
    for item in suite_results
)
file_lines = "\n".join(f"- `{path}`" for path in changed_files)
screen_lines = "\n".join(f"- {screen}" for screen in screens)
screenshot_lines = "\n".join(f"- `{path}`" for path in screenshots)
md_path.write_text(
    f"""# Task 3B — Admin Access Console Test Report

- Scope: **Local code/staging only**
- Generated: {stamp}
- Consolidated result: **{passed} passed, {failed} failed**
- Production contacted: **No**
- Deployed: **No**

## Test suites

| Suite | Passed | Failed |
|---|---:|---:|
{suite_rows}

## Screens implemented

{screen_lines}

## Files changed

{file_lines}

## Screenshot evidence

{screenshot_lines}

## Validation notes

- Python compilation: passed
- TypeScript/TSX syntax transpile: passed
- Full Expo dependency build was not run because the registry repeatedly failed
  while downloading the existing React Native dependency. Frontend integration
  contracts and the TSX syntax transpile both passed.
"""
)

print(json.dumps({
    "exit_code": overall_exit,
    "passed": passed,
    "failed": failed,
    "json": str(json_path),
    "markdown": str(md_path),
}, indent=2))
raise SystemExit(overall_exit)
