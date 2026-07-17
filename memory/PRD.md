# Vasu Infosec — Material Requisition & Purchase Order System
## Product Requirements Document & Architecture Snapshot
*Last updated: Phase 9C, June 2026 — server.py refactor round 2*

---

## 1. Product Vision

A production-grade full-stack app that replaces spreadsheet-driven procurement at Vasu Infosec (a Fire Safety / CCTV / Access Control / Structured Cabling contractor with offices in Pune & Delhi). The system enforces:
- **Strict Role-Based Access Control** across the `Site Engineer → PM → Purchase → GM → Director` approval chain.
- **Traceable audit trail** — every mutation (draft, submit, approve, reject, edit, receive, export) writes an immutable audit row with `old_value`, `new_value`, `reason`, `record_number`, `user_role`.
- **Regulatory-grade export** — GST-compliant PDFs, 40-column Excel workbooks, and Tally-voucher exports with mandatory HSN/GSTIN validation.
- **AI Co-pilot** — LLM assistance is *suggestion-only*; humans always click accept/reject.

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Expo (React Native + Web) via expo-router file-based routing |
| Frontend state | React Context (`src/auth.tsx`), local component state |
| UI kit | Custom (`src/components/ui.tsx`), react-native-safe-area-context, Ionicons |
| Backend | FastAPI (async), Motor (async MongoDB driver) |
| Database | MongoDB (via `MONGO_URL` in backend/.env) |
| Documents | reportlab (PDF), openpyxl (Excel), pypdf (PDF text extraction for LLM) |
| LLM | Emergent LLM Key → Anthropic Claude Haiku 4.5 (cheap) + Sonnet 4.5 (premium) |
| Auth | Emergent-managed Google Auth (prod) + `/api/auth/dev-login` (test-only, gated by `ENABLE_DEV_LOGIN=1`) |
| Deployment | Emergent Publish (single button — top-right) |

## 3. Roles & Approval Chain

`Site Engineer → PM → Purchase → GM → Director` + `Admin`, `Store` (out-of-chain).

| Role | Permissions |
|---|---|
| site_engineer | Draft + submit MRFs for their site; record GRN. Cannot approve. |
| pm | Authorise MRFs on projects they manage; send to purchase. |
| purchase | Issue POs (auto ≤ GM threshold), manage vendors, record invoices, run Co-pilot. |
| gm | Approve POs above GM threshold, authorise MRFs, approve materials. |
| director | Approve POs above Director threshold; override; edit thresholds. |
| admin | Manage users, projects, masters, thresholds; approve GRN/DC/CS. |
| store | Record GRN at their site. |

Thresholds (editable in Masters → PO Thresholds by Director/Admin):
- Default GM: ₹50,000 · Director: ₹5,00,000 · Above Director: pending_director_approval.

## 4. Feature Phases Delivered

| Phase | Feature | Status |
|---|---|---|
| 1 | Users, Roles, Projects, Customers, Vendors CRUD | ✅ |
| 2 | MRF lifecycle (draft → pm_review → approved → sent_to_purchase → partially/fully_ordered) | ✅ |
| 3 | PO lifecycle (issued → received) with threshold-gated approvals & billing | ✅ |
| 4 | Material Master + MAT-####/VAR-#### UIDs + bulk import + GM approval flow | ✅ (chips pending in frontend) |
| 5 | Unified Export/Download (PDF, Excel, Tally) with pre-export validation + audit | ✅ |
| 6 | Comprehensive Audit Trail (login events, old/new values, RBAC-scoped feeds) | ✅ |
| 7 | Delivery Challan (DC) + Comparative Statement (CS) with independent approval chains | ✅ |
| 8 | AI Co-pilot: item-standardise, quotation-compare, reconcile — suggestion-only | ✅ |
| 9A | Emergent LLM Key wired via `emergentintegrations` (Haiku + Sonnet) | ✅ |
| 9B | LLM file uploads (PDF via pypdf, Excel via openpyxl, CSV, TXT) | ✅ |
| 9C | Router extraction: `routers/llm.py`, `routers/notifications.py`, `routers/reports.py`, `routers/audit.py`, `routers/settings.py` (server.py 5276 → 4966 lines) | ✅ (round 2 done — more remaining) |
| 10 | Dashboard & Analytics | ⏳ Deferred by user |

