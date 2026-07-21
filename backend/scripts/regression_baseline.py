#!/usr/bin/env python3
"""T2.4 — Regression baseline against the ISOLATED staging DB.

Spawns a second FastAPI instance on port 8002 that talks to the STAGING Mongo,
then exercises the implemented flows through HTTP (login, MRFs, POs, GRNs, DCs,
CS, invoices, billing screen, reports, exports, audit, AI panels smoke).

Refuses to run if staging is not isolated. Kills the staging API on exit.

Usage:
  python3 /app/backend/scripts/regression_baseline.py
"""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from staging_guard import assert_staging_is_isolated, assert_target_is_not_prod  # type: ignore

STAGING_PORT = 8002
STAGING_BASE = f"http://127.0.0.1:{STAGING_PORT}"


def _die(msg, code=2):
    print(f"[regression] ABORT: {msg}", file=sys.stderr); sys.exit(code)


def main():
    stg_url, stg_db = assert_staging_is_isolated("regression_baseline")
    assert_target_is_not_prod(stg_url, stg_db, "regression_baseline")

    # Spawn a staging API. It reads MONGO_URL / DB_NAME from env.
    env = os.environ.copy()
    env["MONGO_URL"] = stg_url
    env["DB_NAME"] = stg_db
    env["ENABLE_DEV_LOGIN"] = "1"   # for QA fixtures — only on staging port
    log = open("/tmp/staging_api.log", "w")
    print(f"[regression] Spawning staging FastAPI on :{STAGING_PORT} against db='{stg_db}'…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(STAGING_PORT), "--log-level", "warning"],
        cwd="/app/backend", env=env, stdout=log, stderr=log,
    )
    try:
        import requests
        # Wait for start
        for _ in range(30):
            try:
                r = requests.get(f"{STAGING_BASE}/api/settings/thresholds", timeout=2)
                if r.status_code in (200, 401, 403):
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            _die("Staging API did not come up on :8002 (see /tmp/staging_api.log)")

        results = []
        def add(name, ok, extra=""):
            results.append({"test": name, "ok": bool(ok), "detail": extra})
            print(f"  {'✅' if ok else '❌'} {name}  {extra[:120]}")

        # 1) Login (dev-login on staging port is allowed by host guard — 127.0.0.1)
        d = requests.post(f"{STAGING_BASE}/api/auth/dev-login",
            json={"email": "qa-director@vasu.staging", "role": "director", "name": "QA Director"}).json()
        tok = d.get("session_token") or ""
        add("login_dev_director", bool(tok), f"token_len={len(tok)}")
        hdr = {"Authorization": f"Bearer {tok}"} if tok else {}

        # 2) Existing user list visible
        r = requests.get(f"{STAGING_BASE}/api/users", headers=hdr, timeout=10)
        add("users_list", r.status_code == 200 and isinstance(r.json(), list), f"http={r.status_code}")

        # 3) Masters
        for coll in ("materials", "vendors", "customers", "projects"):
            r = requests.get(f"{STAGING_BASE}/api/{coll}", headers=hdr, timeout=10)
            add(f"master_{coll}", r.status_code == 200, f"http={r.status_code}")

        # 4) MRF list
        r = requests.get(f"{STAGING_BASE}/api/mrf", headers=hdr, timeout=10)
        mrfs = r.json() if r.status_code == 200 else []
        add("mrf_list", r.status_code == 200, f"http={r.status_code} n={len(mrfs) if isinstance(mrfs, list) else '?'}")

        # 5) MRF create (QA fixture on staging) — schema per server.MRFCreate
        payload = {
            "project_id": (mrfs[0].get("project_id") if mrfs else "prj_seed_qa"),
            "site": "QA-site",
            "required_by": "2026-12-31",
            "requesting_person": "QA Director",
            "system_category": "Fire",
            "items": [{
                "description": "QA-fixture-item",
                "unit": "nos",
                "qty_requested": 1,
                "priority": "normal",
            }],
            "attachments": [],
            "remarks": "QA fixture — staging only",
        }
        r = requests.post(f"{STAGING_BASE}/api/mrf", headers=hdr, json=payload, timeout=10)
        new_mrf = r.json() if r.status_code == 200 else {}
        add("mrf_create", r.status_code == 200 and "mrf_id" in new_mrf, f"http={r.status_code}")

        # 6) MRF approve — endpoint takes ApprovalAction{action, comment, item_actions}
        if new_mrf.get("mrf_id"):
            r = requests.post(
                f"{STAGING_BASE}/api/mrf/{new_mrf['mrf_id']}/approve",
                headers=hdr,
                json={"action": "approve", "comment": "QA staging approve"},
                timeout=10,
            )
            add("mrf_approve", r.status_code == 200, f"http={r.status_code}")

        # 7) MRF reject — same endpoint, action=return / reject depending on impl.
        payload_second = dict(payload); payload_second["remarks"] = "QA fixture #2 — will be rejected"
        r = requests.post(f"{STAGING_BASE}/api/mrf", headers=hdr, json=payload_second, timeout=10)
        second = r.json() if r.status_code == 200 else {}
        if second.get("mrf_id"):
            r = requests.post(
                f"{STAGING_BASE}/api/mrf/{second['mrf_id']}/approve",
                headers=hdr,
                json={"action": "return", "comment": "QA staging reject/return"},
                timeout=10,
            )
            add("mrf_reject_return", r.status_code == 200, f"http={r.status_code}")

        # 8) PO list
        r = requests.get(f"{STAGING_BASE}/api/po", headers=hdr, timeout=10)
        add("po_list", r.status_code == 200, f"http={r.status_code}")

        # 9) GRN list  (endpoint is /grns plural per grn.py)
        r = requests.get(f"{STAGING_BASE}/api/grns", headers=hdr, timeout=10)
        add("grn_list", r.status_code == 200, f"http={r.status_code}")

        # 10) DC list
        r = requests.get(f"{STAGING_BASE}/api/dc", headers=hdr, timeout=10)
        add("dc_list", r.status_code == 200, f"http={r.status_code}")

        # 11) Comparative statement list
        r = requests.get(f"{STAGING_BASE}/api/comparative-statement", headers=hdr, timeout=10)
        add("cs_list", r.status_code in (200, 404), f"http={r.status_code}")

        # 12) Invoices
        r = requests.get(f"{STAGING_BASE}/api/invoice", headers=hdr, timeout=10)
        add("invoice_list", r.status_code in (200, 404), f"http={r.status_code}")

        # 13) Billing screen
        r = requests.get(f"{STAGING_BASE}/api/billing", headers=hdr, timeout=10)
        add("billing_screen", r.status_code in (200, 404), f"http={r.status_code}")

        # 14) Reports & exports
        for kind in ("mrf", "po", "grn", "dc"):
            r = requests.get(f"{STAGING_BASE}/api/export/{kind}", headers=hdr, timeout=15)
            add(f"export_{kind}", r.status_code == 200 and len(r.content) > 0,
                f"http={r.status_code} bytes={len(r.content)}")

        # 15) Tally export
        for kind in ("purchase", "invoice"):
            r = requests.get(f"{STAGING_BASE}/api/export/tally?kind={kind}", headers=hdr, timeout=15)
            add(f"tally_{kind}", r.status_code == 200, f"http={r.status_code} bytes={len(r.content)}")

        # 16) Audit trail
        r = requests.get(f"{STAGING_BASE}/api/audit", headers=hdr, timeout=10)
        add("audit_list", r.status_code == 200, f"http={r.status_code}")

        # 17) AI panels smoke (non-blocking)
        r = requests.get(f"{STAGING_BASE}/api/llm/my-budget", headers=hdr, timeout=10)
        add("ai_my_budget", r.status_code == 200, f"http={r.status_code}")
        r = requests.post(f"{STAGING_BASE}/api/llm/purchase-analysis", headers=hdr, json={
            "description": "QA fixture item", "qty": 1, "tier": "deterministic",
            "current_quote": {"vendor_name": "QA vendor", "rate": 100, "qty": 1, "gst": 18},
        }, timeout=15)
        add("ai_negotiate_deterministic", r.status_code == 200, f"http={r.status_code}")
        r = requests.post(f"{STAGING_BASE}/api/llm/quotation-compare", headers=hdr, json={
            "tier": "deterministic",
            "quotes": [{"vendor_name":"A","items":[{"description":"cable","qty":1,"rate":100,"gst":18}]},
                         {"vendor_name":"B","items":[{"description":"cable","qty":1,"rate":95,"gst":18}]}],
        }, timeout=15)
        add("ai_compare_deterministic", r.status_code == 200, f"http={r.status_code}")

        # Save report
        Path("/app/backup_artifacts/regression_report.json").write_text(json.dumps({
            "staging_db": stg_db, "staging_base": STAGING_BASE,
            "passed": sum(1 for x in results if x["ok"]),
            "failed": sum(1 for x in results if not x["ok"]),
            "results": results,
        }, indent=2))
        print()
        print(f"[regression] pass={sum(1 for x in results if x['ok'])} "
                f"fail={sum(1 for x in results if not x['ok'])} — see /app/backup_artifacts/regression_report.json")

    finally:
        proc.send_signal(signal.SIGTERM)
        try: proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
        print("[regression] staging API stopped.")


if __name__ == "__main__":
    main()
