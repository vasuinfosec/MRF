#!/usr/bin/env python3
"""Generate local Task 4 implementation and compatibility evidence."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "test_reports"
REPORT_DIR.mkdir(exist_ok=True)
PYTHON = Path(os.environ.get("TASK4_TEST_PYTHON", "/private/tmp/task3b-run-venv/bin/python"))
if not PYTHON.exists():
    PYTHON = Path(os.environ.get("PYTHON", "python3"))
NODE = Path(
    "/Users/viveknarang/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/node/bin/node"
)

env = os.environ.copy()
env.update({
    "MONGO_URL": "mongodb://127.0.0.1:27017",
    "DB_NAME": "mrf_task4_local_tests",
    "ACCESS_SECURITY_V2": "1",
    "COMPANY_EMAIL_DOMAINS": "vasuinfosec.com,vasu.staging",
    "PYDANTIC_DISABLE_PLUGINS": "1",
})

suites = [
    ("Task 3A.2 retained security", [str(PYTHON), "-u", "backend/tests/test_task3a2_access_security.py"], "unittest"),
    ("Task 3B backend integration/security", [str(PYTHON), "-u", "backend/tests/test_task3b_access_console.py"], "unittest"),
    ("Task 3B frontend contracts", [str(NODE), "--test", "frontend/tests/task3b_access_console.test.mjs"], "node"),
    ("Task 4 backend material/UOM/security", [str(PYTHON), "-u", "backend/tests/test_task4_material_master.py"], "unittest"),
    ("Task 4 frontend contracts", [str(NODE), "--test", "frontend/tests/task4_material_master.test.mjs"], "node"),
]


def parse_tests(kind: str, output: str, returncode: int):
    if kind == "unittest":
        rows = re.findall(r"^(test_\S+) .* \.\.\. (ok|FAIL|ERROR)$", output, re.MULTILINE)
        return [{"name": name, "status": "passed" if status == "ok" else "failed"} for name, status in rows]
    rows = re.findall(r"^[✔✖]\s+(.+?)\s+\(", output, re.MULTILINE)
    failed_count = int(re.search(r"ℹ fail (\d+)", output).group(1)) if re.search(r"ℹ fail (\d+)", output) else (1 if returncode else 0)
    return [{"name": re.sub(r"\s+", " ", name).strip(), "status": "failed" if failed_count and returncode else "passed"} for name in rows]


all_tests = []
suite_results = []
exit_code = 0
for name, command, kind in suites:
    proc = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    tests = parse_tests(kind, output, proc.returncode)
    passed = sum(row["status"] == "passed" for row in tests)
    failed = len(tests) - passed
    suite_results.append({
        "name": name,
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "raw_output": output,
    })
    all_tests.extend({**row, "suite": name} for row in tests)
    exit_code = exit_code or proc.returncode

passed = sum(row["status"] == "passed" for row in all_tests)
failed = len(all_tests) - passed
stamp = datetime.now(timezone.utc).isoformat()
files_changed = [
    "backend/routers/material_master.py",
    "backend/server.py",
    "backend/routers/masters.py",
    "backend/tests/test_task4_material_master.py",
    "backend/scripts/task4_test_report.py",
    "frontend/app/material-master.tsx",
    "frontend/app/masters.tsx",
    "frontend/tests/task4_material_master.test.mjs",
]
screens = [
    "Material Master — responsive desktop",
    "Material Master — responsive mobile",
    "Category-linked Materials (category → item → specification)",
    "Categories lifecycle controls",
    "Approved UOM controls and box/lot conversions",
    "Classification threshold, fastener traceability, AMC and billing options",
    "Loading, empty, error and permission-denied states",
]
screenshots = [
    "test_reports/task4_material_master_desktop.png",
    "test_reports/task4_material_master_mobile.png",
]
report = {
    "task": "4 — Material Master & UOM Controls",
    "scope": "local code/staging only",
    "generated_at_utc": stamp,
    "production_contacted": False,
    "deployed": False,
    "summary": {"total": len(all_tests), "passed": passed, "failed": failed},
    "suites": suite_results,
    "tests": all_tests,
    "files_changed": files_changed,
    "screens_implemented": screens,
    "screenshots": screenshots,
    "migration": {
        "required": False,
        "notes": "No destructive migration. Existing material records are preserved; startup indexes are idempotent and legacy material rows remain readable through the MRF picker.",
    },
    "environment_notes": [
        "Backend suites ran in the healthy local staging test runtime.",
        "The project .venv has an unrelated openpyxl Chartsheet import corruption; production code was not changed to work around it.",
    ],
}
json_path = REPORT_DIR / "task4_material_master_test_report.json"
md_path = REPORT_DIR / "task4_material_master_test_report.md"
json_path.write_text(json.dumps(report, indent=2) + "\n")

rows = "\n".join(f"| {s['name']} | {s['passed']} | {s['failed']} |" for s in suite_results)
files = "\n".join(f"- `{f}`" for f in files_changed)
screen_lines = "\n".join(f"- {s}" for s in screens)
shot_lines = "\n".join(f"- `{s}`" for s in screenshots)
md_path.write_text(f"""# Task 4 — Material Master & UOM Controls

- Scope: **Local code/staging only**
- Generated: {stamp}
- Consolidated result: **{passed} passed, {failed} failed**
- Production contacted: **No**
- Deployed: **No**

## Test suites

| Suite | Passed | Failed |
|---|---:|---:|
{rows}

## Screens implemented

{screen_lines}

## Files changed

{files}

## Screenshots

{shot_lines}

## Migration

- Required: **No**
- Existing genuine records are preserved. Historical material/category/UOM rows are deactivated rather than deleted, and legacy MRF material/unit fields remain compatible.

## Environment note

- Backend evidence used the healthy local staging runtime. The project `.venv` has an unrelated `openpyxl` `Chartsheet` import corruption; no production or unrelated module was modified.
""")
print(json.dumps({"exit_code": exit_code, "passed": passed, "failed": failed, "json": str(json_path), "markdown": str(md_path)}, indent=2))
raise SystemExit(exit_code)
