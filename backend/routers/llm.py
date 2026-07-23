"""LLM Co-pilot router — extracted from server.py in Phase 9C for maintainability.

This module is imported at the end of server.py *for its side effects*: it
attaches all /api/llm/* endpoints to the shared APIRouter. It intentionally
imports names from server.py at import time — safe because server.py imports
this module AFTER defining `api`, `db`, `audit`, etc.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
import os
import uuid
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
#   premium          = Anthropic Sonnet 4.5   — Director role only.
# Haiku was removed (~5x more expensive per output token than gpt-4o-mini).
_LLM_MODELS = {
    "cheap": ("openai", "gpt-4o-mini"),
    "premium": ("anthropic", "claude-sonnet-4-5-20250929"),
}

# --------------------------------------------------------------------------
# Cost-control (from user directive, message 618):
#
#   * Director            → no monthly cap, may pick any tier (cheap OR premium)
#   * All other AI roles  → ₹200/month cap, `cheap` tier only.
#                           If they request `premium` we SILENTLY downgrade
#                           to `cheap` and surface a flag on the response so
#                           the UI can show "analyzed with cost-optimised model".
#                           When the ₹200 monthly wallet is exhausted, further
#                           LLM calls return HTTP 402 with a clear payload.
#
# Deterministic (LLM-free) mode is always available for everyone and never
# touches this budget.
# --------------------------------------------------------------------------
MONTHLY_BUDGET_INR: Dict[str, Optional[float]] = {
    "director":       None,     # unlimited
    "gm":             200.0,
    "pm":             200.0,
    "admin":          200.0,
    "purchase":       200.0,
    "site_engineer":  200.0,
    "store":          200.0,
}
PREMIUM_ALLOWED_ROLES = {"director"}

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


def _month_start_utc() -> Any:
    n = now_utc()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _user_month_spend_inr(user_id: str) -> float:
    """Sum of cost.cost_inr from llm_suggestions for this user this calendar
    month. Cached-hits contribute ₹0 because their cost is stored as 0.

    Also includes any un-settled *reservations* from `llm_budget_reservations`
    (see `_enforce_tier_and_budget`) so concurrent in-flight calls cannot
    each pass the budget check before their cost has been recorded.
    """
    start = _month_start_utc()
    pipeline = [
        {"$match": {"created_by": user_id, "created_at": {"$gte": start}}},
        {"$group": {"_id": None, "total": {"$sum": "$cost.cost_inr"}}},
    ]
    try:
        rows = await db.llm_suggestions.aggregate(pipeline).to_list(1)
        spent = float(rows[0]["total"]) if rows else 0.0
    except Exception:
        spent = 0.0
    # Add live reservations (racy in-flight calls)
    try:
        res_rows = await db.llm_budget_reservations.aggregate([
            {"$match": {"user_id": user_id,
                         "created_at": {"$gte": start},
                         "settled": {"$ne": True}}},
            {"$group": {"_id": None, "total": {"$sum": "$reserved_inr"}}},
        ]).to_list(1)
        reserved = float(res_rows[0]["total"]) if res_rows else 0.0
    except Exception:
        reserved = 0.0
    return round(spent + reserved, 4)


async def _budget_status(user: UserOut) -> Dict[str, Any]:
    limit = MONTHLY_BUDGET_INR.get(user.role, 200.0)
    spent = await _user_month_spend_inr(user.user_id)
    remaining = None if limit is None else round(max(0.0, limit - spent), 4)
    return {
        "role": user.role,
        "unlimited": limit is None,
        "limit_inr": limit,
        "spent_inr": spent,
        "remaining_inr": remaining,
        "period": _month_start_utc().strftime("%Y-%m"),
        "premium_allowed": user.role in PREMIUM_ALLOWED_ROLES,
    }


async def _enforce_tier_and_budget(user: UserOut, requested_tier: str) -> Tuple[str, Dict[str, Any]]:
    """Central cost-control gate.

    * Non-director asking for `premium` → silent downgrade to `cheap`.
    * Non-director whose monthly ₹ cap is exhausted → HTTP 402.
    * Director → always allowed at requested tier, no cap.

    Race-safety (SEC hardening):
      A short-lived *reservation* is written to `llm_budget_reservations`
      BEFORE the LLM call, and its amount counts against `spent_inr` via
      `_user_month_spend_inr()` for the duration of the call. This closes
      the concurrent-request window where two calls could each pass the
      budget check before either had settled. Reservations are settled
      (or discarded on failure) by `_call_llm`.

    Returns: (effective_tier, tier_meta) — `tier_meta` includes the
    `reservation_id` when a reservation was written.
    """
    meta: Dict[str, Any] = {
        "requested_tier": requested_tier,
        "effective_tier": requested_tier,
        "downgraded": False,
        "downgrade_reason": None,
        "reservation_id": None,
    }
    effective = requested_tier

    if requested_tier == "premium" and user.role not in PREMIUM_ALLOWED_ROLES:
        effective = "cheap"
        meta["effective_tier"] = "cheap"
        meta["downgraded"] = True
        meta["downgrade_reason"] = (
            "Premium (Claude Sonnet 4.5) is restricted to the Director role. "
            "Analysed with the cost-optimised model (gpt-4o-mini) instead."
        )

    budget = await _budget_status(user)
    meta["budget_before"] = budget
    if not budget["unlimited"] and (budget["remaining_inr"] or 0.0) <= 0:
        raise HTTPException(
            402,
            {
                "error": "monthly_ai_budget_exhausted",
                "role": user.role,
                "spent_inr": budget["spent_inr"],
                "limit_inr": budget["limit_inr"],
                "period": budget["period"],
                "message": (
                    f"Monthly AI budget of ₹{budget['limit_inr']} for role "
                    f"'{user.role}' is exhausted (₹{budget['spent_inr']} used). "
                    "Try the free Deterministic mode, or ask the Director to run this."
                ),
            },
        )

    # SEC race-safety: reserve the maximum plausible cost for this call.
    # 5% of the remaining monthly budget or ₹5, whichever is larger, capped at
    # ₹25. If the actual cost is lower, the reservation is settled to the
    # exact number; if higher (rare), the settle overwrites with the true value.
    if not budget["unlimited"]:
        remaining = float(budget["remaining_inr"] or 0.0)
        reserved = max(5.0, min(25.0, round(remaining * 0.05, 4)))
        rid = f"res_{uuid.uuid4().hex[:12]}"
        await db.llm_budget_reservations.insert_one({
            "reservation_id": rid,
            "user_id": user.user_id,
            "role": user.role,
            "reserved_inr": reserved,
            "created_at": now_utc(),
            "settled": False,
        })
        meta["reservation_id"] = rid
        meta["reserved_inr"] = reserved

    return effective, meta


async def _settle_budget_reservation(reservation_id: Optional[str],
                                      actual_cost_inr: float) -> None:
    """Mark a reservation settled with the true cost. Idempotent."""
    if not reservation_id:
        return
    try:
        await db.llm_budget_reservations.update_one(
            {"reservation_id": reservation_id, "settled": {"$ne": True}},
            {"$set": {"settled": True, "settled_at": now_utc(),
                      "actual_inr": round(float(actual_cost_inr or 0.0), 4)}},
        )
    except Exception:
        pass


async def _release_budget_reservation(reservation_id: Optional[str]) -> None:
    """Delete a reservation whose call errored out (nothing was spent).
    Idempotent."""
    if not reservation_id:
        return
    try:
        await db.llm_budget_reservations.delete_one({"reservation_id": reservation_id})
    except Exception:
        pass


async def _call_llm(tier: str, system: str, user_text: str,
                    user: UserOut, kind: str,
                    entity: str, entity_id: str,
                    input_payload: dict) -> Tuple[str, dict]:
    """Call the LLM with the given prompt and audit-log the invocation.

    Returns: (raw_text, audit_extras).
    Raises HTTPException(500) if the key is missing.
    Raises HTTPException(402) if this user has exhausted their monthly budget.
    """
    if not EMERGENT_LLM_KEY:
        raise HTTPException(500, "EMERGENT_LLM_KEY not configured on server")
    # Central cost-control gate (writes a reservation for race-safety)
    effective_tier, tier_meta = await _enforce_tier_and_budget(user, tier)
    reservation_id = tier_meta.get("reservation_id")
    tier = effective_tier
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
        # Cache hit — no cost, release the reservation
        await _release_budget_reservation(reservation_id)
        return cached["response"], {"cached": True, "tier": tier, "model": model,
                                      "hash": h, "cost": cb,
                                      "tier_meta": tier_meta}
    session_id = f"vasu_{kind}_{gid('sess')[:16]}"
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id,
                   system_message=system).with_model(provider, model)
    try:
        resp = await chat.send_message(UserMessage(text=user_text))
    except Exception as e:
        # Fail closed — do not fabricate suggestions AND release the reservation
        await _release_budget_reservation(reservation_id)
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
        "tier_meta": tier_meta,
    }
    # Settle the reservation with the true cost so subsequent budget checks
    # see the exact figure (not the conservative reserved amount).
    await _settle_budget_reservation(reservation_id, float(cost.get("cost_inr") or 0.0))
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


# ---- 2) Quotation Comparison (deterministic OR gpt-4o-mini — Sonnet retired) -

class QuotationCompareIn(BaseModel):
    mrf_id: Optional[str] = ""
    po_id: Optional[str] = ""
    context: Optional[str] = ""
    quotes: Optional[List[Dict[str, Any]]] = None  # [{vendor_name, currency, items:[...]}]
    attachments: Optional[List[LlmAttachment]] = None  # PDF/Excel/CSV vendor quotes to auto-parse
    # Cost tiers — as of iter-28 the premium (Sonnet 4.5) tier is retired for
    # Compare. Choose between:
    #   deterministic → LLM-free math ranking (₹0). Uses the structured quotes
    #                   payload directly (skips file text extraction).
    #   cheap         → gpt-4o-mini (default; ~₹0.05–₹0.20/call).
    tier: Optional[str] = "cheap"


def _deterministic_compare(quotes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank vendors by line-item totals. LLM-free.

    Each quote is `{vendor_name, items:[{description, qty, rate, gst?, discount?}]}`.
    We compute per-vendor totals, delta% vs L1, per-item delta, and flag
    numeric anomalies (missing rate, huge deviation from mean).
    """
    ranking: List[Dict[str, Any]] = []
    for q in quotes:
        items = q.get("items") or []
        total_taxable = 0.0
        total_with_tax = 0.0
        for it in items:
            qty = float(it.get("qty") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst = float(it.get("gst") or 0)
            taxable = max(0.0, qty * rate - disc)
            with_tax = taxable * (1 + gst / 100.0)
            total_taxable += taxable
            total_with_tax += with_tax
        ranking.append({
            "vendor_name": q.get("vendor_name") or "(unnamed)",
            "total_taxable": round(total_taxable, 2),
            "total_with_tax": round(total_with_tax, 2),
        })
    ranking.sort(key=lambda r: r["total_with_tax"] if r["total_with_tax"] > 0 else 9e18)
    l1 = ranking[0]["total_with_tax"] if ranking and ranking[0]["total_with_tax"] > 0 else 0
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
        r["delta_pct_vs_L1"] = round((r["total_with_tax"] - l1) / l1 * 100.0, 2) if l1 else None

    # ---- Per-line comparison ----
    all_descriptions: Dict[str, Dict[str, Any]] = {}
    for q in quotes:
        vendor = q.get("vendor_name") or "(unnamed)"
        for it in (q.get("items") or []):
            desc = (it.get("description") or "").strip()
            if not desc:
                continue
            row = all_descriptions.setdefault(desc, {"description": desc, "vendors": {}})
            row["vendors"][vendor] = {
                "rate": float(it.get("rate") or 0),
                "qty": float(it.get("qty") or 0),
                "gst": float(it.get("gst") or 0),
            }

    line_comparison: List[Dict[str, Any]] = []
    for desc, row in all_descriptions.items():
        rates = [v["rate"] for v in row["vendors"].values() if v["rate"] > 0]
        min_rate = min(rates) if rates else 0
        l1_vendor = next((v for v, d in row["vendors"].items() if d["rate"] == min_rate), None) if rates else None
        vendors_out = []
        for vname, d in row["vendors"].items():
            delta = round((d["rate"] - min_rate) / min_rate * 100.0, 2) if min_rate else None
            vendors_out.append({"vendor_name": vname, "rate": d["rate"],
                                  "qty": d["qty"], "gst": d["gst"],
                                  "delta_pct": delta})
        line_comparison.append({
            "description": desc,
            "l1_vendor": l1_vendor, "l1_rate": min_rate,
            "vendors": vendors_out,
            "notes": ("" if l1_vendor else "no valid rate provided"),
        })

    # ---- Anomalies: rate outliers (>50% above per-line mean) ----
    anomalies: List[Dict[str, Any]] = []
    for row in line_comparison:
        rates = [v["rate"] for v in row["vendors"] if v.get("rate", 0) > 0]
        if len(rates) < 2:
            continue
        mean = sum(rates) / len(rates)
        for v in row["vendors"]:
            r = v.get("rate", 0)
            if r > mean * 1.5 and mean > 0:
                anomalies.append({
                    "severity": "warning", "vendor_name": v["vendor_name"],
                    "description": row["description"],
                    "reason": f"Rate ₹{r} is {round((r - mean) / mean * 100)}% above the average ₹{round(mean, 2)} for this item.",
                })
    # Vendors missing lines that others quoted
    all_vendors = {q.get("vendor_name") or "(unnamed)" for q in quotes}
    for row in line_comparison:
        provided = {v["vendor_name"] for v in row["vendors"]}
        missing = all_vendors - provided
        for m in missing:
            anomalies.append({
                "severity": "info", "vendor_name": m,
                "description": row["description"],
                "reason": "Vendor did not quote this line.",
            })

    if ranking and len(ranking) > 1:
        l1_total = ranking[0]["total_with_tax"]
        l2_total = ranking[1]["total_with_tax"]
        cheaper_by = round((l2_total - l1_total) / l2_total * 100.0, 2) if l2_total else 0
        recommendation = (
            f"Award to {ranking[0]['vendor_name']} at ₹{l1_total:,.2f} — "
            f"{cheaper_by}% cheaper than the next bidder ({ranking[1]['vendor_name']} @ ₹{l2_total:,.2f})."
        )
    elif ranking:
        recommendation = "Only 1 valid quote — negotiate before award."
    else:
        recommendation = "No valid quotes."

    return {
        "ranking": ranking,
        "line_comparison": line_comparison,
        "anomalies": anomalies,
        "summary": f"Deterministic comparison across {len(quotes)} vendors, {len(line_comparison)} line(s).",
        "recommendation": recommendation,
        "_engine": "deterministic",
    }


@api.post("/llm/quotation-compare")
async def llm_quotation_compare(body: QuotationCompareIn,
                                 authorization: Optional[str] = Header(None)):
    """Produce an L1/L2/L3 side-by-side comparison with delta % and
    recommendations. Suggestions only — Purchase / PM must accept/reject."""
    u = await get_current_user(authorization)
    if u.role not in LLM_ROLES_COMPARE:
        raise HTTPException(403, "Not allowed")
    quotes = body.quotes or []
    tier = (body.tier or "cheap").lower()
    # Sonnet 4.5 is disallowed here as of iter-28 — silently downshift.
    if tier == "premium":
        tier = "cheap"
    attach_summary: List[dict] = []
    attach_chunks: List[str] = []
    if body.attachments and tier != "deterministic":
        # Enforce hard cap BEFORE any expensive processing.
        if len(body.attachments) > 8:
            raise HTTPException(400, "Max 8 vendor quote attachments per comparison")
        for att in body.attachments:
            text, kind = _extract_text_from_attachment(att.file_name, att.mime_type, att.file_base64)
            attach_summary.append({"file_name": att.file_name, "kind": kind, "chars": len(text)})
            if text:
                attach_chunks.append(f"--- Quotation file: {att.file_name} ({kind}) ---\n{text}")
    # Deterministic path only needs structured quotes (no file OCR/LLM).
    if tier == "deterministic":
        if len(quotes) < 2:
            raise HTTPException(400, "Deterministic mode needs at least 2 structured quotes")
        parsed = _deterministic_compare(quotes)
        cost0 = {"model": "deterministic", "input_tokens_approx": 0,
                  "output_tokens_approx": 0, "input_rate_usd_per_m": 0,
                  "output_rate_usd_per_m": 0, "cost_usd": 0.0, "cost_inr": 0.0,
                  "cache_saved": False}
        doc = await _save_suggestion(
            "quotation_compare",
            entity=("po" if body.po_id else "mrf"),
            entity_id=body.po_id or body.mrf_id or "",
            user=u,
            input_payload={"quote_count": len(quotes), "attachment_count": 0,
                            "attachments": [], "tier": "deterministic"},
            parsed=parsed, raw="",
            tier="deterministic", model="deterministic",
            extras={"tier": "deterministic", "model": "deterministic",
                    "cost": cost0, "hash": "det",
                    "tier_meta": {"requested_tier": "deterministic",
                                   "effective_tier": "deterministic",
                                   "downgraded": False}},
        )
        return doc
    # LLM path: require ≥2 structured quotes OR ≥2 attachments
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
    raw, extras = await _call_llm(tier, system, prompt, u,
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
                       "attachments": attach_summary, "tier": tier},
        parsed=parsed, raw=raw,
        tier=tier, model=extras["model"], extras=extras,
    )
    return doc


