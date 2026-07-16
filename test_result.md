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
