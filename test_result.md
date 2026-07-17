#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================
## user_problem_statement (Phase 2 — Approval Chain & Thresholds)
Enforce strict Vasu operational workflow: Site Engineer → Project Manager → Purchase → GM → Director.
Restore `site_engineer` as a distinct role (was previously merged into pm).
Add editable Purchase Approval Thresholds (GM / Director) in Masters.
Preserve existing users and data (no rebuild).

backend:
  - task: "Restore site_engineer role and permission matrix"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "ROLES now includes site_engineer + store. Legacy site_engineer→pm mapping REMOVED. create_mrf allows site_engineer (project team check), approve_mrf explicitly excludes site_engineer, _check_mrf_access and _check_po_access have separate branches for site_engineer vs pm. list_mrfs shows own-only for SE, project-scoped for PM. mark_po_received allows site_engineer/store/purchase/pm/director/admin. Manual curl smoke test passed for full chain: SE-create → PM-approve → Purchase-PO → GRN."

  - task: "PO threshold-based approval flow"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New endpoints: GET/PUT /api/settings/thresholds (director/admin only). create_po now computes initial status via _po_initial_status(total, gm_t, dir_t). Statuses: issued (≤GM), pending_gm_approval (GM<x≤Director), pending_director_approval (>Director). New POST /api/po/{id}/approve endpoint (GM approves GM-tier, Director approves both tiers). MRF qty_ordered rollup is DEFERRED until PO is approved. mark_po_received blocks PO in pending states. Manual curl test passed for small PO auto-issue, GM-tier requires GM, Director-tier rejects GM approval, Director approves it."

  - task: "Seed real Vasu Infosec users"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Added Vivek (Director), Balkrishna (GM), Saket Iyer (PM), Himanshu (PM) with @vasuinfosec.com emails alongside dev demo users. Idempotent seed preserves manually-adjusted roles. Site engineer demo user added as siteeng@vasu.dev. Project team seed assigns saket+himanshu as project_managers on all seed projects."

frontend:
  - task: "Role-based UI for site_engineer and new chain"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/(various)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "AppShell tabs, roleLabel, home Quick Actions, MRF list canCreate, PO list canCreate, PO detail approve/reject/receive buttons, Masters ROLES dropdown, ProjectTeamModal engineer filter, login demo users — all updated to include site_engineer + store."

  - task: "PO approval workflow UI (GM/Director)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/po/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "PO detail shows Approve/Reject buttons when status is pending_gm_approval (for GM/Dir/Admin) or pending_director_approval (for Dir/Admin only). Receipt button unavailable while PO is in pending state. Added quick action 'POs Awaiting My Approval' on home for gm/director/admin."

  - task: "PO Thresholds editor in Masters"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/masters.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "New 'PO Thresholds' tab in Masters visible only to Director/Admin. Two numeric fields (GM, Director), save button hits PUT /api/settings/thresholds with validation (director >= gm)."

metadata:
  created_by: "main_agent"
  version: "2.0"
  test_sequence: 1
  run_ui: true

test_plan:
  current_focus:
    - "Restore site_engineer role and permission matrix"
    - "PO threshold-based approval flow"
    - "Role-based UI for site_engineer and new chain"
    - "PO approval workflow UI (GM/Director)"
    - "PO Thresholds editor in Masters"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "Phase 2 (approval chain + thresholds) implemented. Backend RBAC completely reshuffled: site_engineer is now a first-class role, PO creation goes through threshold gates, GM/Director approve high-value POs. Please run comprehensive RBAC regression tests across all six roles (site_engineer, pm, purchase, gm, director, admin) covering: MRF create/submit/approve/reject/return, PO create with three threshold tiers, GM approve of GM-tier PO, GM reject of Director-tier PO, Director approve of both tiers, GRN receipt by site_engineer/purchase, and Threshold PUT restricted to director/admin. Dev-login endpoint is available at /api/auth/dev-login (ENABLE_DEV_LOGIN=1). See /app/memory/test_credentials.md for seeded users."

## Phase 2b — Admin Master Module (Customers + GST + Departments + Models + Master Audit)

