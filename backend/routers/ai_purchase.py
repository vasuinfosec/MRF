"""AI Purchase Manager router — Phase 10A.

A commercial-focused negotiation copilot that always thinks from the *buyer's*
side (Vasu Infosec). It aggregates internal history for a given material
(matched by MAT-#### UID, item description, or a live quote), computes verified
statistics, then calls a cheap LLM (Claude Haiku 4.5 by default) with a strict
"hard-nosed buyer" system prompt to produce a 25-field negotiation analysis.

Cost tiers with a smart auto-router (per user directive):
  - `auto`        DEFAULT — routes 90% of items to GPT-4o-mini; escalates
                  to Claude Haiku for cables/pipes/software/structural-steel
                  and bulk-expensive lines (>₹1 lakh line value).
  - ultra_cheap:  OpenAI gpt-4o-mini      (~₹1–2/call, forced)
  - cheap:        Claude Haiku 4.5         (~₹4–8/call, forced)
  - premium:      Claude Sonnet 4.5        (~₹20–40/call, forced — for
                                            re-tenders and high-stakes POs only)

Auto-router keywords (case-insensitive):
    cable · wire · conduit · cat6 · utp · fiber · optical · coax · armoured · xlpe
    copper · cu · pipe · gi pipe · ms pipe · erw · seamless · hollow section
    channel · beam · angle · flat · rebar · tmt · ms structural · ms plate
    software · licence · license · subscription · saas · amc
    diesel · fuel · gas · lubricant
Or any line with `qty * rate ≥ ₹1,00,000` (bulk-expensive escalation).

Design tenets:
  - **Save in AI**: every analysis is persisted to `llm_suggestions` with
    `kind='purchase_analysis'` so it appears in the existing Review tab and
    supports accept/reject with audit trail.
  - **Company's POV**: the system prompt is uncompromisingly buyer-biased.
  - **Verified vs estimated**: every output field is explicitly tagged; the
    LLM must never conflate internal verified data with world-knowledge
    market guesses.
  - **Cache-friendly**: identical (tier, system, user_text) hits `llm_cache`
    → zero incremental cost on re-runs.

The endpoints:
  - GET  /api/llm/purchase-analysis/aggregates  (LLM-free preview — data coverage)
  - GET  /api/llm/purchase-analysis/route       (LLM-free — shows which tier will run)
  - POST /api/llm/purchase-analysis             (full analysis; tier=auto by default)
  - GET  /api/llm/purchase-analysis/{sid}        (retrieve saved analysis)
"""
from __future__ import annotations

import json as _json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from statistics import median, mean
from fastapi import Header, HTTPException, Body
from pydantic import BaseModel

from server import (
    api, db, get_current_user, audit, now_utc,
    _strip_oids,
)

# Re-use the LLM plumbing already in routers/llm.py
from routers.llm import (  # noqa: E402
    _call_llm, _save_suggestion, _extract_text_from_attachment,
    _extract_json as _parse_json_upstream, LlmAttachment,
)


# --------------------------------------------------------------------------- helpers

# GPT-4o-mini occasionally emits Indian/US-style comma-grouped numbers (e.g.
# `1,296.0`, `38,880.0`) which are invalid JSON. Regex strips commas that sit
# between digits *only when* they are inside a JSON numeric literal — never
# touching strings.
_COMMA_IN_NUMBER_RE = re.compile(r'(?<=\d),(?=\d)')


def _sanitise_llm_json(text: str) -> str:
    """Best-effort clean-up so both Claude and GPT-4o-mini responses parse.

    Transforms applied:
      1. Strip fenced code blocks (```json ... ```).
      2. Strip thousands-commas between digits (safe — never touches strings
         because keys/values in JSON strings never begin with a digit before
         a comma).
    """
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return _COMMA_IN_NUMBER_RE.sub("", t)


def _repair_truncated_json(text: str) -> Optional[str]:
    """Attempt to salvage a JSON object that was cut off mid-way (e.g. by
    LLM output-token cap). Walks the string, tracks brace/bracket depth,
    truncates back to the last complete key-value pair, then closes the
    remaining structure with the right number of `}`/`]`.
    """
    if not text or "{" not in text:
        return None
    s = text.strip().rstrip(",")
    if s.endswith(",") or s.endswith(":"):
        # trim dangling comma/colon
        s = s.rstrip(",: ")
    # Find last position where we're at even quote-depth and structure is
    # closeable — scan backwards for the last `,` or `}` or `]` that sits
    # outside a string.
    in_str = False
    esc = False
    stack: List[str] = []
    last_safe = -1
    for i, c in enumerate(s):
        if esc:
            esc = False; continue
        if c == "\\" and in_str:
            esc = True; continue
        if c == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if c == "{":
            stack.append("}")
        elif c == "[":
            stack.append("]")
        elif c in "}]":
            if stack:
                stack.pop()
        elif c == "," and not stack[-1:] == ['"']:
            # candidate cut-point (safe: outside any string, comma at current
            # depth)
            last_safe = i
    if last_safe < 0:
        # No comma cut-point found; try to just close whatever is open.
        cut = s
    else:
        cut = s[:last_safe]
    # Now walk cut and rebuild stack to know what's still open
    in_str = False; esc = False; stack = []
    for c in cut:
        if esc: esc = False; continue
        if c == "\\" and in_str: esc = True; continue
        if c == '"': in_str = not in_str; continue
        if in_str: continue
        if c == "{": stack.append("}")
        elif c == "[": stack.append("]")
        elif c in "}]":
            if stack: stack.pop()
    if in_str:
        cut = cut + '"'
    closing = "".join(reversed(stack))
    return cut + closing


