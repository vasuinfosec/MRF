"""Invoice router — extracted from server.py in Phase 9C round 5 (Batch C).

Vendor invoice CRUD + PDF export. Restricted to purchase/director/admin.
Enforces per-line invoice cap against remaining PO qty (prior invoiced sum).
"""
from __future__ import annotations

import io
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException
from fastapi.responses import StreamingResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, SimpleDocTemplate

from server import (
    api, db, get_current_user, audit, now_utc, gid,
    _pdf_story, _vasu_footer,
    next_invoice_number,
    VASU_PRIMARY,
    InvoiceCreate,
    bearer_from_url_token,
)


@api.post("/invoice")
async def create_invoice(body: InvoiceCreate,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    po = await db.pos.find_one({"po_id": body.po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")

    po_line_map = {pit["item_line_id"]: pit for pit in po.get("items", [])}
    already_invoiced: Dict[str, float] = {}
    prior = await db.invoices.find({"po_id": body.po_id}, {"_id": 0}).to_list(500)
    for iv in prior:
        for r in iv.get("items", []):
            key = r.get("item_line_id") or ""
            already_invoiced[key] = already_invoiced.get(key, 0) + float(r.get("qty") or 0)

    subtotal = 0.0
    gst_total = 0.0
    items = []
    for it in body.items:
        if it.item_line_id and it.item_line_id not in po_line_map:
            raise HTTPException(400, f"Item line {it.item_line_id} not in PO {po['po_number']}")
        if it.item_line_id:
            po_line = po_line_map[it.item_line_id]
            max_qty = max(0.0, float(po_line.get("qty") or 0)
                          - already_invoiced.get(it.item_line_id, 0))
            if it.qty > max_qty + 1e-6:
                raise HTTPException(
                    400,
                    f"Qty {it.qty} exceeds remaining invoiceable qty {max_qty} "
                    f"for '{po_line.get('description','')}'",
                )
        gross = it.qty * it.rate
        after_disc = gross - it.discount
        gst_amt = after_disc * it.gst / 100
        subtotal += after_disc
        gst_total += gst_amt
        items.append({**it.model_dump(),
                       "line_total": round(after_disc + gst_amt, 2)})
    total = round(subtotal + gst_total + body.freight + body.other_charges, 2)
    inv = {
        "invoice_id": gid("inv"),
        "invoice_number": await next_invoice_number(),
        "vendor_invoice_number": body.vendor_invoice_number or "",
        "invoice_date": body.invoice_date or now_utc().strftime("%Y-%m-%d"),
        "po_id": body.po_id,
        "po_number": po["po_number"],
        "vendor_id": po["vendor_id"],
        "project_id": po["project_id"],
        "customer_id": po.get("customer_id"),
        "customer_name": po.get("customer_name"),
        "mrf_refs": po.get("mrf_refs", []),
        "items": items,
        "subtotal": round(subtotal, 2),
        "gst_total": round(gst_total, 2),
        "freight": body.freight,
        "other_charges": body.other_charges,
        "total": total,
        "remarks": body.remarks or "",
        "status": "recorded",
        "created_by": u.user_id,
        "created_by_name": u.name,
        "created_at": now_utc(),
    }
    await db.invoices.insert_one(inv)
    await audit("invoice", inv["invoice_id"], "create", u,
                 {"invoice_number": inv["invoice_number"], "total": total})
    inv.pop("_id", None)
    return inv


@api.get("/invoice")
async def list_invoices(po_id: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    q: Dict[str, Any] = {}
    if po_id:
        q["po_id"] = po_id
    return await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.get("/invoice/{inv_id}")
async def get_invoice(inv_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    d = await db.invoices.find_one({"invoice_id": inv_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Invoice not found")
    return d


@api.get("/invoice/{inv_id}/pdf")
async def invoice_pdf(inv_id: str, token: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    auth = authorization or bearer_from_url_token(token)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    inv = await db.invoices.find_one({"invoice_id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    vendor = await db.vendors.find_one({"vendor_id": inv["vendor_id"]}, {"_id": 0}) or {}
    project = await db.projects.find_one({"project_id": inv["project_id"]}, {"_id": 0}) or {}
    mrf_nums = []
    for mid in inv.get("mrf_refs") or []:
        m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "mrf_number": 1})
        if m:
            mrf_nums.append(m["mrf_number"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                              leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)

    cid = inv.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    story = _pdf_story(
        "VENDOR INVOICE", inv["invoice_number"], inv["invoice_date"],
        project, cust, vendor,
        extra_ref=(f"Vendor Ref: {inv.get('vendor_invoice_number') or '—'}  ·  "
                    f"PO: {inv['po_number']}  ·  MRF: {', '.join(mrf_nums) or '—'}"),
    )

    data = [["#", "Description", "Unit", "Qty", "Rate", "Disc", "GST%", "Total"]]
    for idx, it in enumerate(inv["items"], 1):
        data.append([
            str(idx), (it["description"] or "")[:40], it.get("unit", ""),
            str(it["qty"]), f"{it['rate']}", f"{it.get('discount', 0)}",
            f"{it.get('gst', 0)}", f"{it.get('line_total', 0):.2f}",
        ])
    tbl = Table(data, colWidths=[20, 180, 40, 40, 50, 40, 40, 60])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Subtotal:</b> ₹{inv['subtotal']:,.2f}  "
        f"<b>GST:</b> ₹{inv['gst_total']:,.2f}  "
        f"<b>Freight:</b> ₹{inv.get('freight', 0):,.2f}  "
        f"<b>Other:</b> ₹{inv.get('other_charges', 0):,.2f}  "
        f"<b>Grand Total:</b> ₹{inv['total']:,.2f}", small))
    if inv.get("remarks"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Remarks:</b> {inv['remarks']}", small))
    story += [
        Spacer(1, 30),
        Paragraph("Recorded by: " + inv.get("created_by_name", ""), small),
    ]
    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{inv["invoice_number"].replace("/", "_")}.pdf"'},
    )