backend:
  - task: "Customer Master with editable alphanumeric IDs + cascade"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New /api/customers CRUD. Customer ID is admin-typed alphanumeric (^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$). Editable via PUT with reason required. On ID change, cascades to customers, customer_pos, projects.customer_id, mrfs.customer_id, pos.customer_id, invoices.customer_id. Duplicate ID and duplicate name blocked (case-insensitive). Only admin/director. Migration on /api/seed auto-creates Customer records for legacy project.client strings."
  - task: "Customer PO with attachment (base64)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "POST /api/customers/{cid}/pos, PUT /api/customers/{cid}/pos/{cpo_id}, GET /api/customers/{cid}/pos/{cpo_id}/attachment. Fields: po_number, po_date, value, validity_till, attachment_name, attachment_b64. admin/director/purchase only."
  - task: "Model, GST, Department masters (extend masters collection)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New /api/masters PUT + DELETE with mandatory reason. Categories extended to unit/brand/material/model/gst/department. GST accepts numeric `value` (percent). Case-insensitive duplicate prevention per category. Master edits go through master_audit."
  - task: "master_audit trail (WHO, WHEN, WHY, OLD, NEW)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New master_audit_logs collection. helper master_audit(entity, id, action, user, reason, old, new) strips ObjectIds/datetimes deep. Reasons mandatory on all master edits (customer, project, vendor, master). GET /api/master-audit lists entries (director/admin only). Also mirrors into audit_logs so existing audit UI sees them."
  - task: "Seed full Vasu Infosec roster (12 real users)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Added wasim@, sanjeev@, pundlik@, chand@, saurabh@, abhishek.yadav@, shivsaran@, abhishek@ (stores). All @vasuinfosec.com, editable via /users/role."

frontend:
  - task: "Customers screen — dedicated CRUD"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/customers.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "New /customers route. Create form with all fields; list rows with Edit/PO/Deactivate icons; Edit modal has toggle to unlock Customer ID (cascade update). Mandatory reason field."
  - task: "Masters screen — new tabs (Models, GST, Departments, Master Audit) + Customer CTA + reason on edits"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/masters.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Extended Tab type. Add-Project form has CUSTOMER ID field. Project/Vendor edit modals now require a reason (audit). New MasterAuditSection filterable by entity."

test_plan:
  current_focus:
    - "Customer Master with editable alphanumeric IDs + cascade"
    - "Customer PO with attachment (base64)"
    - "master_audit trail (WHO, WHEN, WHY, OLD, NEW)"
    - "Model, GST, Department masters (extend masters collection)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "Phase 2b (Admin Master Module) implemented. Manual smoke test passed for: customer create/duplicate/invalid-ID/rename-with-cascade/deactivate, customer PO add, master reason enforcement, master_audit list, non-admin denial. Please run full RBAC & integrity regression: customer CRUD (admin/director allowed, others 403), CID rename cascade to projects/mrfs/pos/invoices, GST/Department/Model CRUD via masters endpoint, reason-required on customer/vendor/project/master PUT (400 without), master_audit list filtered by entity, duplicate customer name/ID rejected, project.customer_id validation (400 if unknown). Do NOT test PDF generation or Tally export (deferred to Phase 3)."

## Phase 2c — Customer wiring + Branded PDFs + Tally export + 12-status MRF pipeline + line-item audit

backend:
  - task: "Customer ID snapshot on MRF/PO/Invoice + backfill"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "MRF/PO/Invoice models now carry customer_id + customer_name (denormalized snapshot from project at create time). Existing records backfilled. Excel exports (MRF, PO) now include Customer ID + Name columns."
  - task: "Branded Vasu PDF templates (PO/GRN/Invoice)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New _pdf_story() common builder + _vasu_footer(). Every PDF now has: VASU INFOSEC brand banner, tagline, colored title band, meta table (doc no/date/refs), BILL TO block with Customer ID + name + GSTIN, PROJECT DETAILS block, vendor line, alternating row shading in items table, ₹-prefixed totals, footer with address & page number. Verified via analyze_file_tool — PDF confirms all elements present."
  - task: "Tally-compatible Excel voucher export"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New GET /api/export/tally?kind=purchase|invoice. Emits Tally-standard Purchase Voucher rows: Date, Voucher No, Ref, Party Ledger + GSTIN + State, Customer ID + Name, Item, HSN, Qty, Rate, Discount, Taxable, GST%, CGST/SGST/IGST split (auto intra/inter-state based on vendor MH tag), Line Total, Narration. purchase kind uses POs; invoice kind uses vendor invoices."
  - task: "MRF 12-status pipeline (extended MRF_STATUS + canonical alias map)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "MRF_STATUS array extended to 13 canonical statuses (draft, under_review, authorised, rejected, returned, purchase_pending, quotation_received, po_pending, po_issued, partially_received, fully_received, closed, cancelled). Legacy statuses (submitted/pm_review/approved/sent_to_purchase/etc.) preserved. canonical_mrf_status() helper for alias resolution. Existing writes still use legacy names — safe migration."
  - task: "MRF line-item edit with mandatory reason + change log"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New PUT /api/mrf/{mrf_id}/items/{line_id}. Requires reason (400 without). Records per-field {old, new} into items[].change_log[] and mirrors to master_audit_logs. Locked from edit in terminal states (received/fully_received/closed/cancelled/rejected) — admin/director can override."

