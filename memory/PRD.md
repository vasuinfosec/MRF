# Vasu Infosec — Material Requisition & PO System

## Overview
Production-ready enterprise mobile+web app for construction / fire-safety projects. Site engineers create Material Requisition Forms (MRFs), Project Managers approve, Purchase converts approved MRFs into POs, and Billing tracks item-wise billing. Full audit trail, role-based access, PDF/Excel export.

## Stack
- Frontend: Expo Router (React Native + Web preview), safe-area-context, Ionicons
- Backend: FastAPI + Motor (MongoDB), ReportLab (PDF), openpyxl (Excel)
- Auth: Emergent Google OAuth (production) + Dev-Login (demo/testing)

## Roles
- **site_engineer** — create/submit MRFs
- **project_manager** — approve/reject/return MRFs; send to purchase
- **purchase** — build POs from approved MRFs; mark received
- **billing** — item-wise billing updates
- **admin** — full access, user/role management, soft delete

## Key API endpoints
- `POST /api/seed` — populate demo data (idempotent)
- `POST /api/auth/dev-login` — testing auth
- `POST /api/auth/session` — Emergent OAuth session exchange
- `GET  /api/auth/me`
- `POST /api/auth/logout`
- `GET/POST /api/users` and `POST /api/users/role`
- `GET/POST /api/projects` `/api/vendors` `/api/masters`
- `POST /api/mrf`, `GET /api/mrf`, `GET /api/mrf/{id}`
- `POST /api/mrf/{id}/submit`, `/approve`, `/send-to-purchase`
- `POST /api/po`, `GET /api/po`, `GET /api/po/{id}`
- `POST /api/po/{id}/received`
- `GET /api/po/{id}/pdf?token=...` — printable PO
- `GET /api/billing/items`, `POST /api/billing/update`
- `GET /api/reports/dashboard`, `GET /api/reports/mrf-ageing`
- `GET /api/audit`
- `GET /api/export/mrf?token=...`, `/api/export/po?token=...` — Excel
- `GET /api/notifications`, `POST /api/notifications/{id}/read`

## Business rules enforced
1. Site personnel cannot create POs (403).
2. Purchase cannot change approved qty silently — every change is audited.
3. PM approval required before purchase processing.
4. Every PO retains MRF references (mrf_refs array).
5. Billing is item-wise (billing_status per line).
6. Cannot mark item Fully Billed unless billed >= received (override with reason).
7. Rejected items cannot be added to a PO.
8. Soft delete only (deleted flag).
9. Every action logged in audit_logs collection.

## Screens
- /login, /home, /mrf (list), /mrf/create, /mrf/[id]
- /po (list), /po/create, /po/[id]
- /billing, /reports, /audit, /notifications, /more (settings + users + masters)

## Sample seed data
- 3 Projects (VIS-101 ABC IT Park, VIS-102 XYZ Data Center, VIS-103 PQR Mall)
- 5 Vendors (Honeywell, Siemens, Bosch, Ravel, Anixter)
- 10 Materials, 5 Units, 5 Brands
- 5 Demo users (one per role)

## Notes
- Design: Industrial navy (#002FA7) + safety orange (#F97316), high-contrast Swiss/Grid Borders style
- Mobile-first with 48pt tap targets; SafeArea-aware; bottom tabs
- Excel/PDF downloads open in new tab using `?token=` query param
