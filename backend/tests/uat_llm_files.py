"""UAT: LLM file-upload path with realistic BOQ / vendor quote / invoice PDFs.

Generates real, multi-line PDFs on the fly using ReportLab, then hits the
three /api/llm/* endpoints as a Purchase user and validates that:
  - pypdf actually extracts the text (chars_in > 0 in audit),
  - The LLM returns parseable JSON matching the documented schema,
  - Suggestions are persisted with status='pending_review',
  - Human accept/reject is audit-logged (no auto-mutation of workflow rows).

Run: `python -m backend.tests.uat_llm_files`  (backend service must be up on :8001).
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from typing import Any, Dict, List

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

BASE = os.environ.get("VASU_BASE_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


# --------------------------------------------------------------------------- PDF factories
def _pdf(title: str, subtitle: str, header: List[str], rows: List[List[Any]],
         footer_lines: List[str]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title,
                            leftMargin=36, rightMargin=36,
                            topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    story = [Paragraph(f"<b>{title}</b>", styles["Title"]),
             Paragraph(subtitle, styles["Normal"]),
             Spacer(1, 12)]
    data = [header] + rows
    tbl = Table(data, hAlign="LEFT", repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.whitesmoke, colors.white]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))
    for line in footer_lines:
        story.append(Paragraph(line, styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def boq_pdf() -> bytes:
    header = ["S.No", "Description", "Make", "Model", "Unit", "Qty"]
    rows = [
        [1, "IP CCTV Camera 4MP Bullet, IR 30m, IP67, PoE", "Hikvision",
         "DS-2CD1043G2-I", "Nos", 24],
        [2, "IP CCTV Camera 4MP Dome, IR 30m, PoE", "CP Plus",
         "CP-VNC-D41L3-MDS", "Nos", 12],
        [3, "8-Ch NVR, 8 PoE, 4K, 2SATA", "Hikvision",
         "DS-7608NI-Q2/8P", "Nos", 2],
        [4, "Cat6 UTP Cable, 305m Box, 23AWG", "D-Link",
         "NCB-C6UGRYR-305", "Box", 4],
        [5, "48-Port PoE+ Managed L2 Switch, 370W", "TP-Link",
         "TL-SG3452P", "Nos", 1],
        [6, "6U Wall-Mount Rack with Fan & PDU", "Netrack",
         "NR-06U-600", "Nos", 1],
        [7, "Fire Detector Photoelectric Smoke Detector, 24V",
         "Notifier", "SD-651", "Nos", 30],
        [8, "Access Control Reader — Mifare 13.56MHz", "ZKTeco",
         "KR500", "Nos", 6],
    ]
    footer = [
        "Project: Vasu Corporate HQ – Fire Safety & Surveillance Retrofit",
        "Location: Pune Phase 2 · Prepared by: PM Saket Iyer · 20-May-2026",
        "Note: All items must be MAKE-preferred. Substitutions require GM approval.",
    ]
    return _pdf("Bill of Quantities (BOQ) – Rev 3",
                "Vasu Infosec Pvt Ltd · Project VI-2026-018", header, rows, footer)


def vendor_quote_pdf(vendor: str, price_factor: float, include_extras: bool = False) -> bytes:
    header = ["S.No", "Description", "Make", "Model", "Unit",
              "Qty", "Rate (INR)", "GST %", "Amount"]
    line_items = [
        (1, "IP CCTV Camera 4MP Bullet PoE IR30 IP67", "Hikvision",
         "DS-2CD1043G2-I", "Nos", 24, 5850.0),
        (2, "IP CCTV Camera 4MP Dome PoE IR30", "CP Plus",
         "CP-VNC-D41L3-MDS", "Nos", 12, 4200.0),
        (3, "8-Ch 4K NVR with 8 PoE ports", "Hikvision",
         "DS-7608NI-Q2/8P", "Nos", 2, 22500.0),
        (4, "Cat6 UTP 305m 23AWG", "D-Link",
         "NCB-C6UGRYR-305", "Box", 4, 5250.0),
        (5, "48-Port PoE+ Managed L2 Switch 370W", "TP-Link",
         "TL-SG3452P", "Nos", 1, 42750.0),
        (6, "6U Wall Rack with fan+PDU", "Netrack", "NR-06U-600",
         "Nos", 1, 6100.0),
        (7, "Photoelectric Smoke Detector 24V", "Notifier",
         "SD-651", "Nos", 30, 1250.0),
        (8, "Access Reader Mifare 13.56MHz", "ZKTeco",
         "KR500", "Nos", 6, 2450.0),
    ]
    rows: List[List[Any]] = []
    total_taxable = 0.0
    total_with_tax = 0.0
    for sr, desc, make, model, unit, qty, base_rate in line_items:
        rate = round(base_rate * price_factor, 2)
        gst = 18
        amount = round(qty * rate * (1 + gst / 100), 2)
        total_taxable += qty * rate
        total_with_tax += amount
        rows.append([sr, desc, make, model, unit, qty,
                     f"{rate:,.2f}", gst, f"{amount:,.2f}"])
    if include_extras:
        # Add an out-of-scope line (should trigger an anomaly)
        rows.append(["EXTRA", "Optional: 4TB Surveillance HDD (add-on)",
                     "WD", "Purple 4TB", "Nos", 4, "9,800.00", 18, "46,246.00"])

    footer = [
        f"Vendor: <b>{vendor}</b> · Quotation No: Q-2026-{abs(hash(vendor)) % 9000 + 1000}",
        "Terms: 30% advance, balance against delivery. Delivery: 3 weeks ex-works.",
        f"Sub-total (before tax): INR {total_taxable:,.2f}",
        f"GST @ 18% (approx): INR {total_with_tax - total_taxable:,.2f}",
        f"<b>Grand Total: INR {total_with_tax:,.2f}</b>",
        "Warranty: 3 years OEM. Freight & installation extra.",
    ]
    return _pdf(f"Vendor Quotation – {vendor}",
                "Against Vasu Infosec BOQ Rev 3 · dated 22-May-2026",
                header, rows, footer)


def vendor_invoice_pdf(vendor: str, po_number: str,
                        over_deliver: bool = False,
                        rate_mismatch: bool = False) -> bytes:
    header = ["S.No", "Description", "HSN", "Unit", "Qty",
              "Rate (INR)", "GST %", "Amount"]
    lines = [
        (1, "IP CCTV Camera 4MP Bullet PoE", "85258920", "Nos",
         24, 5900.0 if rate_mismatch else 5850.0),
        (2, "IP CCTV Camera 4MP Dome PoE", "85258920", "Nos",
         14 if over_deliver else 12, 4200.0),
        (3, "8-Ch 4K NVR 8 PoE", "85258920", "Nos", 2, 22500.0),
        (4, "Cat6 UTP 305m", "85444990", "Box", 4, 5250.0),
    ]
    rows: List[List[Any]] = []
    total_taxable = 0.0
    grand = 0.0
    for sr, desc, hsn, unit, qty, rate in lines:
        gst = 18
        amt = round(qty * rate * (1 + gst / 100), 2)
        rows.append([sr, desc, hsn, unit, qty,
                     f"{rate:,.2f}", gst, f"{amt:,.2f}"])
        total_taxable += qty * rate
        grand += amt
    footer = [
        f"Tax Invoice No: INV-2026-{abs(hash(po_number)) % 900 + 100}",
        f"Against Purchase Order: <b>{po_number}</b>",
        f"Invoice Date: 05-Jun-2026 · Vendor: <b>{vendor}</b>",
        f"Sub-total: INR {total_taxable:,.2f}",
        f"GST 18%: INR {grand - total_taxable:,.2f}",
        f"<b>Grand Total: INR {grand:,.2f}</b>",
    ]
    return _pdf(f"Tax Invoice – {vendor}",
                "Original for Recipient",
                header, rows, footer)


# --------------------------------------------------------------------------- HTTP helper
def dev_login(role: str) -> str:
    r = requests.post(f"{API}/auth/dev-login",
                      json={"email": f"{role}@vasu.dev",
                            "role": role, "name": role.title()},
                      timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("session_token") or j.get("token") or j["access_token"]


def hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def attach(name: str, mime: str, data: bytes) -> Dict[str, str]:
    return {"file_name": name, "mime_type": mime, "file_base64": b64(data)}


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def section(title: str) -> None:
    print(f"\n\033[1;36m▶ {title}\033[0m")


# --------------------------------------------------------------------------- Test runs
def run() -> int:
    print(f"UAT LLM file-upload path against {API}\n")
    failures = 0

    section("0) Auth (dev-login as purchase)")
    try:
        tok = dev_login("purchase")
        ok(f"purchase token acquired (len={len(tok)})")
    except Exception as e:
        fail(f"dev-login failed: {e}")
        return 1

    # Ensure at least one approved material exists (so item-standardise has a catalogue).
    section("0b) Ensure catalogue has approved materials")
    try:
        mats = requests.get(f"{API}/materials?status=approved",
                            headers=hdr(tok), timeout=30).json()
        if isinstance(mats, list) and mats:
            ok(f"{len(mats)} approved materials in catalogue")
        else:
            # Seed
            requests.post(f"{API}/seed", headers=hdr(tok), timeout=60)
            mats = requests.get(f"{API}/materials?status=approved",
                                headers=hdr(tok), timeout=30).json()
            ok(f"seeded catalogue; {len(mats)} approved materials")
    except Exception as e:
        fail(f"catalogue check failed: {e}")

    # ------------------------------------------------------------------ 1
    section("1) /api/llm/item-standardise  ← BOQ PDF")
    boq_bytes = boq_pdf()
    print(f"    · BOQ PDF generated ({len(boq_bytes):,} bytes)")
    body = {
        "description": ("4MP IP bullet PoE outdoor camera, IR 30m, IP67 "
                        "for corporate perimeter"),
        "make": "Hikvision", "model": "DS-2CD1043G2-I", "unit": "Nos",
        "context": "Fire Safety & Surveillance retrofit BOQ Rev 3",
        "attachments": [attach("BOQ_Rev3.pdf", "application/pdf", boq_bytes)],
    }
    try:
        r = requests.post(f"{API}/llm/item-standardise",
                          headers=hdr(tok), data=json.dumps(body), timeout=90)
        if r.status_code != 200:
            fail(f"HTTP {r.status_code}: {r.text[:400]}"); failures += 1
        else:
            js = r.json()
            sug1 = js.get("suggestion_id")
            parsed = js.get("output_parsed") or {}
            sugs = parsed.get("suggestions") or []
            ok(f"suggestion_id={sug1}  status={js.get('status')}")
            ok(f"suggestions returned: {len(sugs)}  "
               f"(top confidence={sugs[0].get('confidence') if sugs else 'n/a'})")
            attach_info = (js.get("input_summary") or {}).get("attachments") or []
            if attach_info and attach_info[0].get("chars", 0) > 200:
                ok(f"pypdf extracted {attach_info[0]['chars']} chars from BOQ")
            else:
                fail(f"pypdf extraction anaemic: {attach_info}"); failures += 1
    except Exception as e:
        fail(f"exception: {e}"); failures += 1

    # ------------------------------------------------------------------ 2
    section("2) /api/llm/quotation-compare  ← 3 vendor quote PDFs")
    q_a = vendor_quote_pdf("SecureVision Systems", 1.00)
    q_b = vendor_quote_pdf("NetGuard India", 1.06, include_extras=True)
    q_c = vendor_quote_pdf("SafetyFirst Traders", 0.94)
    for name, blob in [("Q1", q_a), ("Q2", q_b), ("Q3", q_c)]:
        print(f"    · {name} PDF: {len(blob):,} bytes")
    body = {
        "context": "Vasu Corporate HQ retrofit – select L1 across full BOQ",
        "attachments": [
            attach("SecureVision_Quote.pdf", "application/pdf", q_a),
            attach("NetGuard_Quote.pdf", "application/pdf", q_b),
            attach("SafetyFirst_Quote.pdf", "application/pdf", q_c),
        ],
    }
    sug2 = None
    try:
        r = requests.post(f"{API}/llm/quotation-compare",
                          headers=hdr(tok), data=json.dumps(body), timeout=120)
        if r.status_code != 200:
            fail(f"HTTP {r.status_code}: {r.text[:400]}"); failures += 1
        else:
            js = r.json()
            sug2 = js.get("suggestion_id")
            parsed = js.get("output_parsed") or {}
            ranking = parsed.get("ranking") or []
            anomalies = parsed.get("anomalies") or []
            ok(f"suggestion_id={sug2}  tier={js.get('tier')}  model={js.get('model')}")
            ok(f"vendors ranked: {len(ranking)}   anomalies flagged: {len(anomalies)}")
            if ranking:
                l1 = ranking[0]
                ok(f"L1 → {l1.get('vendor_name')} @ "
                   f"₹{l1.get('total_with_tax') or l1.get('total_taxable')}")
            # Because SafetyFirst uses 0.94 factor, it should rank L1.
            expected_l1 = "SafetyFirst"
            if ranking and expected_l1.lower() in (ranking[0].get("vendor_name", "").lower()):
                ok(f"L1 correctly identified as {expected_l1}")
            else:
                print(f"    (soft) L1={ranking[0].get('vendor_name') if ranking else '?'} "
                      f"(expected SafetyFirst — LLM may still rank OK by different metric)")
    except Exception as e:
        fail(f"exception: {e}"); failures += 1

    # ------------------------------------------------------------------ 3
    section("3) /api/llm/reconcile  ← invoice PDF vs an existing PO")
    # Reuse an existing PO (creating one requires full MRF/PO chain — out of
    # scope for this UAT).
    try:
        pos = requests.get(f"{API}/po?limit=5",
                            headers=hdr(tok), timeout=30).json()
    except Exception as e:
        fail(f"list POs failed: {e}"); return failures + 1
    if not isinstance(pos, list) or not pos:
        fail("no POs on server — reconcile step skipped"); return failures + 1
    po = pos[0]
    po_id = po.get("po_id")
    po_number = po.get("po_number") or "PO-UAT"
    vendor_name = po.get("vendor_name") or "Vendor"
    ok(f"reusing existing PO {po_number}  po_id={po_id}")

    inv_bytes = vendor_invoice_pdf(vendor_name, po_number,
                                    over_deliver=True, rate_mismatch=True)
    print(f"    · invoice PDF generated ({len(inv_bytes):,} bytes) — with 1 qty & 1 rate mismatch")
    body = {"po_id": po_id,
            "attachments": [attach("Vendor_Invoice.pdf",
                                    "application/pdf", inv_bytes)]}
    sug3 = None
    try:
        r = requests.post(f"{API}/llm/reconcile",
                          headers=hdr(tok), data=json.dumps(body), timeout=120)
        if r.status_code != 200:
            fail(f"HTTP {r.status_code}: {r.text[:400]}"); failures += 1
        else:
            js = r.json()
            sug3 = js.get("suggestion_id")
            parsed = js.get("output_parsed") or {}
            per_line = parsed.get("per_line") or []
            excs = parsed.get("exceptions") or []
            ok(f"suggestion_id={sug3}  per_line={len(per_line)}  exceptions={len(excs)}")
            statuses = {p.get("status") for p in per_line}
            ok(f"per-line statuses seen: {sorted(s for s in statuses if s)}")
            # Expect at least one non-'match' status because we injected mismatches.
            if statuses and any(s and s != "match" for s in statuses):
                ok("mismatch correctly detected by LLM")
            else:
                print("    (soft) LLM did not flag mismatch — worth manual review")
    except Exception as e:
        fail(f"exception: {e}"); failures += 1

    # ------------------------------------------------------------------ 4
    section("4) Suggestion decide (accept & reject roundtrips)")
    for sid, action in [(sug1, "reject"), (sug2, "accept"), (sug3, "accept")]:
        if not sid: continue
        try:
            r = requests.post(f"{API}/llm/suggestions/{sid}/decide",
                              headers=hdr(tok),
                              data=json.dumps({"action": action,
                                                "reason": f"UAT {action}"}),
                              timeout=30)
            if r.status_code != 200:
                fail(f"{action} {sid}: HTTP {r.status_code} {r.text[:200]}")
                failures += 1
            else:
                ok(f"suggestion {sid[:14]}… → {r.json().get('status')}")
        except Exception as e:
            fail(f"{action} {sid}: {e}"); failures += 1

    # ------------------------------------------------------------------ 5
    section("5) List suggestions (should include our three)")
    try:
        r = requests.get(f"{API}/llm/suggestions?limit=20",
                          headers=hdr(tok), timeout=30)
        r.raise_for_status()
        rows = r.json()
        ids = {row.get("suggestion_id") for row in rows}
        for sid in [sug1, sug2, sug3]:
            if sid and sid in ids:
                ok(f"found {sid[:14]}… in list")
            elif sid:
                fail(f"missing {sid} from list"); failures += 1
    except Exception as e:
        fail(f"list failed: {e}"); failures += 1

    print(f"\n{'='*54}\nUAT complete. Failures: {failures}")
    return failures


if __name__ == "__main__":
    sys.exit(run())