frontend:
  - task: "Customer ID badge on MRF/PO detail screens"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/[id].tsx, /app/frontend/app/po/[id].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Blue Vasu-branded pill under document number showing Customer ID + Customer Name. Verified via screenshot on MRF/2026/0248 — RIL-DIG · Reliance Digital Ltd visible."
  - task: "Reports screen Tally export buttons + status color mapping for new statuses"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/reports.tsx, /app/frontend/src/theme.ts"
    stuck_count: 0
    priority: "low"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Reports → Tally-Compatible Voucher Export section with two buttons: Purchase Voucher (from POs) and Purchase Voucher (from Vendor Invoices). theme.status extended with under_review/authorised/purchase_pending/po_pending/po_issued/fully_received/cancelled colors."

test_plan:
  current_focus:
    - "Customer ID snapshot on MRF/PO/Invoice + backfill"
    - "Tally-compatible Excel voucher export"
    - "MRF line-item edit with mandatory reason + change log"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "Phase 2c bundle implemented. Backend smoke test passed: new customer_id on MRF/PO responses populated; Tally export returns XLSX with correct columns and CGST/SGST split; branded PO PDF verified with Vasu banner + Customer ID + footer; MRF line-item PUT enforces reason and writes to master_audit. Please run regression: (1) Tally purchase export returns 200 with expected columns for POs; (2) Tally invoice export handles invoice line-items; (3) MRF line-item PUT: 400 without reason, 200 with reason and creates master_audit entry with entity='mrf.item'; (4) Locked-status editing blocked (fully_received, closed) except for admin/director; (5) Non-creator SE cannot edit lines they didn't create (403); (6) Existing tests still pass. Do NOT test PDF layout — was manually verified via analyze_file_tool."

## Phase 3a — Dropdown-driven MRF creation for Site Engineers

backend:
  - task: "MRFItem model: material_id + make/make_id + model/model_id + priority"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Extended MRFItemIn with master-driven selection fields. All optional (backwards-compat). priority default 'normal'."
  - task: "PUT /api/mrf/{mrf_id} — draft edit endpoint"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Only editable when status ∈ {draft, returned}. RBAC: creator OR admin/director; other SEs 403. Verified via curl: SE edits DRAFT OK → submits → edit blocked (400) → PM returns → SE edits RETURNED OK → other SE tries edit → 403."

frontend:
  - task: "MRF create screen — dropdown-only workflow for SE"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/create.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Full rewrite. Dependent dropdowns (Customer→Project→Site, Category from project.system_categories, Material auto-fills UID+description+unit, Make→Model). Searchable picker with autofocus, empty state, quick-date chips + @react-native-community/datetimepicker. Only Qty (numeric) and Remarks (free text) allow manual input. Uses ?edit=<mrf_id> query param for edit mode."
  - task: "Edit MRF button on detail screen (creator + draft/returned only)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/[id].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Added 'Edit MRF' outline button next to 'Submit for PM Review' on the actions section, visible only to creator when status is draft/returned."