# ---- 3) PO-GRN-Invoice Mismatch Detection (deterministic OR gpt-4o-mini) ----

class ReconcileIn(BaseModel):
    po_id: str
    attachments: Optional[List[LlmAttachment]] = None  # e.g. vendor invoice PDFs
    # Iter-28: Sonnet retired. Choose deterministic (pure arithmetic diff) or
    # cheap (gpt-4o-mini narrative).
    tier: Optional[str] = "cheap"


def _deterministic_reconcile(po: dict, grns: List[dict], invs: List[dict]) -> Dict[str, Any]:
    """Pure-arithmetic 3-way match. Compares PO qty/rate against summed GRN qty
    and summed invoice qty/rate — no LLM."""
    def _canon(s):
        return (s or "").strip().lower()

    # Aggregate GRN qty by description
    grn_qty_by_desc: Dict[str, float] = {}
    for g in grns:
        for it in (g.get("items") or []):
            grn_qty_by_desc[_canon(it.get("description"))] = grn_qty_by_desc.get(
                _canon(it.get("description")), 0.0) + float(it.get("qty") or 0)

    # Aggregate invoice qty/rate by description
    inv_by_desc: Dict[str, Dict[str, float]] = {}
    for i in invs:
        for it in (i.get("items") or []):
            d = _canon(it.get("description"))
            row = inv_by_desc.setdefault(d, {"qty": 0.0, "rate": 0.0, "gst": 0.0, "n": 0})
            row["qty"] += float(it.get("qty") or 0)
            row["rate"] += float(it.get("rate") or 0)
            row["gst"] += float(it.get("gst") or 0)
            row["n"] += 1

    per_line: List[Dict[str, Any]] = []
    exceptions: List[Dict[str, Any]] = []
    po_total = 0.0
    grn_total_est = 0.0
    inv_total_est = 0.0
    for idx, it in enumerate(po.get("items") or []):
        desc = it.get("description") or ""
        d = _canon(desc)
        po_qty = float(it.get("qty") or 0)
        po_rate = float(it.get("rate") or 0)
        po_gst = float(it.get("gst") or 0)
        po_line_total = po_qty * po_rate * (1 + po_gst / 100.0)
        po_total += po_line_total

        grn_qty = grn_qty_by_desc.get(d, 0.0)
        grn_total_est += grn_qty * po_rate * (1 + po_gst / 100.0)

        inv_row = inv_by_desc.get(d)
        inv_qty = inv_row["qty"] if inv_row else 0.0
        inv_rate = (inv_row["rate"] / max(1, inv_row["n"])) if inv_row else 0.0
        inv_gst = (inv_row["gst"] / max(1, inv_row["n"])) if inv_row else 0.0
        inv_line_total = inv_qty * inv_rate * (1 + inv_gst / 100.0)
        inv_total_est += inv_line_total

        # Compute variances
        qty_variance = round(inv_qty - po_qty, 3) if inv_qty else round(grn_qty - po_qty, 3)
        rate_variance_pct = round((inv_rate - po_rate) / po_rate * 100.0, 2) if (po_rate and inv_rate) else None

        status = "match"
        if not inv_row and not grn_qty:
            status = "not_invoiced"
        elif inv_qty > po_qty * 1.001:
            status = "over_delivered"
        elif inv_qty and inv_qty < po_qty * 0.999:
            status = "under_delivered"
        elif rate_variance_pct is not None and abs(rate_variance_pct) > 0.5:
            status = "rate_mismatch"
        elif inv_gst and abs(inv_gst - po_gst) > 0.01:
            status = "gst_mismatch"

        per_line.append({
            "line": idx + 1, "description": desc,
            "po_qty": po_qty, "grn_qty": grn_qty, "invoice_qty": inv_qty,
            "po_rate": po_rate, "invoice_rate": inv_rate,
            "qty_variance": qty_variance,
            "rate_variance_pct": rate_variance_pct,
            "status": status,
        })
        if status == "rate_mismatch":
            exceptions.append({"severity": "critical", "reason": f"Line {idx + 1} '{desc}': invoice rate ₹{inv_rate} vs PO rate ₹{po_rate} ({rate_variance_pct}% deviation)."})
        elif status == "over_delivered":
            exceptions.append({"severity": "warning", "reason": f"Line {idx + 1} '{desc}': over-delivered by {round(inv_qty - po_qty, 3)} {it.get('unit') or ''}."})
        elif status == "under_delivered":
            exceptions.append({"severity": "warning", "reason": f"Line {idx + 1} '{desc}': under-delivered by {round(po_qty - inv_qty, 3)} {it.get('unit') or ''}."})
        elif status == "not_invoiced" and po_qty > 0:
            exceptions.append({"severity": "info", "reason": f"Line {idx + 1} '{desc}': not received, not invoiced yet."})
        elif status == "gst_mismatch":
            exceptions.append({"severity": "critical", "reason": f"Line {idx + 1} '{desc}': GST% mismatch (PO {po_gst}% vs invoice {inv_gst}%)."})

    inv_total_actual = sum(float(i.get("total") or 0) for i in invs) or inv_total_est
    delta = round(inv_total_actual - po_total, 2)
    summary_bits = [f"{sum(1 for r in per_line if r['status'] == 'match')} of {len(per_line)} lines matched cleanly."]
    if exceptions:
        summary_bits.append(f"{len(exceptions)} exception(s) — see details.")
    return {
        "po_number": po.get("po_number"),
        "per_line": per_line,
        "aggregate": {
            "po_total": round(po_total, 2),
            "grn_total_est": round(grn_total_est, 2),
            "invoice_total": round(inv_total_actual, 2),
            "delta": delta,
        },
        "exceptions": exceptions,
        "summary": " ".join(summary_bits),
        "_engine": "deterministic",
    }


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

    tier = (body.tier or "cheap").lower()
    if tier == "premium":
        tier = "cheap"  # Sonnet retired for Reconcile in iter-28

    # ─── Deterministic (LLM-free) path ────────────────────────────
    if tier == "deterministic":
        parsed = _deterministic_reconcile(po, grns, invs)
        cost0 = {"model": "deterministic", "input_tokens_approx": 0,
                  "output_tokens_approx": 0, "input_rate_usd_per_m": 0,
                  "output_rate_usd_per_m": 0, "cost_usd": 0.0, "cost_inr": 0.0,
                  "cache_saved": False}
        doc = await _save_suggestion(
            "reconcile", "po", body.po_id, u,
            input_payload={"po_number": po.get("po_number"),
                            "grn_count": len(grns), "invoice_count": len(invs),
                            "attachments": [], "tier": "deterministic"},
            parsed=parsed, raw="",
            tier="deterministic", model="deterministic",
            extras={"tier": "deterministic", "model": "deterministic",
                    "cost": cost0, "hash": "det",
                    "tier_meta": {"requested_tier": "deterministic",
                                   "effective_tier": "deterministic",
                                   "downgraded": False}},
        )
        return doc

    # Minimise payload so we don't burn cheap tokens either
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
    raw, extras = await _call_llm(tier, system, prompt, u,
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
                       "attachments": attach_summary, "tier": tier},
        parsed=parsed, raw=raw,
        tier=tier, model=extras["model"], extras=extras,
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


