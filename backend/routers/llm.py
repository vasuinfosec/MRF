"""LLM Co-pilot router — extracted from server.py in Phase 9C for maintainability.

This module is imported at the end of server.py *for its side effects*: it
attaches all /api/llm/* endpoints to the shared APIRouter. It intentionally
imports names from server.py at import time — safe because server.py imports
this module AFTER defining `api`, `db`, `audit`, etc.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
import os
from fastapi import HTTPException, Header, Body
from pydantic import BaseModel

# Late-bind server-defined singletons. Server imports this module last, so all
# these names are guaranteed to exist by the time the decorators here execute.
from server import (
    api, db, audit, get_current_user, UserOut, gid, now_utc,
    _strip_oids, _check_po_access, openpyxl,
)

from emergentintegrations.llm.chat import LlmChat, UserMessage
import hashlib as _hashlib
import json as _json
import base64 as _base64_llm
import csv as _csv_llm
import io as _io_llm

EMERGENT_LLM_KEY = os.getenv("EMERGENT_LLM_KEY", "")

# Tier → model name.
#   cheap (DEFAULT)  = OpenAI gpt-4o-mini      — cheapest text model in Emergent LLM Key.
#   premium          = Anthropic Sonnet 4.5   — only used when explicitly overridden.
# Haiku was removed (~5x more expensive per output token than gpt-4o-mini).
_LLM_MODELS = {
    "cheap": ("openai", "gpt-4o-mini"),
    "premium": ("anthropic", "claude-sonnet-4-5-20250929"),
}

# Public pricing (USD per 1M tokens) as of 2025 Q4 — used only to display
# an approximate cost on each call. Actual billing is on the Emergent
# Universal Key credit balance.
_MODEL_PRICING_USD_PER_M = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    # Kept for legacy suggestions written under the previous configuration.
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}
_USD_TO_INR = 83.0


def _estimate_tokens(text: str) -> int:
    """Fast, dependency-free token approximation. Roughly `chars / 4` is the
    industry rule-of-thumb for English text; JSON/structured content is a bit
    denser, so we use 3.6 as the divisor.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 3.6))


def _cost_breakdown(model: str, in_tokens: int, out_tokens: int) -> Dict[str, Any]:
    rates = _MODEL_PRICING_USD_PER_M.get(model)
    if not rates:
        return {"model": model, "input_tokens": in_tokens, "output_tokens": out_tokens,
                "cost_inr": None, "note": "unknown_model_pricing"}
    cost_usd = (in_tokens / 1_000_000) * rates["input"] + \
               (out_tokens / 1_000_000) * rates["output"]
    return {
        "model": model,
        "input_tokens_approx": in_tokens,
        "output_tokens_approx": out_tokens,
        "input_rate_usd_per_m": rates["input"],
        "output_rate_usd_per_m": rates["output"],
        "cost_usd": round(cost_usd, 6),
        "cost_inr": round(cost_usd * _USD_TO_INR, 4),
        "cache_saved": False,
    }

# Roles allowed to invoke each LLM feature.
LLM_ROLES_STD = {"purchase", "admin", "pm", "gm", "director"}
LLM_ROLES_COMPARE = {"purchase", "admin", "pm", "gm", "director"}
LLM_ROLES_RECONCILE = {"purchase", "admin", "gm", "director"}
LLM_ROLES_DECIDE = {"purchase", "admin", "pm", "gm", "director"}

# Attachment limits
LLM_MAX_ATTACHMENT_MB = 10
LLM_MAX_EXTRACTED_CHARS = 40000  # trim extracted text to keep token spend sane


def _decode_b64(payload: str) -> bytes:
    if not payload:
        return b""
    # Strip data URL prefix if present
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    return _base64_llm.b64decode(payload.encode("utf-8"), validate=False)