## 5. Third-Party Integrations & Cost to Company

### Emergent-managed integrations (single Universal Key, top-up model)

| Integration | Provider | Model | Purpose | Approx per-call cost |
|---|---|---|---|---|
| Emergent Google Auth | Google (via Emergent) | OAuth 2.0 | Real production login | **₹0** (bundled with Emergent Universal Key credits) |
| Item Standardise | Anthropic (via Emergent) | claude-haiku-4-5-20251001 | Suggest MAT/VAR matches | ~$0.01–$0.03 (~₹1–₹2.5) per call |
| Quotation Compare | Anthropic (via Emergent) | claude-sonnet-4-5-20250929 | L1/L2/L3 side-by-side analysis | ~$0.15–$0.25 (~₹12–₹21) per call |
| Reconcile (3-way match) | Anthropic (via Emergent) | claude-sonnet-4-5-20250929 | PO vs GRN vs Invoice audit | ~$0.10–$0.20 (~₹8–₹17) per call |

**Cost optimisation already built in:**
- Content-hash cache (`db.llm_cache`) — identical prompts hit cache and cost ₹0. This is a huge saving during repeat testing/re-runs.
- Cheap-tier (Haiku) routing for high-frequency, low-complexity task (item standardise). Sonnet reserved for the two Sonnet-worthy multi-doc analyses.
- Attachment text is capped at 40,000 chars and 60 PDF pages to bound input tokens.
- Catalogue slice sent to Haiku is capped at 200 materials + 600 variants.

**Monthly ballpark assuming realistic Vasu volume:**

| Volume | Cost |
|---|---|
| 200 item-standardise calls/month (Haiku) | ~₹200–₹500 |
| 30 quotation-compare calls/month (Sonnet) | ~₹360–₹630 |
| 50 reconcile calls/month (Sonnet) | ~₹400–₹850 |
| **Total LLM cost per month (upper bound)** | **~₹1,000–₹2,000** |

*Top up in the Emergent Profile → Universal Key → Add Balance panel. Enable auto-topup to avoid interruption.*

### Open-source libraries (₹0 recurring cost)

- **reportlab** — GST-compliant PDF generation (PO, MRF, GRN, DC, CS, Invoice)
- **openpyxl** — 40-column Excel workbooks + Tally voucher spreadsheets
- **pypdf** — extract text from uploaded BOQ / quote / invoice PDFs
- **motor** — async MongoDB driver
- **FastAPI** — REST API framework
- **Expo / React Native** — cross-platform mobile & web frontend

### Infrastructure

- **MongoDB** — hosted within Emergent (bundled)
- **Expo dev + preview** — bundled with Emergent workspace
- **Emergent Publish (deploy)** — priced per workspace tier (out of scope of app cost; deployment triggered by user via the Publish button)

**Total recurring third-party cost to Vasu Infosec (excluding Emergent hosting): ~₹1,000–₹2,000/month at expected LLM volume.** Everything else is open-source.

## 6. Database Schema Highlights

- `users` — {user_id, email, name, role, is_active}
- `projects` — {project_id, code, name, customer_id, project_managers[], sites[]}
- `customers` — {customer_id, name, gstin, pan, customer_pos[]}
- `vendors` — {vendor_id, name, gstin, pan, contact}
- `materials` — {material_uid: 'MAT-####', description, category, unit, hsn_code, status: pending_gm/approved/rejected}
- `variants` — {variant_uid: 'VAR-####', material_uid, make, model}
- `mrfs` — {mrf_id, mrf_number, project_id, site, items[{item_line_id, material_uid, variant_uid, qty_requested, qty_approved, billing_status, ...}], status, approval_history[]}
- `pos` — {po_id, po_number, vendor_id, project_id, items[], mrf_refs[], total, status, approval_history[]}
- `grns` — {grn_id, mrf_id/po_id, date, items[], status, approval_history[]}
- `dcs` — {dc_id, project_id, customer_id, items[], status, approval_history[]}
- `comparative_statements` — {cs_id, project_id, vendor_quotes[], status, approval_history[]}
- `invoices` — {invoice_id, po_id, vendor_invoice_number, total, items[]}
- `audit_logs` — {entity, entity_id, action, user_id, user_role, timestamp, details: {old_value, new_value, reason, record_number, ...}}
- `llm_suggestions` — {suggestion_id, kind, entity, status: pending_review/accepted/rejected, output_parsed, decided_by, decision_reason}
- `llm_cache` — {_id: sha256(prompt), response, tier, model, kind}
- `settings` — {_id: 'thresholds', gm, director}
- `notifications` — {notification_id, user_id, read, created_at}