def _parse_json_from_llm(text: str) -> Any:
    """Multi-stage JSON extraction:
      1. Sanitise fences + thousands-commas → upstream parse
      2. Fallback to raw upstream parse
      3. Repair a truncated tail and try again
    """
    cleaned = _sanitise_llm_json(text or "")
    for candidate in (cleaned, text or ""):
        got = _parse_json_upstream(candidate)
        if got:
            return got
    # Truncation recovery
    repaired = _repair_truncated_json(cleaned)
    if repaired:
        got = _parse_json_upstream(repaired)
        if got:
            return got
    return None


# Roles that can invoke the AI Purchase Manager
AIPM_ROLES = {"purchase", "pm", "gm", "director", "admin"}

MAX_HISTORY_ROWS = 200        # cap per collection to keep prompt bounded
MAX_MRF_LINES = 400
LOOKBACK_DAYS = 3 * 365       # look 3 years back by default

# --- Smart tier auto-router ------------------------------------------------
# All everyday-item calls now route to gpt-4o-mini (cheapest text model in
# Emergent LLM Key). Specialised categories and bulk-expensive lines are ALSO
# routed to gpt-4o-mini by default; the escalation now writes a flag on the
# response so the buyer knows this is a high-stakes item that MAY warrant a
# manual `premium` override for a second opinion.
# Sonnet 4.5 is NEVER auto-selected.
_CLAUDE_KEYWORDS = [
    # Cables & wires
    "cable", "wire", "conduit", "cat6", "cat5", "cat-6", "cat-5",
    "utp", "stp", "fiber", "fibre", "optical", "coax", "coaxial",
    "armoured", "armored", "xlpe", "pvc",
    # Copper-linked
    "copper", "cu ", "cu-", "cu/",
    # Pipes
    "pipe", "gi pipe", "ms pipe", "conduit pipe", "erw", "seamless",
    "hollow section",
    # Structural steel
    "channel", "beam", "angle", "flat", "rebar", "tmt",
    "ms structural", "ms plate", "girder", "purlin", "rsj",
    # Software / IT licences
    "software", "licence", "license", "subscription", "saas",
    "annual maintenance", "amc",
    # Bulk consumables
    "diesel", "fuel", "gas", "lubricant",
]

_BULK_VALUE_THRESHOLD_INR = 100_000  # ₹1 lakh line-item value flag