def _extract_text_from_attachment(file_name: str, mime_type: str,
                                   file_base64: str) -> Tuple[str, str]:
    """Return (extracted_text, detected_kind).
    Supported kinds: pdf, xlsx, xls, csv, txt.
    Images/other → returns empty text with kind='unsupported'.
    """
    raw = _decode_b64(file_base64 or "")
    if not raw:
        return ("", "empty")
    if len(raw) > LLM_MAX_ATTACHMENT_MB * 1024 * 1024:
        raise HTTPException(413, f"Attachment exceeds {LLM_MAX_ATTACHMENT_MB} MB")
    name = (file_name or "").lower()
    mt = (mime_type or "").lower()
    try:
        if "pdf" in mt or name.endswith(".pdf"):
            import pypdf
            reader = pypdf.PdfReader(_io_llm.BytesIO(raw))
            parts: List[str] = []
            for i, pg in enumerate(reader.pages[:60]):  # cap 60 pages
                try:
                    parts.append(f"[Page {i+1}]\n{(pg.extract_text() or '').strip()}")
                except Exception:
                    continue
            text = "\n\n".join(parts).strip()
            return (text[:LLM_MAX_EXTRACTED_CHARS], "pdf")
        if "spreadsheetml" in mt or name.endswith(".xlsx") or name.endswith(".xls"):
            wb = openpyxl.load_workbook(_io_llm.BytesIO(raw), data_only=True, read_only=True)
            lines: List[str] = []
            for ws in wb.worksheets[:6]:  # cap 6 sheets
                lines.append(f"### Sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = ["" if c is None else str(c) for c in row]
                    if any(cells):
                        lines.append("\t".join(cells))
                    if len("\n".join(lines)) > LLM_MAX_EXTRACTED_CHARS:
                        break
            return ("\n".join(lines)[:LLM_MAX_EXTRACTED_CHARS], "xlsx")
        if "csv" in mt or name.endswith(".csv"):
            txt = raw.decode("utf-8", errors="replace")
            reader = _csv_llm.reader(_io_llm.StringIO(txt))
            lines = ["\t".join(r) for r in reader]
            return ("\n".join(lines)[:LLM_MAX_EXTRACTED_CHARS], "csv")
        if "text" in mt or name.endswith(".txt"):
            return (raw.decode("utf-8", errors="replace")[:LLM_MAX_EXTRACTED_CHARS], "txt")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read attachment ({name}): {e}")
    # Unsupported (images, etc.)
    return ("", "unsupported")


def _payload_hash(payload: Any) -> str:
    return _hashlib.sha256(_json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _extract_json(txt: str) -> Any:
    """LLMs sometimes wrap JSON in ```json blocks — this pulls it out."""
    if not txt:
        return None
    t = txt.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.startswith("json\n"):
            t = t[5:]
        # locate first { or [
        for i, c in enumerate(t):
            if c in "{[":
                t = t[i:]
                break
    # try full then progressively trim trailing
    try:
        return _json.loads(t)
    except Exception:
        # find last balanced brace
        last = max(t.rfind("}"), t.rfind("]"))
        if last > 0:
            try:
                return _json.loads(t[:last + 1])
            except Exception:
                pass
    return None


async def _call_llm(tier: str, system: str, user_text: str,
                    user: UserOut, kind: str,
                    entity: str, entity_id: str,
                    input_payload: dict) -> Tuple[str, dict]:
    """Call the LLM with the given prompt and audit-log the invocation.

    Returns: (raw_text, audit_extras).
    Raises HTTPException(500) if the key is missing.
    """
    if not EMERGENT_LLM_KEY:
        raise HTTPException(500, "EMERGENT_LLM_KEY not configured on server")
    provider, model = _LLM_MODELS.get(tier, _LLM_MODELS["cheap"])
    # Simple content-hash-based cache to avoid burning credits on identical prompts
    h = _payload_hash({"tier": tier, "sys": system, "user": user_text})
    cached = await db.llm_cache.find_one({"_id": h}, {"_id": 0, "response": 1})
    if cached and cached.get("response"):
        cb = _cost_breakdown(model,
                              _estimate_tokens(system + user_text),
                              _estimate_tokens(cached["response"]))
        cb["cost_usd"] = 0.0
        cb["cost_inr"] = 0.0
        cb["cache_saved"] = True
        return cached["response"], {"cached": True, "tier": tier, "model": model,
                                      "hash": h, "cost": cb}

    session_id = f"vasu_{kind}_{gid('sess')[:16]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id,
                   system_message=system).with_model(provider, model)
    try:
        resp = await chat.send_message(UserMessage(text=user_text))
    except Exception as e:
        # Fail closed — do not fabricate suggestions
        raise HTTPException(502, f"LLM call failed: {e}")
    text = str(resp or "")
    await db.llm_cache.update_one(
        {"_id": h},
        {"$set": {"response": text, "created_at": now_utc(),
                  "tier": tier, "model": model, "kind": kind}},
        upsert=True,
    )
    in_tok = _estimate_tokens(system + user_text)
    out_tok = _estimate_tokens(text)
    cost = _cost_breakdown(model, in_tok, out_tok)
    extras = {
        "tier": tier, "model": model, "kind": kind, "hash": h,
        "chars_in": len(user_text) + len(system),
        "chars_out": len(text),
        "cost": cost,
    }
    await audit("llm", entity_id or "n/a", f"llm_call_{kind}", user,
                {"tier": tier, "model": model, "entity": entity,
                 "record_number": input_payload.get("record_number", ""),
                 "chars_in": extras["chars_in"], "chars_out": extras["chars_out"],
                 "input_tokens_approx": in_tok, "output_tokens_approx": out_tok,
                 "cost_inr": cost.get("cost_inr")})
    return text, extras


async def _save_suggestion(kind: str, entity: str, entity_id: str,
                           user: UserOut, input_payload: dict,
                           parsed: Any, raw: str, tier: str, model: str,
                           extras: dict) -> dict:
    sid = gid("sug")
    doc = {
        "suggestion_id": sid,
        "kind": kind,
        "entity": entity,
        "entity_id": entity_id or "",
        "status": "pending_review",
        "tier": tier,
        "model": model,
        "created_by": user.user_id,
        "created_by_name": user.name,
        "created_by_role": user.role,
        "created_at": now_utc(),
        "input_hash": extras.get("hash"),
        "input_summary": {k: v for k, v in input_payload.items() if k != "long_text"},
        "output_raw": raw,
        "output_parsed": parsed,
        "cost": extras.get("cost"),                    # <-- new
        "cached": bool(extras.get("cached")),          # <-- new
        "decision": None,
        "decided_by": None,
        "decided_at": None,
        "decision_reason": "",
    }
    await db.llm_suggestions.insert_one(dict(doc))
    doc.pop("_id", None)
    return _strip_oids(doc)


# ---- 1) Item Standardisation (Haiku / cheap) --------------------------------

class LlmAttachment(BaseModel):
    file_name: str
    mime_type: str = ""
    file_base64: str


class ItemStandardiseIn(BaseModel):
    description: str
    make: Optional[str] = ""
    model: Optional[str] = ""
    unit: Optional[str] = ""
    context: Optional[str] = ""  # e.g. "MRF Fire Safety Camera"
    attachments: Optional[List[LlmAttachment]] = None


@api.post("/llm/item-standardise")
async def llm_item_standardise(body: ItemStandardiseIn,
                                authorization: Optional[str] = Header(None)):
    """Suggest MAT-/VAR- UIDs and closest Material-Master matches for a
    free-text line item. Returns top-3 candidates with a confidence score.
    NOTE: LLM DOES NOT create, edit or approve the master data — the caller
    (Purchase/PM) explicitly accepts a suggestion via /api/llm/suggestions/{id}/decide.
    """
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_STD:
        raise HTTPException(403, "Not allowed")
    if not (body.description or "").strip():
        raise HTTPException(400, "description is required")
    # Fetch approved masters (limit to keep prompt small)
    approved = await db.materials.find(
        {"status": "approved"},
        {"_id": 0, "material_uid": 1, "description": 1, "category": 1,
         "unit": 1, "hsn_code": 1}
    ).limit(200).to_list(200)
    variants = await db.variants.find(
        {},
        {"_id": 0, "variant_uid": 1, "material_uid": 1, "make": 1, "model": 1}
    ).limit(600).to_list(600)
    system = (
        "You are a procurement item-standardisation assistant for Vasu Infosec. "
        "You are given a free-text material description plus a catalogue of approved "
        "materials (MAT-####) and variants (VAR-####). "
        "Return top 3 best matches with confidence 0..1. "
        "You DO NOT approve, create, or modify masters. Output STRICT JSON only, "
        "no prose."
    )
    prompt = _json.dumps({
        "input": body.model_dump(exclude={"attachments"}),
        "catalogue_materials": approved[:200],
        "catalogue_variants": variants[:600],
        "instructions": (
            "Return JSON: {suggestions: [{material_uid, variant_uid (nullable), "
            "matched_description, category, hsn_code, confidence, reasoning}]} — "
            "sorted by confidence desc, at most 3 items. If no plausible match, "
            "return {suggestions: [], notes: 'no match'}. "
            "Never invent material_uid values not present in the catalogue."
        ),
    })
    # Append attachment-extracted text if provided
    attach_summary: List[dict] = []
    if body.attachments:
        chunks: List[str] = []
        for att in body.attachments[:5]:
            text, kind = _extract_text_from_attachment(att.file_name, att.mime_type, att.file_base64)
            attach_summary.append({"file_name": att.file_name, "kind": kind, "chars": len(text)})
            if text:
                chunks.append(f"--- Attachment: {att.file_name} ({kind}) ---\n{text}")
        if chunks:
            prompt += "\n\nAttached documents:\n" + "\n\n".join(chunks)
    raw, extras = await _call_llm("cheap", system, prompt, u,
                                   kind="item_standardise",
                                   entity="material", entity_id="",
                                   input_payload={"description": body.description,
                                                  "attachments": attach_summary})
    parsed = _extract_json(raw) or {"suggestions": [], "notes": "unparseable"}
    # Defensive: strip any suggestion that references an unknown MAT-#### UID
    known_muid = {m["material_uid"] for m in approved}
    parsed_suggestions = []
    for s in (parsed.get("suggestions") or []):
        if not isinstance(s, dict): continue
        muid = s.get("material_uid")
        if muid and muid not in known_muid:
            continue  # LLM hallucinated a UID — drop it
        parsed_suggestions.append(s)
    parsed["suggestions"] = parsed_suggestions[:3]
    doc = await _save_suggestion(
        "item_standardise", "material", "", u,
        input_payload={
            "description": body.description, "make": body.make,
            "model": body.model, "unit": body.unit, "context": body.context,
            "attachments": attach_summary,
        }, parsed=parsed, raw=raw,
        tier="cheap", model=extras["model"], extras=extras,
    )
    return doc


# ---- 2) Quotation Comparison (Sonnet / premium) -----------------------------

class QuotationCompareIn(BaseModel):
    mrf_id: Optional[str] = ""
    po_id: Optional[str] = ""
    context: Optional[str] = ""
    quotes: Optional[List[Dict[str, Any]]] = None  # [{vendor_name, currency, items:[...]}]
    attachments: Optional[List[LlmAttachment]] = None  # PDF/Excel/CSV vendor quotes to auto-parse


@api.post("/llm/quotation-compare")
async def llm_quotation_compare(body: QuotationCompareIn,
                                 authorization: Optional[str] = Header(None)):
    """Produce an L1/L2/L3 side-by-side comparison with delta % and
    recommendations. Suggestions only — Purchase / PM must accept/reject."""
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_COMPARE:
        raise HTTPException(403, "Not allowed")
    quotes = body.quotes or []
    attach_summary: List[dict] = []
    attach_chunks: List[str] = []
    if body.attachments:
        # Enforce hard cap BEFORE any expensive processing.
        if len(body.attachments) > 8:
            raise HTTPException(400, "Max 8 vendor quote attachments per comparison")
        for att in body.attachments:
            text, kind = _extract_text_from_attachment(att.file_name, att.mime_type, att.file_base64)
            attach_summary.append({"file_name": att.file_name, "kind": kind, "chars": len(text)})
            if text:
                attach_chunks.append(f"--- Quotation file: {att.file_name} ({kind}) ---\n{text}")
    # Require either ≥2 structured quotes OR ≥2 attachments
    if len(quotes) + len(attach_chunks) < 2:
        raise HTTPException(400, "Provide at least 2 vendor quotes (structured or file attachments)")
    if len(quotes) > 6:
        raise HTTPException(400, "Max 6 structured vendor quotes per comparison")

    system = (
        "You are a senior procurement analyst for Vasu Infosec. Compare vendor "
        "quotations line-by-line and produce a decision-ready side-by-side. "
        "Rank vendors L1 (lowest total) → Ln, compute per-item delta% vs L1, and "
        "flag anomalies (rate outliers, missing items, unit mismatches, "
        "unusually low bids). You DO NOT issue POs or authorise vendors. "
        "Output STRICT JSON only. If vendor names/rates need to be inferred "
        "from unstructured attachments, do your best and flag low-confidence rows "
        "under anomalies with severity='info'."
    )
    prompt = _json.dumps({
        "quotes": quotes,
        "context": body.context or "",
        "instructions": (
            "Return JSON: {ranking:[{rank,vendor_name,total_taxable,total_with_tax,"
            "delta_pct_vs_L1}], line_comparison:[{description,l1_vendor,l1_rate,"
            "vendors:[{vendor_name,rate,delta_pct}], notes}], anomalies:[{severity,"
            "vendor_name,description,reason}], summary, recommendation}."
        ),
    })
    if attach_chunks:
        prompt += "\n\nAttached quotation documents:\n" + "\n\n".join(attach_chunks)
    raw, extras = await _call_llm("premium", system, prompt, u,
                                   kind="quotation_compare",
                                   entity=("po" if body.po_id else "mrf"),
                                   entity_id=(body.po_id or body.mrf_id or ""),
                                   input_payload={"quote_count": len(quotes),
                                                  "attachment_count": len(attach_chunks),
                                                  "attachments": attach_summary,
                                                  "record_number": body.po_id or body.mrf_id})
    parsed = _extract_json(raw) or {"error": "unparseable", "raw_excerpt": raw[:600]}
    doc = await _save_suggestion(
        "quotation_compare",
        entity=("po" if body.po_id else "mrf"),
        entity_id=body.po_id or body.mrf_id or "",
        user=u,
        input_payload={"quote_count": len(quotes), "attachment_count": len(attach_chunks),
                       "attachments": attach_summary},
        parsed=parsed, raw=raw,
        tier="premium", model=extras["model"], extras=extras,
    )
    return doc


# ---- 3) PO-GRN-Invoice Mismatch Detection (Sonnet / premium) ----------------

class ReconcileIn(BaseModel):
    po_id: str
    attachments: Optional[List[LlmAttachment]] = None  # e.g. vendor invoice PDFs


@api.post("/llm/reconcile")
async def llm_reconcile(body: ReconcileIn,
                        authorization: Optional[str] = Header(None)):
    """3-way reconciliation of a PO's line items against its GRNs and vendor
    invoices. Flags qty / rate / total mismatches. Read-only — no PO / GRN /
    invoice mutation. Purchase / GM / Director must accept exceptions."""
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_RECONCILE:
        raise HTTPException(403, "Not allowed")
    po = await db.pos.find_one({"po_id": body.po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, po)
    grns = await db.grns.find({"po_id": body.po_id}, {"_id": 0}).to_list(100)
    invs = await db.invoices.find({"po_id": body.po_id}, {"_id": 0}).to_list(100)
    # Minimise payload so we don't burn premium tokens
    po_slim = {
        "po_number": po.get("po_number"),
        "vendor_name": (po.get("vendor_name") or ""),
        "items": [
            {"line": i + 1, "description": it.get("description"),
             "qty": it.get("qty"), "unit": it.get("unit"),
             "rate": it.get("rate"), "gst": it.get("gst"),
             "hsn_code": it.get("hsn_code"),
             "qty_received": it.get("qty_received"),
             "material_uid": it.get("material_uid"),
             "variant_uid": it.get("variant_uid")}
            for i, it in enumerate(po.get("items") or [])
        ],
    }
    grn_slim = [{
        "grn_number": g.get("grn_number"), "date": str(g.get("date"))[:10],
        "status": g.get("status"),
        "items": [{"description": it.get("description"), "qty": it.get("qty"),
                   "unit": it.get("unit")} for it in (g.get("items") or [])],
    } for g in grns]
    inv_slim = [{
        "invoice_number": i.get("invoice_number"),
        "vendor_invoice_number": i.get("vendor_invoice_number"),
        "invoice_date": str(i.get("invoice_date"))[:10],
        "total": i.get("total"),
        "items": [{"description": it.get("description"), "qty": it.get("qty"),
                   "rate": it.get("rate"), "gst": it.get("gst")}
                  for it in (i.get("items") or [])],
    } for i in invs]

    system = (
        "You are a 3-way match auditor for Vasu Infosec accounts. Given a PO, "
        "its GRNs and vendor invoices, produce a per-line reconciliation and "
        "flag qty / rate / GST / total mismatches. Read-only. "
        "You DO NOT approve invoices, release payment, or update stock. "
        "Output STRICT JSON only."
    )
    prompt = _json.dumps({
        "po": po_slim, "grns": grn_slim, "invoices": inv_slim,
        "instructions": (
            "Return JSON: {po_number, per_line:[{line, description, po_qty, "
            "grn_qty, invoice_qty, po_rate, invoice_rate, qty_variance, "
            "rate_variance_pct, status:'match'|'over_delivered'|'under_delivered'"
            "|'rate_mismatch'|'gst_mismatch'|'not_invoiced'}], "
            "aggregate:{po_total, grn_total_est, invoice_total, delta}, "
            "exceptions:[{severity:'critical'|'warning'|'info', reason}], "
            "summary}. Be conservative — flag rather than assume."
        ),
    })
    # Append vendor invoice attachments (extracted text) if provided
    attach_summary: List[dict] = []
    if body.attachments:
        chunks: List[str] = []
        for att in body.attachments[:5]:
            text, kind = _extract_text_from_attachment(att.file_name, att.mime_type, att.file_base64)
            attach_summary.append({"file_name": att.file_name, "kind": kind, "chars": len(text)})
            if text:
                chunks.append(f"--- Vendor invoice: {att.file_name} ({kind}) ---\n{text}")
        if chunks:
            prompt += "\n\nAttached vendor invoices:\n" + "\n\n".join(chunks)
    raw, extras = await _call_llm("premium", system, prompt, u,
                                   kind="reconcile",
                                   entity="po", entity_id=body.po_id,
                                   input_payload={"po_number": po.get("po_number"),
                                                  "record_number": po.get("po_number"),
                                                  "grn_count": len(grns),
                                                  "invoice_count": len(invs),
                                                  "attachments": attach_summary})
    parsed = _extract_json(raw) or {"error": "unparseable", "raw_excerpt": raw[:600]}
    doc = await _save_suggestion(
        "reconcile", "po", body.po_id, u,
        input_payload={"po_number": po.get("po_number"),
                       "grn_count": len(grns), "invoice_count": len(invs),
                       "attachments": attach_summary},
        parsed=parsed, raw=raw,
        tier="premium", model=extras["model"], extras=extras,
    )
    return doc


# ---- Suggestions read / decide ---------------------------------------------

@api.get("/llm/suggestions")
async def list_suggestions(entity: Optional[str] = None,
                            entity_id: Optional[str] = None,
                            kind: Optional[str] = None,
                            status: Optional[str] = None,
                            limit: int = 100,
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_DECIDE:
        raise HTTPException(403, "Not allowed")
    q: Dict[str, Any] = {}
    if entity: q["entity"] = entity
    if entity_id: q["entity_id"] = entity_id
    if kind: q["kind"] = kind
    if status: q["status"] = status
    limit = max(1, min(int(limit or 100), 500))
    rows = await db.llm_suggestions.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return [_strip_oids(r) for r in rows]


@api.get("/llm/suggestions/{sug_id}")
async def get_suggestion(sug_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_DECIDE:
        raise HTTPException(403, "Not allowed")
    r = await db.llm_suggestions.find_one({"suggestion_id": sug_id}, {"_id": 0})
    if not r: raise HTTPException(404, "Suggestion not found")
    return _strip_oids(r)


@api.post("/llm/suggestions/{sug_id}/decide")
async def decide_suggestion(sug_id: str, body: Dict[str, Any] = Body(...),
                             authorization: Optional[str] = Header(None)):
    """Accept or reject an LLM suggestion.

    Accepting DOES NOT auto-mutate any workflow collection — it simply records
    the human decision in audit + suggestion row. The user must then act on
    the workflow via existing role-gated endpoints (e.g. use MAT-#### suggestion
    to fill in the MRF line via the existing MRF edit endpoint).
    """
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_DECIDE:
        raise HTTPException(403, "Not allowed")
    action = (body.get("action") or "").lower()
    if action not in ("accept", "reject"):
        raise HTTPException(400, "action must be 'accept' or 'reject'")
    r = await db.llm_suggestions.find_one({"suggestion_id": sug_id}, {"_id": 0})
    if not r: raise HTTPException(404, "Suggestion not found")
    if r.get("status") != "pending_review":
        raise HTTPException(400, f"Cannot {action}: suggestion is '{r.get('status')}'")
    new_status = "accepted" if action == "accept" else "rejected"
    await db.llm_suggestions.update_one(
        {"suggestion_id": sug_id},
        {"$set": {"status": new_status,
                  "decision": action,
                  "decided_by": u.user_id,
                  "decided_by_name": u.name,
                  "decided_at": now_utc(),
                  "decision_reason": body.get("reason") or ""}},
    )
    await audit("llm_suggestion", sug_id, f"llm_{action}", u,
                {"kind": r.get("kind"),
                 "record_number": r.get("input_summary", {}).get("record_number", ""),
                 "old_value": {"status": "pending_review"},
                 "new_value": {"status": new_status},
                 "reason": body.get("reason") or ""})
    return await db.llm_suggestions.find_one({"suggestion_id": sug_id}, {"_id": 0})


# ---------------------- End LLM Co-pilot ----------------------