test_plan:
  current_focus:
    - "PUT /api/mrf/{mrf_id} — draft edit endpoint"
    - "MRF create screen — dropdown-only workflow for SE"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "Phase 3a implemented. Manual e2e: SE creates MRF with material_id/make/model/priority — OK. SE edits draft — OK. SE submits → status pm_review — edit blocked (400). PM returns → SE can edit again — OK. Different SE forbidden — 403. Please regress: PUT /api/mrf/{id} — happy path (draft edit by creator, 200); denied after submit (400); allowed after return; RBAC (creator vs other SE vs admin); make sure customer_id snapshot updates if project changes."

## Phase 3b — MRF-opening bug + comprehensive detail view

backend:
  - task: "Audit endpoint entity-scoped access (fix MRF opening bug)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "ROOT CAUSE: GET /api/audit was admin-only, so PM/GM/Director/Purchase opening any MRF triggered a 403 that broke the whole detail page (blank state). Fixed: /api/audit?entity_id=<x> now uses per-entity access check (via _check_mrf_access / _check_po_access), and bulk audit (no entity_id) still requires admin/director. Also added entity= filter."

frontend:
  - task: "MRF list — 17-status filters, customer badges, pending count, new-tab open"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Rebuilt with all 17 canonical statuses + Pending Action filter (badge count per role owner mapping). Customer ID + Name shown on each card. YOUR ACTION badge on pending rows. On web, tapping a row opens the MRF in a NEW TAB (window.open) — falls back to router.push if popup blocked; on mobile it navigates full-screen."

  - task: "MRF detail — Customer/POs/Owner/Pending action/Print/Export + never-blank error UI"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Complete rewrite. Load errors now surface a proper 'Unable to open MRF' card with Retry + Back to List (never blank). Audit fetch is best-effort and non-blocking. New sections: Status / Current Owner / Pending Action rows in meta; Customer card with GSTIN + Customer POs; Documents card; Print (web) + Export (Excel) buttons; new canonical status handling via canonicalStatus helper."

  - task: "STATUS_LABELS + status colors for 17 canonical statuses"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/theme.ts"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "STATUS_LABELS map covers all 17 canonical + legacy aliases. Added color scheme for under_pm_review/purchase_review/gm_review/director_review. canonicalStatus() helper for legacy->canonical translation on the client."

  - task: "Empty component accepts title/subtitle in addition to msg"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/ui.tsx"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Backwards compat: accepts either msg or title+subtitle."

test_plan:
  current_focus:
    - "Audit endpoint entity-scoped access (fix MRF opening bug)"
    - "MRF list — 17-status filters, customer badges, pending count, new-tab open"
    - "MRF detail — Customer/POs/Owner/Pending action/Print/Export + never-blank error UI"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "PM/GM/Director MRF-opening bug fixed at the root (audit endpoint scoping). Verified via UI: PM can now open any accessible MRF and see Status / Current Owner / Pending Action / Customer with POs / Items grid / all action buttons (Authorise/Reject/Return/Print/Export) / Audit Trail. Regression targets: (1) GET /api/audit?entity_id=<mrf_id> now works for any user with MRF access; (2) GET /api/audit?entity_id=<po_id> for anyone with PO access; (3) GET /api/audit without entity_id still 403 for non-admin/director; (4) /api/audit?entity_id=<mrf_id> as unrelated site_engineer returns 403 (project scoping); (5) MRF list uses canonical status filters and returns matching sets; (6) Confirm no other endpoint regressions."

## Phase 4 — Material Master (MAT-####) + Variants (VAR-####) + Bulk Import

backend:
  - task: "Material UID (MAT-####) and Variant UID (VAR-####) with dedup"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "New collections: materials (unique on material_uid + description_norm), variants (unique compound on material_uid+make_norm+model_norm), counters (atomic _next_seq for MAT/VAR sequence). Format: MAT-0001, VAR-0001. Legacy master.category=material rows migrated in seed with next-available UID in creation-date order. Case-insensitive dedup on description and (material,make,model). Idempotent."
  - task: "Purchase-uploads → PM-reviews workflow for materials"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "POST /api/materials by Purchase → status=pending_pm_review (Admin/Director bypass to approved). POST /api/materials/{uid}/action (PM approve/reject/flag). POST /api/materials/bulk-action for PM bulk approve/reject. GET /api/materials?status=<x> — default returns only 'approved'; MRF picker uses status=approved so un-approved cannot be used in MRFs. Word-count guard: >100 words → 400."
  - task: "PUT /api/materials/{uid} routes changes-of-approved to pending_gm_approval"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Editing an approved material by Purchase sets status=pending_gm_approval + records pending_change. Admin/Director edits commit immediately. POST /api/materials/{uid}/gm-approve to finalise. Reason mandatory on every edit. Master audit records old->new."
  - task: "Bulk import (Excel/CSV) — POST /api/import/materials + template"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "GET /api/import/materials/template returns Excel with headers (Material Description, Category, Make, Model, Unit, GST Rate %, Item Code, Remarks) + 2 sample rows. POST /api/import/materials with {rows:[…]} — Purchase only. Dedup (skip if description_norm exists). Word limit enforced per row. Auto-creates a variant if Make provided. Returns summary {created, duplicates, errors, flagged_word_limit} for UI feedback."