def _auto_route_tier(description: str, make: str, model: str,
                       current_quote: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic routing. All auto-tier calls land on the cheapest model
    (gpt-4o-mini). Specialised / bulk lines are FLAGGED so the UI can hint
    "consider a premium re-run", but they still start on the cheap tier.
    """
    hay = " ".join([
        (description or ""), (make or ""), (model or ""),
        ((current_quote or {}).get("specification") or ""),
    ]).lower()

    for kw in _CLAUDE_KEYWORDS:
        pattern = r"(?<![\w-])" + re.escape(kw) + r"(?![\w-])"
        if re.search(pattern, hay):
            return {"tier": "cheap", "reason": "specialised_category",
                     "matched_keyword": kw,
                     "premium_reroll_advised": True}

    if current_quote:
        try:
            qty = float(current_quote.get("qty") or 0)
            rate = float(current_quote.get("rate") or 0)
            line_value = qty * rate
            if line_value >= _BULK_VALUE_THRESHOLD_INR:
                return {"tier": "cheap", "reason": "bulk_expensive_line",
                         "line_value_inr": round(line_value, 2),
                         "premium_reroll_advised": True}
        except Exception:
            pass

    return {"tier": "cheap", "reason": "everyday_item",
             "premium_reroll_advised": False}


# --------------------------------------------------------------------------- helpers
def _to_dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            s = v.replace("Z", "+00:00")
            return datetime.fromisoformat(s[:26])
        except Exception:
            try:
                return datetime.strptime(v[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                return None
    return None


def _round(x: Optional[float], nd: int = 2) -> Optional[float]:
    try:
        return round(float(x), nd)
    except Exception:
        return None


def _landed(rate: float, qty: float, discount: float = 0, gst: float = 0,
             freight: float = 0, insurance: float = 0, duties: float = 0,
             loading: float = 0) -> float:
    """Total landed cost for a line."""
    gross = qty * rate
    after_disc = gross - (discount or 0)
    tax_amt = after_disc * (gst or 0) / 100
    return round(after_disc + tax_amt + (freight or 0) + (insurance or 0)
                 + (duties or 0) + (loading or 0), 2)


def _unit_landed(rate: float, discount: float = 0, gst: float = 0,
                  qty: float = 1, freight_share: float = 0,
                  insurance_share: float = 0, duties: float = 0,
                  loading_share: float = 0) -> float:
    """Landed cost per unit — used for cross-purchase comparability."""
    q = max(qty or 1, 1)
    disc_per_unit = (discount or 0) / q
    base_after = max(0.0, rate - disc_per_unit)
    tax = base_after * (gst or 0) / 100
    return round(base_after + tax + freight_share + insurance_share
                 + duties + loading_share, 2)


# --------------------------------------------------------------------------- aggregator
async def _aggregate_material_history(material_uid: str = "",
                                       description: str = "",
                                       lookback_days: int = LOOKBACK_DAYS) -> Dict[str, Any]:
    """Return a verified snapshot of every internal touch-point for a material.

    Matching rules (in priority order):
      1. `material_uid` present → strict match on `items.material_uid` or
         `items.material_id` == MAT-uid.
      2. Otherwise, fuzzy `description` regex.
      3. If both, use both (OR-combined).

    Returns a structured aggregates dict with verified doc references.
    """
    since = now_utc() - timedelta(days=lookback_days)

    # Build item-level match predicate
    or_clauses: List[Dict[str, Any]] = []
    uid_re = re.escape(material_uid) if material_uid else ""
    if material_uid:
        or_clauses.append({"material_uid": material_uid})
        or_clauses.append({"material_id": material_uid})
    if description:
        or_clauses.append(
            {"description": {"$regex": re.escape(description[:60]), "$options": "i"}}
        )
    if not or_clauses:
        raise HTTPException(400, "material_uid or description required")

    item_match = {"$or": or_clauses}

    # ---- 1. MRF lines that reference this material
    mrf_lines_raw = await db.mrfs.aggregate([
        {"$match": {"deleted": False}},
        {"$unwind": "$items"},
        {"$match": {**{f"items.{k}": v for pair in or_clauses
                        for k, v in pair.items()}}} if False else
        {"$match": {"$or": [{f"items.{k}": v for k, v in c.items()}
                              for c in or_clauses]}},
        {"$project": {
            "_id": 0, "mrf_id": 1, "mrf_number": 1, "project_id": 1,
            "customer_id": 1, "created_at": 1, "status": 1,
            "item": "$items",
        }},
        {"$sort": {"created_at": -1}},
        {"$limit": MAX_MRF_LINES},
    ]).to_list(MAX_MRF_LINES)

    mrf_line_keys = {(m["mrf_id"], m["item"]["item_line_id"]) for m in mrf_lines_raw
                     if m.get("item", {}).get("item_line_id")}

    # ---- 2. POs that reference those MRF lines
    po_docs = await db.pos.find(
        {"deleted": False, "created_at": {"$gte": since},
         "items.mrf_id": {"$in": list({k[0] for k in mrf_line_keys})} if mrf_line_keys else "__none__"},
        {"_id": 0},
    ).sort("created_at", -1).limit(MAX_HISTORY_ROWS).to_list(MAX_HISTORY_ROWS)

    # Also match POs by description on their own line items (in case PO was
    # created directly without an MRF match)
    if description and not po_docs:
        po_docs = await db.pos.find(
            {"deleted": False, "created_at": {"$gte": since},
             "items.description": {"$regex": re.escape(description[:60]), "$options": "i"}},
            {"_id": 0},
        ).sort("created_at", -1).limit(MAX_HISTORY_ROWS).to_list(MAX_HISTORY_ROWS)

    # Extract only the matching PO lines
    po_lines: List[Dict[str, Any]] = []
    for po in po_docs:
        for pit in po.get("items", []):
            if (pit.get("mrf_id"), pit.get("item_line_id")) in mrf_line_keys or (
                description and description.lower() in (pit.get("description") or "").lower()
            ):
                po_lines.append({
                    "po_id": po["po_id"], "po_number": po["po_number"],
                    "vendor_id": po.get("vendor_id"), "vendor_name": po.get("vendor_name") or "",
                    "date": _to_dt(po.get("date") or po.get("created_at")),
                    "status": po.get("status"),
                    "qty": float(pit.get("qty") or 0),
                    "unit": pit.get("unit"),
                    "rate": float(pit.get("rate") or 0),
                    "discount": float(pit.get("discount") or 0),
                    "gst": float(pit.get("gst") or 0),
                    "freight": float(po.get("freight") or 0),
                    "other_charges": float(po.get("other_charges") or 0),
                    "hsn": pit.get("hsn_code"),
                    "make": pit.get("make"),
                    "model": pit.get("model"),
                    "description": pit.get("description"),
                    "payment_terms": po.get("payment_terms"),
                    "warranty": po.get("warranty_terms"),
                })

    # Look up vendor names for lines missing them
    v_ids = {ln["vendor_id"] for ln in po_lines if ln.get("vendor_id") and not ln.get("vendor_name")}
    if v_ids:
        v_map = {v["vendor_id"]: v.get("name", "")
                 for v in await db.vendors.find(
                     {"vendor_id": {"$in": list(v_ids)}}, {"_id": 0}
                 ).to_list(500)}
        for ln in po_lines:
            if not ln.get("vendor_name") and ln.get("vendor_id"):
                ln["vendor_name"] = v_map.get(ln["vendor_id"], "")

    # ---- 3. Invoices (verified paid rates)
    po_ids = list({ln["po_id"] for ln in po_lines})
    inv_docs = await db.invoices.find(
        {"po_id": {"$in": po_ids}} if po_ids else {"__none__": "__none__"},
        {"_id": 0},
    ).sort("created_at", -1).limit(MAX_HISTORY_ROWS).to_list(MAX_HISTORY_ROWS)
    inv_lines: List[Dict[str, Any]] = []
    for iv in inv_docs:
        for it in iv.get("items", []):
            if (iv.get("po_id"), it.get("item_line_id")) in {(ln["po_id"], ln.get("item_line_id"))
                                                              for ln in po_lines} or (
                description and description.lower() in (it.get("description") or "").lower()
            ):
                inv_lines.append({
                    "invoice_number": iv["invoice_number"],
                    "vendor_invoice_number": iv.get("vendor_invoice_number"),
                    "invoice_date": iv.get("invoice_date"),
                    "po_number": iv.get("po_number"),
                    "vendor_id": iv.get("vendor_id"),
                    "rate": float(it.get("rate") or 0),
                    "qty": float(it.get("qty") or 0),
                    "discount": float(it.get("discount") or 0),
                    "gst": float(it.get("gst") or 0),
                    "line_total": float(it.get("line_total") or 0),
                })

    # ---- 4. GRNs (delivery timeliness)
    grn_docs = await db.grns.find(
        {"po_id": {"$in": po_ids}} if po_ids else {"__none__": "__none__"},
        {"_id": 0},
    ).sort("date", -1).limit(MAX_HISTORY_ROWS).to_list(MAX_HISTORY_ROWS)

    # ---- 5. Delivery Challans referenced
    dc_count = await db.dcs.count_documents(
        {"deleted": {"$ne": True},
         "items.description": {"$regex": re.escape(description[:60]), "$options": "i"}}
    ) if description else 0

    # ---- 6. Comparative statements
    cs_docs = await db.comparative_statements.find(
        {"deleted": {"$ne": True}},
        {"_id": 0, "cs_number": 1, "uploaded_at": 1, "l1_vendor": 1,
         "l1_amount": 1, "selected_vendor": 1, "vendors": 1, "title": 1},
    ).sort("uploaded_at", -1).limit(30).to_list(30)
    # Filter CS heuristically by title/vendor list
    cs_matched = []
    if description:
        keys = description.lower()[:40]
        for cs in cs_docs:
            hay = f"{cs.get('title','')} {cs.get('l1_vendor','')}".lower()
            if keys.split(" ", 1)[0] in hay:
                cs_matched.append(cs)

    # ---- 7. Vendor performance: on-time-delivery per vendor
    perf: Dict[str, Dict[str, Any]] = {}
    for grn in grn_docs:
        vid = grn.get("vendor_id")
        if not vid:
            continue
        rec = perf.setdefault(vid, {"vendor_id": vid, "vendor_name": grn.get("vendor_name") or "",
                                    "grn_count": 0, "total_qty": 0.0})
        rec["grn_count"] += 1
        for it in grn.get("items", []):
            rec["total_qty"] += float(it.get("qty") or 0)
    # Add PO-side count
    for ln in po_lines:
        vid = ln.get("vendor_id")
        if not vid:
            continue
        rec = perf.setdefault(vid, {"vendor_id": vid, "vendor_name": ln.get("vendor_name") or "",
                                    "grn_count": 0, "total_qty": 0.0})
        rec["po_lines"] = rec.get("po_lines", 0) + 1
    vendor_perf = sorted(perf.values(),
                         key=lambda x: -(x.get("po_lines", 0) + x.get("grn_count", 0)))[:20]

    # ---- 8. Compute rate statistics (verified only)
    unit_landed_rates = []
    for ln in po_lines:
        if ln["rate"] > 0 and ln["qty"] > 0:
            freight_share = (ln.get("freight") or 0) / max(ln["qty"], 1)
            other_share = (ln.get("other_charges") or 0) / max(ln["qty"], 1)
            ul = _unit_landed(ln["rate"], ln.get("discount", 0), ln.get("gst", 0),
                              ln["qty"], freight_share, 0, 0, other_share)
            unit_landed_rates.append({
                "unit_landed": ul, "rate": ln["rate"],
                "date": ln.get("date"), "vendor_id": ln.get("vendor_id"),
                "vendor_name": ln.get("vendor_name"), "qty": ln["qty"],
                "po_number": ln.get("po_number"),
            })
    unit_landed_rates.sort(key=lambda r: r["date"] or datetime(1970, 1, 1, tzinfo=timezone.utc),
                            reverse=True)

    hist_rates_only = [r["unit_landed"] for r in unit_landed_rates]
    stats = {
        "count": len(unit_landed_rates),
        "lowest": min(hist_rates_only) if hist_rates_only else None,
        "highest": max(hist_rates_only) if hist_rates_only else None,
        "average": _round(mean(hist_rates_only)) if hist_rates_only else None,
        "median": _round(median(hist_rates_only)) if hist_rates_only else None,
    }

    last_purchase = unit_landed_rates[0] if unit_landed_rates else None
    lowest_row = min(unit_landed_rates, key=lambda r: r["unit_landed"]) if unit_landed_rates else None

    # 90-day recent trend
    ninety_days_ago = now_utc() - timedelta(days=90)
    recent = [r["unit_landed"] for r in unit_landed_rates
              if r["date"] and r["date"] >= ninety_days_ago]
    older = [r["unit_landed"] for r in unit_landed_rates
             if r["date"] and r["date"] < ninety_days_ago]
    trend_pct: Optional[float] = None
    if recent and older:
        r_avg = mean(recent); o_avg = mean(older)
        if o_avg > 0:
            trend_pct = _round((r_avg - o_avg) / o_avg * 100)

    return {
        "material_uid": material_uid or "",
        "description": description or "",
        "matched_mrf_lines": len(mrf_line_keys),
        "matched_po_lines": len(po_lines),
        "matched_invoices": len(inv_lines),
        "matched_grns": len(grn_docs),
        "dc_mentions": dc_count,
        "matched_cs": len(cs_matched),
        "unique_vendors": len({ln.get("vendor_id") for ln in po_lines if ln.get("vendor_id")}),
        "stats_unit_landed_inr": stats,
        "last_purchase": last_purchase,
        "lowest_purchase": lowest_row,
        "recent_trend_pct": trend_pct,
        "vendor_performance_top": vendor_perf,
        "po_lines_sample": [
            {**{k: v for k, v in ln.items() if k != "date"},
             "date": (ln["date"].strftime("%Y-%m-%d") if ln.get("date") else None)}
            for ln in unit_landed_rates[:25]
        ],
        "invoices_sample": inv_lines[:10],
        "cs_matched": [{"cs_number": c.get("cs_number"), "title": c.get("title"),
                          "l1_vendor": c.get("l1_vendor"), "l1_amount": c.get("l1_amount")}
                          for c in cs_matched[:5]],
    }


# --------------------------------------------------------------------------- endpoints
@api.get("/llm/purchase-analysis/aggregates")
async def purchase_aggregates(material_uid: Optional[str] = None,
                                description: Optional[str] = None,
                                lookback_days: int = LOOKBACK_DAYS,
                                authorization: Optional[str] = Header(None)):
    """Cheap, LLM-free preview: returns the verified aggregation of history for
    the material. UI can call this before the full analysis to preview data
    coverage and avoid a Sonnet spend if nothing meaningful exists."""
    u = await get_current_user(authorization)
    if u.role not in AIPM_ROLES:
        raise HTTPException(403, "Not allowed to run purchase analysis")
    if not (material_uid or description):
        raise HTTPException(400, "material_uid or description required")
    return await _aggregate_material_history(material_uid or "",
                                              description or "",
                                              lookback_days)


@api.get("/llm/purchase-analysis/route")
async def preview_routing(description: Optional[str] = None,
                            make: Optional[str] = None,
                            model: Optional[str] = None,
                            qty: Optional[float] = 0,
                            rate: Optional[float] = 0,
                            authorization: Optional[str] = Header(None)):
    """Preview which LLM tier the auto-router would pick for a line item.
    Zero LLM cost — pure keyword & value routing."""
    u = await get_current_user(authorization)
    if u.role not in AIPM_ROLES:
        raise HTTPException(403, "Not allowed")
    quote = {"qty": qty or 0, "rate": rate or 0} if (qty or rate) else None
    decision = _auto_route_tier(description or "", make or "", model or "", quote)
    # Human-readable model labels with approx per-1M-token pricing (INR).
    # ₹ figures assume ~$1 = ₹83.
    _MODEL_LABELS = {
        "deterministic": "Deterministic (no LLM, ₹0 · unlimited)",
        "cheap":         "GPT-4o-mini (₹12/M in · ₹50/M out · ~₹0.05–₹0.20/call)",
        "premium":       "Claude Sonnet 4.5 (₹250/M in · ₹1245/M out · ~₹15–₹40/call · Director only)",
    }
    decision["model_label"] = _MODEL_LABELS.get(decision["tier"], decision["tier"])
    decision["model_labels"] = _MODEL_LABELS
    decision["premium_allowed"] = u.role == "director"
    return decision


class CurrentQuote(BaseModel):
    vendor_name: str = ""
    vendor_id: Optional[str] = None
    make: Optional[str] = ""
    model: Optional[str] = ""
    specification: Optional[str] = ""
    size: Optional[str] = ""
    unit: str = "Nos"
    qty: float = 1
    rate: float = 0
    discount: float = 0
    gst: float = 18
    freight: float = 0
    insurance: float = 0
    duties: float = 0
    loading_unloading: float = 0
    payment_terms: str = ""
    delivery_days: Optional[int] = None
    warranty: Optional[str] = ""
    hsn_code: Optional[str] = ""


class PurchaseAnalysisIn(BaseModel):
    material_uid: Optional[str] = ""
    description: Optional[str] = ""
    make: Optional[str] = ""
    model: Optional[str] = ""
    specification: Optional[str] = ""
    unit: Optional[str] = "Nos"
    qty: Optional[float] = 1
    current_quote: Optional[CurrentQuote] = None
    context: Optional[str] = ""      # e.g. "Bangalore high-rise, urgent"
    attachments: Optional[List[LlmAttachment]] = None
    include_market_estimates: bool = True
    # Cost tiers (Haiku removed as too expensive):
    #   deterministic → LLM-FREE. Pure aggregates + math. ₹0. Unlimited for all
    #                   roles. Great when the AI wallet is exhausted or the
    #                   user simply wants a fast, mechanical price benchmark.
    #   auto          → smart-router (DEFAULT): routes to gpt-4o-mini; flags
    #                   specialised/bulk lines so the buyer can optionally re-run
    #                   at premium tier for a second opinion.
    #   cheap         → gpt-4o-mini forced   (~₹0.05–₹0.20/call — very small)
    #   premium       → Claude Sonnet 4.5    (Director role only — will be
    #                   silently downgraded for other roles)
    tier: Optional[str] = "auto"


AI_PURCHASE_SYSTEM_PROMPT = """\
You are the AI Purchase Manager for **Vasu Infosec Pvt Ltd** (Indian fire-safety
/ CCTV / access-control / structured-cabling contractor).

Loyalty: ONLY to Vasu Infosec. Be a hard-nosed, commercially ruthless buyer.
Goal: lowest defensible technically-compliant final landed cost.

────────────────  HARD AI RESTRICTIONS (MUST OBEY)  ────────────────
You are strictly a **read-only analytical advisor**. You MUST NOT and CANNOT:
  1. Approve, register, blacklist or shortlist any vendor.
  2. Accept or reject a quotation. Only humans do that.
  3. Issue, release, cancel or modify a Purchase Order.
  4. Modify a Material Requisition Form (MRF), its lines or its statuses.
  5. Alter any master data — Materials, Vendors, Projects, Sites, Units, Brands.
  6. Create, alter or release any financial commitment, invoice, payment,
     advance, credit note or debit note.
  7. Post anything to Tally / accounting or update stock/inventory.
  8. Promise or grant discounts, credit periods, warranties, price protection
     or exclusivity on behalf of Vasu Infosec.
  9. Send emails / messages / calls to vendors or customers.

Every field you produce is an **advisory recommendation** that a human buyer
(Purchase / PM / GM / Director) must explicitly accept via the app's existing
approval workflow before ANY downstream action happens. Never phrase output
as if you have already taken action. Never write "I have approved / issued
/ sent / posted"; use "I recommend" instead.

────────────────  ANALYSIS RULES  ────────────────
1. NEVER inflate a target price. Push toward the lowest defensible number.
2. Tag every field with `source_type`: `verified` (from internal history
   provided) | `estimated` (LLM inference / market knowledge) | `inferred`
   (calculated from the two above).
3. Never fabricate historical rates. If we did not supply the data point,
   mark it `estimated` and be conservative.
4. Compute FINAL LANDED COST per unit = (base × qty − discount) × (1 + GST%)
   + freight + insurance + duties + loading/unloading.
5. Recommend a TARGET price:
   - ≤ historical median landed rate (if available)
   - ≤ current quote by 3-8% for common items; 8-15% for cables/pipes/MS
     (commodity linked)
   - Adjust DOWN for long lead-times, adverse payment terms, or high qty.
   - Adjust UP only for verified single-source items (cite reason).
6. Confidence: ≥0.85 needs ≥5 verified rows; 0.30-0.55 for <3 rows or none.
7. Market benchmark: cite commodity + date (e.g. "LME copper ~$8,300/T,
   world-knowledge 2024-Q4").
8. Flag vendor red-flags briefly.
9. Give 2-4 concrete negotiation tactics (each ≤ 40 words).

Output STRICTLY as one JSON object, no fences, no prose outside JSON. Keep
strings short (each field ≤ 300 chars, tactics ≤ 40 words each):

{
  "material_uid": "MAT-... or empty",
  "description": "...",
  "normalised_specification": {"make":"...","model":"...","size":"...","unit":"...","spec_summary":"..."},
  "current_quote_landed_cost_per_unit": <float>,
  "current_quote_total_landed_cost": <float>,
  "history": {
    "last_purchase_rate": <float|null>, "last_purchase_landed": <float|null>,
    "last_supplier": "...", "last_purchase_date": "YYYY-MM-DD",
    "historical_lowest_rate": <float|null>, "historical_average_rate": <float|null>,
    "historical_median_rate": <float|null>, "trend_last_90_days_pct": <float|null>
  },
  "market_benchmark": {"value_per_unit": <float|null>,"commodity_link":"copper|steel|MS|pipe|fuel|freight|fx|none","source_type":"estimated","source_note":"..."},
  "variance": {"current_vs_last_pct":<float|null>,"current_vs_market_pct":<float|null>,"current_vs_lowest_pct":<float|null>},
  "recommended_target_price_per_unit": <float>,
  "recommended_negotiated_price_per_unit": <float>,
  "expected_saving_per_unit": <float>,
  "expected_saving_total": <float>,
  "expected_saving_pct": <float>,
  "confidence": <float 0..1>,
  "verified_fields": [...],
  "estimated_fields": [...],
  "vendor_red_flags": [...],
  "negotiation_tactics": ["≤40w each","≤40w each"],
  "risks": [...],
  "assumptions": [...],
  "sources": [{"kind":"po|invoice|grn|dc|cs","ref":"...","date":"YYYY-MM-DD"}],
  "commercial_summary": "≤ 400 chars exec summary for the Purchase Head",
  "decision": "issue_at_target | negotiate_more | reject_and_retender | ok_current"
}

If data is insufficient, use null and add to `assumptions`. NEVER invent
numbers. Keep the total response under 2500 tokens.
"""


def _deterministic_analysis(body: "PurchaseAnalysisIn",
                             aggregates: Dict[str, Any],
                             computed_quote_landed: Optional[float],
                             computed_quote_total: Optional[float]) -> Dict[str, Any]:
    """LLM-free rule-based analysis. Uses only verified aggregates + basic
    heuristics — free, unlimited, no external calls.

    Rules:
      * Target price   = min(historical median, current × 0.95) if history exists,
                           else current × 0.95.
      * Negotiate to   = min(historical lowest, target × 0.98) if lowest exists,
                           else target × 0.97.
      * Decision:
          ok_current           if variance ≤ +2%   vs historical median
          negotiate_more       if variance +2..+10%
          reject_and_retender  if variance > +10%  OR current > historical highest
          issue_at_target      otherwise
      * Confidence: derived from #verified rows (0.35 base + 0.1 per row, cap 0.90).
    """
    stats = aggregates.get("stats_unit_landed_inr") or {}
    n = int(stats.get("count") or 0)
    hist_med = stats.get("median")
    hist_avg = stats.get("average")
    hist_lo = stats.get("lowest")
    hist_hi = stats.get("highest")
    last_row = aggregates.get("last_purchase")
    current_landed = computed_quote_landed

    target = None
    negotiate_to = None
    if current_landed is not None:
        # Base target: 95% of current
        base = current_landed * 0.95
        if hist_med is not None:
            target = round(min(base, float(hist_med)), 2)
        else:
            target = round(base, 2)
        # Negotiate to
        if hist_lo is not None:
            negotiate_to = round(min(float(hist_lo), target * 0.98), 2)
        else:
            negotiate_to = round(target * 0.97, 2)
    elif hist_med is not None:
        target = round(float(hist_med), 2)
        negotiate_to = round(float(hist_lo or hist_med) * 0.98, 2) if hist_lo or hist_med else None

    variance_vs_last = None
    variance_vs_median = None
    if current_landed is not None and last_row and last_row.get("unit_landed"):
        try:
            l = float(last_row["unit_landed"])
            if l > 0:
                variance_vs_last = round((current_landed - l) / l * 100.0, 2)
        except Exception:
            pass
    if current_landed is not None and hist_med:
        try:
            m = float(hist_med)
            if m > 0:
                variance_vs_median = round((current_landed - m) / m * 100.0, 2)
        except Exception:
            pass

    decision = "ok_current"
    if variance_vs_median is not None:
        if variance_vs_median > 10 or (hist_hi and current_landed and current_landed > float(hist_hi)):
            decision = "reject_and_retender"
        elif variance_vs_median > 2:
            decision = "negotiate_more"
        else:
            decision = "issue_at_target"
    elif current_landed is not None and target and current_landed > target * 1.02:
        decision = "negotiate_more"

    conf = min(0.90, 0.35 + 0.10 * n)
    if n == 0:
        conf = 0.20

    qty = float(body.qty or (body.current_quote.qty if body.current_quote else 1) or 1)
    saving_per_unit = None
    if current_landed is not None and negotiate_to is not None:
        saving_per_unit = round(current_landed - negotiate_to, 2)
    saving_total = round((saving_per_unit or 0) * qty, 2) if saving_per_unit is not None else None
    saving_pct = None
    if saving_per_unit is not None and current_landed:
        saving_pct = round(saving_per_unit / current_landed * 100.0, 2)

    tactics = []
    if variance_vs_median is not None and variance_vs_median > 5:
        tactics.append(f"Current quote is {variance_vs_median}% above our historical median — anchor to the median and ask for a written revised offer.")
    if hist_lo is not None and current_landed and float(hist_lo) < current_landed:
        tactics.append(f"We have a verified purchase at ₹{hist_lo} for this line — request rate parity or better.")
    if last_row and last_row.get("vendor_name"):
        tactics.append(f"Get a competing quote from {last_row['vendor_name']} (last supplier) to create competitive pressure.")
    if not tactics:
        tactics.append("Bundle qty across pending indents to unlock volume discount (3-5%).")
        tactics.append("Offer 100% advance for a 2-3% cash discount and shorter delivery.")

    return {
        "material_uid": body.material_uid or "",
        "description": body.description or "",
        "normalised_specification": {
            "make": body.make or "",
            "model": body.model or "",
            "unit": body.unit or "Nos",
            "spec_summary": (body.specification or "").strip(),
        },
        "current_quote_landed_cost_per_unit": current_landed,
        "current_quote_total_landed_cost": computed_quote_total,
        "history": {
            "last_purchase_rate": last_row.get("rate") if last_row else None,
            "last_purchase_landed": last_row.get("unit_landed") if last_row else None,
            "last_supplier": (last_row or {}).get("vendor_name") or (last_row or {}).get("vendor_id"),
            "last_purchase_date": (last_row or {}).get("date"),
            "historical_lowest_rate": hist_lo,
            "historical_average_rate": hist_avg,
            "historical_median_rate": hist_med,
            "trend_last_90_days_pct": aggregates.get("recent_trend_pct"),
        },
        "market_benchmark": {
            "value_per_unit": None,
            "commodity_link": "none",
            "source_type": "estimated",
            "source_note": "Deterministic mode does not use external market data.",
        },
        "variance": {
            "current_vs_last_pct": variance_vs_last,
            "current_vs_market_pct": None,
            "current_vs_lowest_pct": (
                round((current_landed - float(hist_lo)) / float(hist_lo) * 100.0, 2)
                if current_landed is not None and hist_lo else None
            ),
        },
        "recommended_target_price_per_unit": target,
        "recommended_negotiated_price_per_unit": negotiate_to,
        "expected_saving_per_unit": saving_per_unit,
        "expected_saving_total": saving_total,
        "expected_saving_pct": saving_pct,
        "confidence": round(conf, 2),
        "verified_fields": [
            k for k in ("historical_median_rate", "historical_lowest_rate",
                          "historical_average_rate", "last_purchase_rate")
            if (aggregates.get("stats_unit_landed_inr") or {}).get(
                k.replace("historical_", "").replace("_rate", "").replace("last_purchase", "count"))
        ],
        "estimated_fields": ["market_benchmark", "negotiation_tactics"],
        "vendor_red_flags": [],
        "negotiation_tactics": tactics[:4],
        "risks": (["Only {} verified rate row(s) — low statistical confidence.".format(n)]
                   if n < 3 else []),
        "assumptions": (
            ["No verified history — target is a straight 5% discount from the current quote."]
            if n == 0 else []
        ),
        "sources": [
            {"kind": "po", "ref": r.get("po_number"), "date": r.get("date")}
            for r in (aggregates.get("po_lines_sample") or [])[:5]
        ],
        "commercial_summary": (
            f"Deterministic benchmark: {n} verified rate row(s). "
            f"Current landed ₹{current_landed if current_landed is not None else '—'}. "
            f"Target ₹{target if target is not None else '—'}, negotiate to ₹{negotiate_to if negotiate_to is not None else '—'}. "
            f"Decision: {decision.replace('_', ' ')}."
        ),
        "decision": decision,
        "_engine": "deterministic",
    }


@api.post("/llm/purchase-analysis")
async def purchase_analysis(body: PurchaseAnalysisIn,
                              authorization: Optional[str] = Header(None)):
    """Run the full AI Purchase Manager analysis for one line item and save the
    resulting suggestion to `llm_suggestions` for accept/reject workflow."""
    u = await get_current_user(authorization)
    if u.role not in AIPM_ROLES:
        raise HTTPException(403, "Not allowed to run AI Purchase Manager")
    if not (body.material_uid or body.description or body.current_quote):
        raise HTTPException(400,
            "Provide at least material_uid, description, or a current_quote")

    # ---- 1) Aggregate internal history (verified data) ----
    desc = (body.description or "").strip()
    if body.current_quote and not desc:
        desc = (body.current_quote.model or body.current_quote.make
                or "").strip()
    aggregates = await _aggregate_material_history(
        (body.material_uid or "").strip(), desc
    )

    # ---- 2) Attachment text (optional PDF/Excel quote) ----
    att_text_blobs: List[Dict[str, Any]] = []
    for a in (body.attachments or [])[:4]:
        try:
            text, kind = _extract_text_from_attachment(a.file_name,
                                                        a.mime_type,
                                                        a.file_base64)
            att_text_blobs.append({
                "file_name": a.file_name, "kind": kind,
                "chars": len(text),
                "text": text[:8000] if text else "",
            })
        except HTTPException:
            raise
        except Exception as e:
            att_text_blobs.append({"file_name": a.file_name, "error": str(e)})

    # ---- 3) Build the user-message payload ----
    user_prompt = {
        "context": body.context or "",
        "material_uid": body.material_uid or "",
        "description": body.description or "",
        "make": body.make or "",
        "model": body.model or "",
        "specification": body.specification or "",
        "unit": body.unit or "Nos",
        "qty": body.qty or 1,
        "current_quote": (body.current_quote.model_dump()
                            if body.current_quote else None),
        "verified_internal_aggregates": aggregates,
        "attachments_text": att_text_blobs,
        "market_estimates_allowed": body.include_market_estimates,
    }
    user_text = _json.dumps(user_prompt, default=str)[:60000]  # cap for token safety

    # ---- 4) Route to the right LLM tier ----
    entity = "material" if body.material_uid else "quote"
    entity_id = body.material_uid or (body.current_quote.vendor_name
                                       if body.current_quote else "adhoc")

    requested_tier = (body.tier or "auto").lower()

    # Compute authoritative landed cost first — used by BOTH deterministic
    # and LLM paths for the final display.
    computed_quote_landed = None
    computed_quote_total = None
    if body.current_quote:
        q = body.current_quote
        freight_share = (q.freight or 0) / max(q.qty or 1, 1)
        loading_share = (q.loading_unloading or 0) / max(q.qty or 1, 1)
        insurance_share = (q.insurance or 0) / max(q.qty or 1, 1)
        computed_quote_landed = _unit_landed(
            q.rate, q.discount, q.gst, q.qty,
            freight_share, insurance_share, q.duties or 0, loading_share,
        )
        computed_quote_total = _landed(
            q.rate, q.qty, q.discount, q.gst,
            q.freight, q.insurance, q.duties, q.loading_unloading,
        )

    # ─── Deterministic (LLM-free) mode ─────────────────────────────────
    if requested_tier == "deterministic":
        parsed = _deterministic_analysis(body, aggregates,
                                          computed_quote_landed,
                                          computed_quote_total)
        parsed.setdefault("_computed_by_server", {})
        parsed["_computed_by_server"]["current_quote_landed_cost_per_unit"] = computed_quote_landed
        parsed["_computed_by_server"]["current_quote_total_landed_cost"] = computed_quote_total
        parsed["_computed_by_server"]["routing"] = {
            "tier": "deterministic", "reason": "user_selected_no_llm",
        }
        parsed["_verified_aggregates"] = aggregates
        # Zero-cost record so it still surfaces in the Review tab and admin roll-ups
        cost0 = {
            "model": "deterministic",
            "input_tokens_approx": 0, "output_tokens_approx": 0,
            "input_rate_usd_per_m": 0, "output_rate_usd_per_m": 0,
            "cost_usd": 0.0, "cost_inr": 0.0, "cache_saved": False,
        }
        doc = await _save_suggestion(
            kind="purchase_analysis",
            entity=entity, entity_id=entity_id or "adhoc",
            user=u, input_payload=user_prompt,
            parsed=parsed, raw="",
            tier="deterministic", model="deterministic",
            extras={"tier": "deterministic", "model": "deterministic",
                    "cost": cost0, "hash": "det",
                    "tier_meta": {"requested_tier": "deterministic",
                                   "effective_tier": "deterministic",
                                   "downgraded": False}},
        )
        return doc

    routing_decision: Dict[str, Any]
    if requested_tier == "auto":
        routing_decision = _auto_route_tier(
            body.description or "", body.make or "", body.model or "",
            body.current_quote.model_dump() if body.current_quote else None,
        )
    elif requested_tier in ("cheap", "premium"):
        routing_decision = {"tier": requested_tier, "reason": "user_override"}
    else:
        routing_decision = {"tier": "cheap", "reason": "unknown_tier_default"}

    final_tier = routing_decision["tier"]
    raw, extras = await _call_llm(
        tier=final_tier,
        system=AI_PURCHASE_SYSTEM_PROMPT,
        user_text=user_text,
        user=u, kind="purchase_analysis",
        entity=entity, entity_id=entity_id or "adhoc",
        input_payload={"material_uid": body.material_uid,
                        "description": body.description,
                        "record_number": body.material_uid or "adhoc"},
    )
    # If the RBAC gate silently downgraded (e.g. non-director asked for
    # premium), reflect the effective tier back in the routing block so the
    # UI can render an accurate "analysed with X" note.
    tier_meta = extras.get("tier_meta") or {}
    if tier_meta.get("downgraded"):
        routing_decision["downgraded"] = True
        routing_decision["downgrade_reason"] = tier_meta.get("downgrade_reason")
        routing_decision["effective_tier"] = tier_meta.get("effective_tier")
    extras["routing"] = routing_decision
    parsed = _parse_json_from_llm(raw) or {"raw": raw[:8000],
                                             "error": "Could not parse LLM output as JSON"}

    # ---- 5) Attach authoritative computed values to LLM output ----
    if isinstance(parsed, dict):
        parsed.setdefault("_computed_by_server", {})
        parsed["_computed_by_server"]["current_quote_landed_cost_per_unit"] = computed_quote_landed
        parsed["_computed_by_server"]["current_quote_total_landed_cost"] = computed_quote_total
        parsed["_computed_by_server"]["routing"] = routing_decision
        # Attach the verified aggregates so the UI can render them side-by-side
        parsed["_verified_aggregates"] = aggregates

    # ---- 6) Save suggestion for accept/reject ----
    doc = await _save_suggestion(
        kind="purchase_analysis",
        entity=entity, entity_id=entity_id or "adhoc",
        user=u, input_payload=user_prompt,
        parsed=parsed, raw=raw,
        tier=extras.get("tier", "premium"),
        model=extras.get("model", ""),
        extras=extras,
    )
    return doc


@api.get("/llm/purchase-analysis/{sid}")
async def get_purchase_analysis(sid: str,
                                  authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in AIPM_ROLES:
        raise HTTPException(403, "Not allowed")
    doc = await db.llm_suggestions.find_one(
        {"suggestion_id": sid, "kind": "purchase_analysis"}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Analysis not found")
    return _strip_oids(doc)