# ---------------------- Cost-Control & Admin Spend ----------------------

@api.get("/llm/my-budget")
async def my_budget(authorization: Optional[str] = Header(None)):
    """Return the caller's monthly AI budget status.

    Response:
      {role, unlimited, limit_inr, spent_inr, remaining_inr, period,
       premium_allowed}

    Frontend uses this to show a "wallet" chip in the AI Co-pilot header and
    to greying-out the premium tier chip for non-directors.
    """
    u = await get_current_user(authorization)
    return await _budget_status(u)


@api.get("/llm/admin/spend-monthly")
async def admin_spend_monthly(months: int = 6,
                              authorization: Optional[str] = Header(None)):
    """Per-month, per-user, per-model AI spend rollup for the last `months`
    calendar months. Admin & Director only.

    Response:
      {
        "period_range": [{"month": "2026-06", "spent_inr": 12.34,
                            "calls": 42}, ...],
        "by_user":    [{"user_id": "...", "name": "...", "role": "...",
                         "spent_inr_this_month": 3.4, "limit_inr": 200,
                         "remaining_inr": 196.6, "calls_this_month": 5}, ...],
        "by_model":   [{"model": "gpt-4o-mini", "spent_inr": ..., "calls": ...}]
      }
    """
    u = await get_current_user(authorization)
    if u.role not in {"admin", "director"}:
        raise HTTPException(403, "Admin or Director only")
    months = max(1, min(int(months or 6), 24))
    # ---- 1) monthly totals over the last N months
    now = now_utc()
    lookback = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(months - 1):
        # rewind by one month
        if lookback.month == 1:
            lookback = lookback.replace(year=lookback.year - 1, month=12)
        else:
            lookback = lookback.replace(month=lookback.month - 1)
    monthly_pipeline = [
        {"$match": {"created_at": {"$gte": lookback}}},
        {"$addFields": {
            "ym": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}}
        }},
        {"$group": {
            "_id": "$ym",
            "spent_inr": {"$sum": "$cost.cost_inr"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    period_rows = await db.llm_suggestions.aggregate(monthly_pipeline).to_list(months)
    period_range = [
        {"month": r["_id"],
         "spent_inr": round(float(r.get("spent_inr") or 0), 4),
         "calls": int(r.get("calls") or 0)}
        for r in period_rows
    ]
    # ---- 2) this-month per-user rollup
    ms = _month_start_utc()
    user_pipeline = [
        {"$match": {"created_at": {"$gte": ms}}},
        {"$group": {
            "_id": "$created_by",
            "name": {"$first": "$created_by_name"},
            "role": {"$first": "$created_by_role"},
            "spent_inr": {"$sum": "$cost.cost_inr"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"spent_inr": -1}},
    ]
    user_rows = await db.llm_suggestions.aggregate(user_pipeline).to_list(500)
    by_user = []
    for r in user_rows:
        role = r.get("role") or ""
        limit = MONTHLY_BUDGET_INR.get(role, 200.0)
        spent = round(float(r.get("spent_inr") or 0), 4)
        remaining = None if limit is None else round(max(0.0, limit - spent), 4)
        by_user.append({
            "user_id": r["_id"],
            "name": r.get("name") or r["_id"],
            "role": role,
            "spent_inr_this_month": spent,
            "limit_inr": limit,
            "unlimited": limit is None,
            "remaining_inr": remaining,
            "calls_this_month": int(r.get("calls") or 0),
        })
    # ---- 3) this-month per-model breakdown
    model_pipeline = [
        {"$match": {"created_at": {"$gte": ms}}},
        {"$group": {
            "_id": "$model",
            "spent_inr": {"$sum": "$cost.cost_inr"},
            "calls": {"$sum": 1},
        }},
        {"$sort": {"spent_inr": -1}},
    ]
    model_rows = await db.llm_suggestions.aggregate(model_pipeline).to_list(20)
    by_model = [
        {"model": r["_id"] or "unknown",
         "spent_inr": round(float(r.get("spent_inr") or 0), 4),
         "calls": int(r.get("calls") or 0)}
        for r in model_rows
    ]
    grand_total = round(sum(r["spent_inr"] for r in by_model), 4)
    return {
        "period_start_this_month": ms.strftime("%Y-%m"),
        "grand_total_inr_this_month": grand_total,
        "period_range": period_range,
        "by_user": by_user,
        "by_model": by_model,
        "budget_config": {
            k: v for k, v in MONTHLY_BUDGET_INR.items()
        },
        "premium_allowed_roles": sorted(list(PREMIUM_ALLOWED_ROLES)),
    }


# ---------------------- Supplier Performance ----------------------

@api.get("/llm/admin/supplier-performance")
async def admin_supplier_performance(limit: int = 100,
                                       authorization: Optional[str] = Header(None)):
    """Simple, deterministic supplier-performance rollup based on internal
    workflow data — no LLM cost, no complex scoring.

    Metrics per vendor:
      - completed_orders: POs with status in {'received','closed'}
      - open_orders: POs with status in {'issued','partially_received'}
      - rejected_grns: GRNs with status == 'rejected'
      - total_grns
      - on_time_pct: % of GRNs where grn.date <= po.expected_delivery
      - avg_delay_days: mean delay days for late GRNs
      - last_order_date
      - total_ordered_value

    Admin, Director, GM, Purchase can view.
    """
    u = await get_current_user(authorization)
    if u.role not in {"admin", "director", "gm", "purchase"}:
        raise HTTPException(403, "Not allowed")

    vendors = await db.vendors.find({}, {"_id": 0}).to_list(2000)
    pos = await db.pos.find({"deleted": False}, {"_id": 0}).to_list(5000)
    grns = await db.grns.find({}, {"_id": 0}).to_list(10000)

    po_by_id = {p["po_id"]: p for p in pos if p.get("po_id")}
    v_by_id = {v["vendor_id"]: v for v in vendors if v.get("vendor_id")}

    stats: Dict[str, Dict[str, Any]] = {}
    for p in pos:
        vid = p.get("vendor_id") or "_unassigned"
        rec = stats.setdefault(vid, {
            "vendor_id": vid,
            "vendor_name": p.get("vendor_name") or (v_by_id.get(vid, {}).get("name") if vid != "_unassigned" else ""),
            "total_orders": 0,
            "completed_orders": 0,
            "open_orders": 0,
            "total_ordered_value_inr": 0.0,
            "total_grns": 0,
            "rejected_grns": 0,
            "on_time_grns": 0,
            "late_grns": 0,
            "delay_days_sum": 0,
            "last_order_date": None,
        })
        rec["total_orders"] += 1
        status = (p.get("status") or "").lower()
        if status in ("received", "closed"):
            rec["completed_orders"] += 1
        elif status in ("issued", "partially_received", "approved"):
            rec["open_orders"] += 1
        rec["total_ordered_value_inr"] += float(p.get("total") or 0)
        pd = p.get("date") or p.get("created_at")
        if pd:
            if not rec["last_order_date"] or str(pd) > str(rec["last_order_date"]):
                rec["last_order_date"] = pd

    for g in grns:
        po = po_by_id.get(g.get("po_id"))
        if not po:
            continue
        vid = po.get("vendor_id") or "_unassigned"
        rec = stats.get(vid)
        if not rec:
            continue
        rec["total_grns"] += 1
        if (g.get("status") or "").lower() == "rejected":
            rec["rejected_grns"] += 1
        # On-time check — expected_delivery is optional on the PO
        exp = po.get("expected_delivery") or po.get("delivery_date")
        gd = g.get("date") or g.get("created_at")
        if exp and gd:
            try:
                exp_s = str(exp)[:10]
                gd_s = str(gd)[:10]
                if gd_s <= exp_s:
                    rec["on_time_grns"] += 1
                else:
                    rec["late_grns"] += 1
                    # naive delay in days
                    try:
                        from datetime import datetime as _dt
                        d1 = _dt.strptime(exp_s, "%Y-%m-%d")
                        d2 = _dt.strptime(gd_s, "%Y-%m-%d")
                        rec["delay_days_sum"] += max(0, (d2 - d1).days)
                    except Exception:
                        pass
            except Exception:
                pass

    out = []
    for rec in stats.values():
        if rec["vendor_id"] == "_unassigned":
            continue
        on_time_denom = rec["on_time_grns"] + rec["late_grns"]
        on_time_pct = (rec["on_time_grns"] * 100.0 / on_time_denom) if on_time_denom else None
        avg_delay = (rec["delay_days_sum"] / rec["late_grns"]) if rec["late_grns"] else 0.0
        out.append({
            "vendor_id": rec["vendor_id"],
            "vendor_name": rec["vendor_name"],
            "total_orders": rec["total_orders"],
            "completed_orders": rec["completed_orders"],
            "open_orders": rec["open_orders"],
            "total_ordered_value_inr": round(rec["total_ordered_value_inr"], 2),
            "total_grns": rec["total_grns"],
            "rejected_grns": rec["rejected_grns"],
            "on_time_pct": round(on_time_pct, 1) if on_time_pct is not None else None,
            "avg_delay_days": round(avg_delay, 1),
            "last_order_date": str(rec["last_order_date"])[:10] if rec["last_order_date"] else None,
        })
    out.sort(key=lambda r: (-(r["completed_orders"] or 0),
                              -(r["total_ordered_value_inr"] or 0)))
    return out[:max(1, min(int(limit or 100), 500))]


# ---------------------- End LLM Co-pilot ----------------------