frontend:
  - task: "MRF picker uses only approved Material Master (MAT-#### UIDs)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/mrf/create.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Materials loaded from /materials?status=approved instead of /masters. material_id now stores MAT-#### UID. Unapproved materials cannot appear in MRF picker."

  - task: "Unified Export/Download menu (PDF, Excel, Tally) — Phase 5"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/ExportMenu.tsx, /app/frontend/app/po/[id].tsx, /app/frontend/app/mrf/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "New ExportMenu bottom-sheet component with three tiles (PDF/Excel/Tally). Wired into PO detail (all three) and MRF detail (PDF+Excel). Preflight fetch surfaces HTTP 422 validation with a warning banner listing missing mandatory fields + optional warnings; user can 'Force Download (audit-logged)' to bypass. Every download opens in a new tab (web) / Linking (native)."

  - task: "Enhanced PO PDF — Vasu GSTIN/PAN header, MAT/VAR/HSN/Make/Model, per-line taxable+CGST/SGST/IGST, authorised signatories from approval history"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py (po_pdf)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Rewrote po_pdf endpoint. Added Vasu identity strip (legal name, GSTIN, PAN, state code) below the banner. Enriched items table now shows MAT/VAR UIDs, Make/Model, HSN, Unit, Qty, Rate, Disc, Taxable, GST%, Total. Grand total block shows CGST/SGST vs IGST split. References line shows MRF numbers, latest Customer PO reference (from Customer master), Vendor Quote. Authorisation block pulls approver names/roles/timestamps from po.approval_history + explicit signatory. Advisory row printed if optional fields missing. Validation returns 422 with missing_mandatory + warnings when mandatory fields absent; ?force=1 bypass logged in audit."

  - task: "Enhanced PO Excel (single & bulk) with line-item detail (Customer, MAT/VAR, HSN, GST split)"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py (_po_excel_workbook, /api/export/po, /api/po/{po_id}/export)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "New _po_excel_workbook helper produces 40-column per-line workbook — PO#, Date, Status, Customer ID/Name/GSTIN, Project/Site, Vendor Name/GSTIN/Address, MRF Refs, Customer PO Ref, Vendor Quote, Line#, MAT/VAR UIDs, Description, Make, Model, HSN, Unit, Qty, Rate, Discount, Taxable, GST%, CGST, SGST, IGST, Line Total, Freight, Other, Grand Total, Delivery/Payment/Warranty terms, Authorised Signatory, Approval history. Reused by /api/export/po (bulk) and /api/po/{po_id}/export?format=excel (single)."

  - task: "Enhanced Tally-compatible voucher export (Vasu GSTIN, MAT/VAR UIDs, HSN mandatory)"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py (_po_tally_workbook, /api/export/tally, /api/po/{po_id}/export?format=tally)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Voucher rows now carry Company GSTIN/State/State-Code, Party (vendor) ledger + GSTIN, Customer ID/Name/GSTIN, Project code, MAT/VAR UIDs, Make/Model, HSN (mandatory for Tally), unit, qty, rate, disc, taxable, GST%, CGST/SGST/IGST split, Line Total, Narration. HSN missing → 422 with 'Item i HSN/SAC (required for Tally)'. Bulk /api/export/tally?kind=purchase|invoice preserved; single /api/po/{po_id}/export?format=tally added."

  - task: "MRF PDF endpoint (branded) + MRF/PO unified single-record dispatchers"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py (/api/mrf/{id}/pdf, /api/mrf/{id}/export, /api/po/{id}/export)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "New branded MRF PDF with Vasu header, project/customer block, line-item table (MAT/VAR/Make/Model/Priority/Status/Purpose), remarks, approval trail. Dispatchers /api/po/{id}/export?format=pdf|excel|tally and /api/mrf/{id}/export?format=pdf|excel provide single unified download endpoint. Validation ensures mandatory fields before generating; ?force=1 bypass audit-logged."

  - task: "Export validation + audit logging for every download"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py (_validate_po_for_export, _validate_mrf_for_export, _log_export)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Two validators: PO checks Vendor name, Customer ID+name, Project, PO number/date, line items (description, qty>0, rate≥0). HSN warning for PDF/Excel; MANDATORY for Tally. Missing Vasu GSTIN → warning for PDF/Excel, MANDATORY for Tally. MRF validator similar (customer_id is warning-only). _log_export writes to audit_logs collection with action='export_{format}', details include format, record_number, warnings list, forced flag. Verified via GET /api/audit shows all 8 test exports logged with correct format+record."

