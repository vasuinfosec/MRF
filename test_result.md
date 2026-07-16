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