## 7. Current server.py Refactor Status

**Before Phase 9C round 2:** 5,276 lines monolithic.
**After round 3:** 4,400 lines. Extracted modules in `/app/backend/routers/`:

| Module | Endpoints | LOC |
|---|---|---|
| `llm.py` | /api/llm/item-standardise, /quotation-compare, /reconcile, /suggestions[/{id}[/decide]] | 570 |
| `masters.py` | /materials/*, /variants/*, /master-audit, /systems, /masters (generic), /import/materials[/template] | 464 |
| `customers.py` | /customers + /customers/{id}/pos/* | 223 |
| `reports.py` | /api/reports/dashboard, /mrf-ageing, /grn-variance | 155 |
| `audit.py` | /api/audit, /api/audit/facets | 142 |
| `settings.py` | /api/settings/thresholds (GET, PUT) | 46 |
| `notifications.py` | /api/notifications (GET), /api/notifications/{nid}/read | 30 |

**Pending extraction (Batch B & C):**
- `masters.py` — /materials, /variants, /master-audit, /systems, /masters (generic)
- `customers.py` — /customers + /customers/{id}/pos
- `mrf.py` — /mrf lifecycle
- `po.py` — /po lifecycle + PO PDF/Excel/Tally exports
- `grn.py` — /grn/* + GRN PDF/export
- `dc.py` — /dc/* + DC PDF/export
- `cs.py` — /comparative-statement/*
- `imports.py` — /import/materials|vendors|mrf templates + upload
- `exports.py` — /export/mrf|po|tally|grn|dc bulk endpoints
- `auth.py` — /auth/session|me|logout|dev-login + /users, /users/role
- `projects.py` — /projects + /projects/{id}/sites|team
- `billing.py` — /billing/items, /billing/update
- `invoice.py` — /invoice/*

## 8. Frontend Screens (`/app/frontend/app/`)

- `index.tsx`, `login.tsx`, `home.tsx` — landing + Google auth
- `mrf/`, `po/`, `grn/`, `dc/`, `comparative-statement.tsx` — record CRUD screens
- `masters.tsx`, `customers.tsx` — master data
- `import.tsx` — bulk imports
- `reports.tsx`, `notifications.tsx`, `audit.tsx` — reads
- `assistant.tsx` — **AI Co-pilot** (Standardise / Compare Quotes / 3-way Match / Review tabs)
- `billing.tsx`, `more.tsx` — settings & billing views

Shared components (`/app/frontend/src/components/`):
- `ExportMenu` — unified PDF/Excel/Tally bottom sheet with force-download for validation warnings
- `AuditTrail` — reusable per-entity audit feed
- `ApprovalPanel` — GRN/DC/CS approval UI
- `LlmFilePicker` — file picker feeding attachments into the LLM endpoints

## 9. Testing State

- `/app/backend/tests/test_phase9c_refactor.py` — 21/21 pass (router extraction regression + LLM UAT)
- `/app/backend/tests/uat_llm_files.py` — generates realistic BOQ/quote/invoice PDFs and drives the LLM endpoints end-to-end (0/0 failures)
- Legacy `test_phase2c_backend.py` and `test_audit_scoping_iter14.py` have drifted from newer validators — non-blocking; earmarked for a cleanup pass.
- All test reports live in `/app/test_reports/iteration_*.json` (up to iteration 23).

## 10. Deployment

- Preview: served by Expo Metro on the workspace preview URL; `/` → port 3000 (Expo), `/api/*` → port 8001 (FastAPI). Never modify `.env` URL/port values.
- Production: user clicks **Publish** (top-right) in Emergent. iOS/Android builds require google-services.json + Apple credentials (only if user enables mobile push in future).

## 11. Known Deferred Items

- Dashboard & Analytics (Phase 10) — deferred by user 2 sessions ago
- Frontend MAT-####/VAR-#### chip rendering in MRF/PO/GRN item cards
- Legacy test-suite refresh