test_plan:
  current_focus:
    - "UAT: LLM file-upload path (BOQ / vendor quote / invoice PDFs) — /api/llm/item-standardise, /api/llm/quotation-compare, /api/llm/reconcile"
    - "Phase 9C refactor: /api/notifications now served from routers/notifications.py"
    - "Phase 9C refactor: /api/reports/dashboard, /api/reports/mrf-ageing, /api/reports/grn-variance now served from routers/reports.py"
    - "Phase 9C refactor: /api/audit and /api/audit/facets now served from routers/audit.py"
    - "Phase 9C refactor: /api/settings/thresholds (GET+PUT) now served from routers/settings.py"
    - "server.py shrunk 5276 -> 4966 lines (~310 lines extracted)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: "Phase 9C incremental refactor round 2: extracted 4 more routers from server.py — notifications, reports (dashboard/mrf-ageing/grn-variance), audit (audit + audit/facets), settings (thresholds get/put). Pattern is identical to the existing routers/llm.py — decorators run at import time against the shared `api` APIRouter, imports done AFTER app/api are defined in server.py. Backend restarted cleanly, all 8 extracted endpoints return 200 via curl for admin role, sample payloads sane. Full LLM UAT re-run (BOQ / quote / invoice PDFs against Haiku + Sonnet) passed 0 failures.  Also created /app/backend/tests/uat_llm_files.py — auto-generates realistic reportlab PDFs and drives the 3 LLM endpoints end-to-end incl. accept/reject/list. Please run backend regression: (a) hit /notifications, /reports/dashboard, /reports/mrf-ageing, /reports/grn-variance, /audit, /audit/facets, /settings/thresholds (GET+PUT with valid & invalid payloads) for each role; (b) verify RBAC on /audit (site_engineer/store scoped feeds); (c) verify PUT /settings/thresholds rejects director<gm and non-numeric values; (d) confirm no /api/* endpoint is missing after the refactor (OpenAPI diff or curl smoke sweep)."
    -agent: "testing"
    -message: "Phase 9C router-refactor regression + LLM UAT — ALL GREEN. 21/21 pytest cases in new /app/backend/tests/test_phase9c_refactor.py. All 9 extracted endpoints byte-identical to pre-refactor behaviour. Audit RBAC leaks verified absent (site_engineer & store scoped feeds correct). Threshold PUT validation matrix: 403/400 negatives + 200 with audit row on success. OpenAPI diff shows all 9 paths + methods present. uat_llm_files.py exit 0 — BOQ standardise, quotation compare (L1 correctly identified as SafetyFirst), invoice reconcile (mismatches detected), and decide/list roundtrips all pass. No blockers. Full details: /app/test_reports/iteration_23.json."

agent_communication:
    -agent: "main"
    -message: "Phase 4 (Material Master + UIDs + Bulk Import + GM-approval flow) implemented and manually smoke-tested. All flows green in curl: MAT/VAR UIDs assigned in order, migration idempotent, dedup case-insensitive on description AND (material,make,model), word-count 400 on >100 words, bulk import summary correct, PM approve/reject/bulk, edit-of-approved → pending_gm_approval, GM approve → approved. Please run RBAC & integrity regression per the test_result tasks. Verify: (a) POST /materials 403 for site_engineer/pm/gm/store; (b) POST /materials/{uid}/action 403 for purchase/site_engineer/gm (only PM/admin/director); (c) POST /materials/{uid}/gm-approve 403 for pm/purchase/site_engineer (only GM/director/admin); (d) POST /materials duplicate description (case-insensitive) → 400; (e) POST /variants duplicate combo returns SAME variant_uid (not error); (f) POST /materials word count >100 → 400; (g) Bulk import dedup skips existing; (h) /materials default filter is approved-only; (i) Migration idempotent (running /seed twice does not double up); (j) master_audit contains entries with entity='material'."
    -agent: "main"
    -message: "Phase 5 (Unified Export/Download + Validation + Audit) implemented. New endpoints: (1) GET /api/po/{po_id}/export?format=pdf|excel|tally&force=0|1 — single-PO download dispatcher; (2) GET /api/mrf/{mrf_id}/pdf — branded MRF PDF; (3) GET /api/mrf/{mrf_id}/export?format=pdf|excel — single-MRF dispatcher; enhanced GET /api/po/{po_id}/pdf, /api/export/mrf, /api/export/po, /api/export/tally. Every export writes an audit_logs row with action='export_{format}' via _log_export(). Backend smoke-tested via curl for purchase role: PDF (200, valid %PDF), Excel single (200, 40 cols), Tally single (422 without HSN → 200 with force=1), bulk MRF/PO/Tally (all 200), MRF PDF (200), MRF Excel single (200). Audit endpoint (director role) shows all export events logged. Please: (a) verify validation returns 422 with missing_mandatory listing missing Customer ID / Vendor / HSN (for tally) etc.; (b) verify ?force=1 bypasses and still audits with forced=true; (c) verify RBAC — site_engineer denied on /api/export/po and /api/export/tally, but can download their own MRF PDF; (d) verify audit rows written for both successful downloads AND forced downloads; (e) verify the enriched PO PDF contains MAT/VAR/HSN/CGST/SGST/IGST columns and the Vasu GSTIN/PAN identity strip; (f) verify PO Excel single/bulk produces 40 columns with the requested fields; (g) confirm no regression on existing endpoints (GRN PDF, invoice PDF, /seed). Frontend: new ExportMenu bottom-sheet component wired in /po/[id] and /mrf/[id]. Preflights the request and surfaces validation errors as an in-modal warning banner with 'Force Download' button. Skip UI screenshot testing if backend is green — the component is a straightforward Modal + fetch flow."
    -agent: "testing"
    -message: "Phase 5 backend testing done — 34/36 pass, 1 skip, 1 bug. See /app/test_reports/iteration_17.json. Bug: /api/export/po missing 'pm' in role tuple (spec said pm allowed). Everything else green: validation 422 works with missing_mandatory + warnings, force=1 bypass audit-logged, tally HSN mandatory, PDF %PDF bytes, Excel 40 cols matches spec, MRF PDF works, RBAC otherwise correct, audit rows written for every export, regression on GRN/seed/materials clean."
    -agent: "main"
    -message: "Fixed the reported bug: added 'pm' to export_po role tuple. Manually re-verified: PM role now returns 200 on GET /api/export/po (was 403). Phase 5 complete."
    -agent: "main"
    -message: "Phase 6 (Audit Trail overhaul) implemented. (1) RBAC on /api/audit relaxed: admin/director/gm/purchase see full bulk feed; pm/site_engineer/store see server-side filtered feed (own actions + scoped MRF/PO + master-data for pm). (2) Login/logout events now audit-logged (entity='auth'). (3) Old/new value enrichment: MRF create/submit/approve/return/edit/soft_delete/send_to_purchase and PO create/approve/received all carry old_value/new_value/reason and record_number in audit details. (4) New endpoint GET /api/audit/facets returns distinct entities/actions/users for the filter UI. (5) Reusable frontend <AuditTrail entityId=... /> component wired into MRF detail, PO detail. Global /audit screen re-built with filter chips (entity, action, role) + free-text record ID search. Customers list gets a per-row 'View Audit' button that deep-links to /audit?entity_id=CUS-####. testing_agent iter18: 40/40 pass — verified all requirements including no ObjectId leaks and full backward compat with Phase 5 exports."
