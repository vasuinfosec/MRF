"""
Vasu Infosec — Material Requisition & Purchase Order System
Backend: FastAPI + MongoDB + Emergent Google Auth
"""
import os
import io
import re
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal, Dict, Any

import httpx
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, Response, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Vasu Infosec MRF & PO System")
api = APIRouter(prefix="/api")

# ---------------------- Constants ----------------------
# Vasu operational chain: Site Engineer -> PM -> Purchase -> GM -> Director.
# Admin is a system-management role and NOT part of the approval chain by default.
ROLES = ["site_engineer", "pm", "purchase", "gm", "director", "admin", "store"]
LEGACY_ROLE_MAP = {
    # Historic aliases -> canonical roles. site_engineer is now a first-class role
    # and MUST NOT be mapped to pm any more.
    "project_manager": "pm",
    "billing": "purchase",
}
def _canon_role(r: str) -> str:
    return LEGACY_ROLE_MAP.get(r, r) if r in LEGACY_ROLE_MAP else r

MRF_APPROVERS = {"pm", "gm", "director", "admin"}
MRF_EDITORS = {"site_engineer", "pm", "gm", "purchase", "director", "admin"}
MRF_CREATORS = {"site_engineer", "pm", "director", "admin"}
GRN_ROLES = {"site_engineer", "store", "purchase", "pm", "director", "admin"}

# --- Purchase approval thresholds (INR). Editable via /api/settings/thresholds ---
DEFAULT_THRESHOLD_GM = 50000.0        # PO value above this needs GM approval
DEFAULT_THRESHOLD_DIRECTOR = 500000.0  # PO value above this needs Director approval

async def get_thresholds() -> Dict[str, float]:
    doc = await db.settings.find_one({"_id": "thresholds"}, {"_id": 0})
    if not doc:
        return {"gm": DEFAULT_THRESHOLD_GM, "director": DEFAULT_THRESHOLD_DIRECTOR}
    return {
        "gm": float(doc.get("gm", DEFAULT_THRESHOLD_GM)),
        "director": float(doc.get("director", DEFAULT_THRESHOLD_DIRECTOR)),
    }

def _po_initial_status(total: float, gm_t: float, dir_t: float) -> str:
    if total > dir_t:
        return "pending_director_approval"
    if total > gm_t:
        return "pending_gm_approval"
    return "issued"
SYSTEMS = ["Fire Alarm", "Fire Fighting", "Gas Suppression", "Water Mist",
           "CCTV", "Access Control", "Structured Cabling", "Electrical", "Other"]
MRF_STATUS = ["draft", "under_review", "authorised", "rejected", "returned",
              "purchase_pending", "quotation_received", "po_pending",
              "po_issued", "partially_received", "fully_received",
              "closed", "cancelled",
              # legacy aliases retained for backwards compat with existing data:
              "submitted", "pm_review", "approved", "sent_to_purchase",
              "partially_ordered", "fully_ordered", "received"]

# Canonical status alias map (legacy -> new). New statuses map to themselves.
MRF_STATUS_ALIAS = {
    "submitted": "under_review",
    "pm_review": "under_review",
    "approved": "authorised",
    "sent_to_purchase": "purchase_pending",
    "partially_ordered": "po_issued",
    "fully_ordered": "po_issued",
    "received": "fully_received",
}
def canonical_mrf_status(s: str) -> str:
    return MRF_STATUS_ALIAS.get(s or "", s or "")
BILLING_STATUS = ["not_billed", "partially_billed", "fully_billed", "non_billable"]

# ---------------------- Models ----------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def gid(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class UserOut(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: str = "site_engineer"
    is_active: bool = True

class RoleUpdate(BaseModel):
    user_id: str
    role: str

class SessionRequest(BaseModel):
    session_id: str

class Site(BaseModel):
    site_id: str = Field(default_factory=lambda: gid("st"))
    name: str
    location: Optional[str] = ""
    site_engineers: List[str] = []
    active: bool = True

class Project(BaseModel):
    project_id: str = Field(default_factory=lambda: gid("prj"))
    code: str
    name: str
    site: str
    client: Optional[str] = None                 # legacy free-text client name (kept for backwards compat)
    customer_id: Optional[str] = None            # FK to Customer.customer_id (permanent, alphanumeric)
    active: bool = True
    site_engineers: List[str] = []      # user_ids at project level
    project_managers: List[str] = []    # user_ids
    sites: List[Site] = []              # sub-sites under this project
    system_categories: List[str] = []   # e.g. ["Fire Alarm", "CCTV"]

class Vendor(BaseModel):
    vendor_id: str = Field(default_factory=lambda: gid("vnd"))
    name: str
    address: Optional[str] = ""
    gstin: Optional[str] = ""
    contact: Optional[str] = ""
    email: Optional[str] = ""
    active: bool = True

class MasterItem(BaseModel):
    item_id: str = Field(default_factory=lambda: gid("itm"))
    name: str
    category: str  # unit/system/brand/material/model/gst/department
    parent_id: Optional[str] = None   # e.g. Model.parent_id -> Brand.item_id
    value: Optional[str] = None       # generic extra (e.g. GST rate "18", HSN code, dept code)
    active: bool = True

# ---------------------- Customer & Customer PO ----------------------
CUSTOMER_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")

class CustomerPO(BaseModel):
    """A customer-side PO issued to Vasu — anchors project billing/collection."""
    cpo_id: str = Field(default_factory=lambda: gid("cpo"))
    customer_id: Optional[str] = ""      # populated from URL path; client may omit
    po_number: str
    po_date: Optional[str] = None        # ISO date "YYYY-MM-DD"
    value: float = 0.0
    validity_till: Optional[str] = None  # ISO date
    attachment_name: Optional[str] = None
    attachment_b64: Optional[str] = None  # base64 (small files only)
    remarks: Optional[str] = ""
    active: bool = True

class Customer(BaseModel):
    customer_id: str                     # PERMANENT, admin-typed alphanumeric (e.g. "VASU-CUST-001")
    name: str
    gstin: Optional[str] = ""
    pan: Optional[str] = ""
    billing_address: Optional[str] = ""
    shipping_address: Optional[str] = ""
    contact_person: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    remarks: Optional[str] = ""
    active: bool = True
    created_at: datetime = Field(default_factory=now_utc)

class MRFItemIn(BaseModel):
    description: str
    specification: Optional[str] = ""
    part_number: Optional[str] = ""
    unit: str
    qty_requested: float
    qty_approved: Optional[float] = None
    purpose: Optional[str] = ""
    drawing_ref: Optional[str] = ""
    billable: bool = True
    boq_ref: Optional[str] = ""
    remarks: Optional[str] = ""

class MRFItem(MRFItemIn):
    item_line_id: str = Field(default_factory=lambda: gid("mli"))
    status: str = "pending"  # pending/approved/rejected
    rejection_reason: Optional[str] = ""
    billing_status: str = "not_billed"
    qty_received: float = 0
    qty_issued: float = 0
    qty_billed: float = 0
    qty_ordered: float = 0
    client_bill_ref: Optional[str] = ""
    ra_bill_no: Optional[str] = ""
    billing_date: Optional[str] = ""
    billing_remarks: Optional[str] = ""

class MRFCreate(BaseModel):
    project_id: str
    site: str
    required_by: str
    requesting_person: str
    system_category: str
    items: List[MRFItemIn]
    attachments: List[str] = []  # base64 or descriptions
    remarks: Optional[str] = ""

class MRF(BaseModel):
    mrf_id: str = Field(default_factory=lambda: gid("mrf"))
    mrf_number: str
    date: datetime = Field(default_factory=now_utc)
    project_id: str
    site: str
    required_by: str
    requesting_person: str
    system_category: str
    customer_id: Optional[str] = None          # snapshot from project at create time
    customer_name: Optional[str] = None        # snapshot for display / exports
    items: List[MRFItem]
    attachments: List[str] = []
    remarks: str = ""
    status: str = "draft"
    created_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    pm_comments: str = ""
    deleted: bool = False

class POItemIn(BaseModel):
    mrf_id: str
    item_line_id: str
    description: str
    specification: Optional[str] = ""
    unit: str
    qty: float
    rate: float = 0
    discount: float = 0
    gst: float = 18
    remarks: Optional[str] = ""

class POCreate(BaseModel):
    vendor_id: str
    project_id: str
    delivery_site: str
    items: List[POItemIn]
    delivery_schedule: Optional[str] = ""
    payment_terms: Optional[str] = ""
    warranty_terms: Optional[str] = ""
    freight: float = 0
    other_charges: float = 0
    authorised_signatory: Optional[str] = ""
    vendor_quotation: Optional[str] = ""

class PO(POCreate):
    po_id: str = Field(default_factory=lambda: gid("po"))
    po_number: str
    date: datetime = Field(default_factory=now_utc)
    mrf_refs: List[str] = []
    status: str = "issued"  # issued/received/closed
    total: float = 0
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    created_by: str
    created_at: datetime = Field(default_factory=now_utc)
    deleted: bool = False

class BillingUpdate(BaseModel):
    mrf_id: str
    item_line_id: str
    qty_received: Optional[float] = None
    qty_issued: Optional[float] = None
    qty_billed: Optional[float] = None
    client_bill_ref: Optional[str] = None
    ra_bill_no: Optional[str] = None
    billing_date: Optional[str] = None
    billing_remarks: Optional[str] = None
    billing_status: Optional[str] = None
    override_reason: Optional[str] = None

class ApprovalAction(BaseModel):
    action: str  # approve/reject/return
    comment: Optional[str] = ""
    item_actions: Optional[List[Dict[str, Any]]] = None  # [{item_line_id, action, qty_approved, reason}]

# ---------------------- Auth ----------------------
async def get_current_user(authorization: Optional[str] = Header(None)) -> UserOut:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    exp = sess["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Auto-migrate legacy roles on read
    if user.get("role") in LEGACY_ROLE_MAP:
        canon = LEGACY_ROLE_MAP[user["role"]]
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"role": canon}})
        user["role"] = canon
    return UserOut(**user)

def require_roles(*allowed):
    async def dep(user: UserOut = None, authorization: Optional[str] = Header(None)):
        u = await get_current_user(authorization)
        if u.role not in allowed and u.role != "admin":
            raise HTTPException(status_code=403, detail=f"Role {u.role} not allowed")
        return u
    return dep

@api.post("/auth/session")
async def create_session(body: SessionRequest):
    async with httpx.AsyncClient(timeout=15) as client_http:
        r = await client_http.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": body.session_id},
        )
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session_id")
        data = r.json()

    email = data["email"]
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        role = existing.get("role", "site_engineer")
        # Canonicalize legacy role on login
        if role in LEGACY_ROLE_MAP:
            role = LEGACY_ROLE_MAP[role]
            await db.users.update_one({"email": email}, {"$set": {"role": role}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        # First user becomes admin; subsequent unknown users default to site_engineer
        # (lowest-privilege in the approval chain).
        count = await db.users.count_documents({})
        role = "admin" if count == 0 else "site_engineer"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": data.get("name", email),
            "picture": data.get("picture", ""),
            "role": role,
            "is_active": True,
            "created_at": now_utc(),
        })

    session_token = data["session_token"]
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": now_utc() + timedelta(days=7),
            "created_at": now_utc(),
        }},
        upsert=True,
    )
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": session_token, "user": UserOut(**user).model_dump()}

@api.get("/auth/me", response_model=UserOut)
async def me(authorization: Optional[str] = Header(None)):
    return await get_current_user(authorization)

@api.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}

@api.post("/auth/dev-login")
async def dev_login(body: dict):
    """Dev-only endpoint. Disabled in production via ENABLE_DEV_LOGIN env flag."""
    if os.environ.get("ENABLE_DEV_LOGIN", "0") != "1":
        raise HTTPException(404, "Not found")
    email = body.get("email")
    role = body.get("role", "pm")
    name = body.get("name", email.split("@")[0] if email else "Dev User")
    if not email:
        raise HTTPException(400, "email required")
    if role not in ROLES:
        raise HTTPException(400, "invalid role")
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"role": role, "name": name}})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id, "email": email, "name": name, "picture": "",
            "role": role, "is_active": True, "created_at": now_utc(),
        })
    session_token = f"dev_{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "session_token": session_token, "user_id": user_id,
        "expires_at": now_utc() + timedelta(days=7), "created_at": now_utc(),
    })
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": session_token, "user": UserOut(**user).model_dump()}

# ---------------------- Users / Roles ----------------------
@api.get("/users", response_model=List[UserOut])
async def list_users(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        # Non-admin: return only lightweight directory info (name/role) without emails
        users = await db.users.find({}, {"_id": 0}).to_list(1000)
        return [UserOut(**{**x, "email": ""}) for x in users]
    users = await db.users.find({}, {"_id": 0}).to_list(1000)
    return [UserOut(**u2) for u2 in users]

@api.post("/users/role", response_model=UserOut)
async def set_role(body: RoleUpdate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin can change roles")
    if body.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    r = await db.users.update_one({"user_id": body.user_id}, {"$set": {"role": body.role}})
    if r.matched_count == 0:
        raise HTTPException(404, "User not found")
    user = await db.users.find_one({"user_id": body.user_id}, {"_id": 0})
    return UserOut(**user)

# ---------------------- Audit ----------------------
async def audit(entity: str, entity_id: str, action: str, user: UserOut, details: dict = None):
    await db.audit_logs.insert_one({
        "audit_id": gid("aud"),
        "entity": entity,
        "entity_id": entity_id,
        "action": action,
        "user_id": user.user_id,
        "user_name": user.name,
        "user_role": user.role,
        "details": details or {},
        "timestamp": now_utc(),
    })

def _strip_oids(o):
    """Recursively strip `_id` keys and convert ObjectId/datetime to JSON-safe primitives."""
    from bson import ObjectId
    if isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, dict):
        return {k: _strip_oids(v) for k, v in o.items() if k != "_id"}
    if isinstance(o, list):
        return [_strip_oids(v) for v in o]
    if isinstance(o, datetime):
        return o.isoformat()
    return o

async def master_audit(entity: str, entity_id: str, action: str, user: UserOut,
                       reason: str, old_value: Any = None, new_value: Any = None):
    """Master-data change log — captures WHO, WHEN, WHY, and BEFORE/AFTER values."""
    old_value = _strip_oids(old_value)
    new_value = _strip_oids(new_value)
    ts = now_utc()
    await db.master_audit_logs.insert_one({
        "audit_id": gid("maud"),
        "entity": entity,
        "entity_id": entity_id,
        "action": action,
        "user_id": user.user_id,
        "user_name": user.name,
        "user_role": user.role,
        "reason": reason or "",
        "old_value": old_value,
        "new_value": new_value,
        "timestamp": ts,
    })
    # Mirror into the main audit log too so /api/audit sees it
    await db.audit_logs.insert_one({
        "audit_id": gid("aud"),
        "entity": entity,
        "entity_id": entity_id,
        "action": action,
        "user_id": user.user_id,
        "user_name": user.name,
        "user_role": user.role,
        "details": {"reason": reason, "old": old_value, "new": new_value},
        "timestamp": ts,
    })

async def notify(user_ids: List[str], title: str, body_text: str, link: str = ""):
    for uid in user_ids:
        await db.notifications.insert_one({
            "notification_id": gid("ntf"),
            "user_id": uid,
            "title": title,
            "body": body_text,
            "link": link,
            "read": False,
            "created_at": now_utc(),
        })

# ---------------------- Master Data ----------------------
@api.get("/projects")
async def list_projects(all: Optional[bool] = False,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"active": True}
    docs = await db.projects.find(q, {"_id": 0}).to_list(500)
    # Purchase/GM/Director/Admin see all projects.
    if all and u.role == "admin":
        return docs
    if u.role in ("purchase", "gm", "director", "admin"):
        return docs
    if u.role == "site_engineer":
        docs = [
            p for p in docs
            if u.user_id in (p.get("site_engineers") or [])
            or any(u.user_id in (s.get("site_engineers") or [])
                   for s in (p.get("sites") or []) if s.get("active", True))
        ]
    elif u.role == "pm":
        docs = [p for p in docs if u.user_id in (p.get("project_managers") or [])]
    elif u.role == "store":
        # Store users see projects where they're listed as site_engineer (they work at a site)
        docs = [
            p for p in docs
            if u.user_id in (p.get("site_engineers") or [])
            or any(u.user_id in (s.get("site_engineers") or [])
                   for s in (p.get("sites") or []) if s.get("active", True))
        ]
    return docs

# --- Site management (sub-master under Project) ---
@api.post("/projects/{project_id}/sites")
async def add_site(project_id: str, body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Site name required")
    site = {
        "site_id": gid("st"),
        "name": name,
        "location": (body.get("location") or "").strip(),
        "site_engineers": list(body.get("site_engineers") or []),
        "active": True,
    }
    r = await db.projects.update_one({"project_id": project_id},
                                     {"$push": {"sites": site}})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "site_add", u, {"site": name})
    return site

@api.put("/projects/{project_id}/sites/{site_id}")
async def update_site(project_id: str, site_id: str, body: dict,
                      authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    updates: Dict[str, Any] = {}
    for k in ("name", "location"):
        if k in body:
            updates[f"sites.$.{k}"] = str(body[k] or "").strip()
    if "site_engineers" in body and isinstance(body["site_engineers"], list):
        updates["sites.$.site_engineers"] = [str(x) for x in body["site_engineers"]]
    if "active" in body:
        updates["sites.$.active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    r = await db.projects.update_one(
        {"project_id": project_id, "sites.site_id": site_id},
        {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Site not found")
    await audit("project", project_id, "site_update", u, {"site_id": site_id, **body})
    proj = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    return next((s for s in (proj.get("sites") or []) if s["site_id"] == site_id), None)

@api.delete("/projects/{project_id}/sites/{site_id}")
async def remove_site(project_id: str, site_id: str,
                      authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    r = await db.projects.update_one(
        {"project_id": project_id, "sites.site_id": site_id},
        {"$set": {"sites.$.active": False}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Site not found")
    await audit("project", project_id, "site_delete", u, {"site_id": site_id})
    return {"ok": True}

@api.post("/projects/{project_id}/team")
async def update_project_team(
    project_id: str,
    body: dict,
    authorization: Optional[str] = Header(None),
):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    site_engineers = body.get("site_engineers")
    project_managers = body.get("project_managers")
    update: Dict[str, Any] = {}
    if isinstance(site_engineers, list):
        update["site_engineers"] = [str(x) for x in site_engineers]
    if isinstance(project_managers, list):
        update["project_managers"] = [str(x) for x in project_managers]
    if not update:
        raise HTTPException(400, "Nothing to update")
    r = await db.projects.update_one({"project_id": project_id}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "team_update", u, update)
    return await db.projects.find_one({"project_id": project_id}, {"_id": 0})

@api.post("/projects")
async def add_project(p: Project, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ["admin"]:
        raise HTTPException(403, "Only admin")
    # If customer_id provided, verify it exists
    if p.customer_id:
        cust = await db.customers.find_one({"customer_id": p.customer_id}, {"_id": 0})
        if not cust:
            raise HTTPException(400, f"Customer '{p.customer_id}' not found — create the Customer master first")
        # Auto-fill legacy client text with customer name for backwards compat
        if not p.client:
            p.client = cust.get("name") or ""
    await db.projects.insert_one(p.model_dump())
    await master_audit("project", p.project_id, "create", u, "Initial creation", None, p.model_dump())
    return p

@api.put("/projects/{project_id}")
async def update_project(project_id: str, body: dict,
                         authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    existing = await db.projects.find_one({"project_id": project_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Project not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")
    updates: Dict[str, Any] = {}
    for k in ("code", "name", "site", "client", "customer_id"):
        if k in body:
            updates[k] = str(body[k] or "").strip() or None
    if "system_categories" in body and isinstance(body["system_categories"], list):
        updates["system_categories"] = [str(x) for x in body["system_categories"]]
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    # Validate customer_id if changed
    if updates.get("customer_id"):
        cust = await db.customers.find_one({"customer_id": updates["customer_id"]}, {"_id": 0})
        if not cust:
            raise HTTPException(400, f"Customer '{updates['customer_id']}' not found")
    await db.projects.update_one({"project_id": project_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit("project", project_id, "update", u, reason, old_snap, updates)
    return await db.projects.find_one({"project_id": project_id}, {"_id": 0})

@api.delete("/projects/{project_id}")
async def deactivate_project(project_id: str, reason: str = "Deactivated",
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    r = await db.projects.update_one({"project_id": project_id},
                                     {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await master_audit("project", project_id, "deactivate", u, reason,
                       {"active": True}, {"active": False})
    return {"ok": True}

@api.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, body: dict,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    existing = await db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Vendor not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")
    updates: Dict[str, Any] = {}
    for k in ("name", "address", "gstin", "contact", "email"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.vendors.update_one({"vendor_id": vendor_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit("vendor", vendor_id, "update", u, reason, old_snap, updates)
    return await db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})

@api.delete("/vendors/{vendor_id}")
async def deactivate_vendor(vendor_id: str, reason: str = "Deactivated",
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    r = await db.vendors.update_one({"vendor_id": vendor_id},
                                    {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Vendor not found")
    await master_audit("vendor", vendor_id, "deactivate", u, reason,
                       {"active": True}, {"active": False})
    return {"ok": True}

# ---------------------- Customers ----------------------
def _validate_customer_id(cid: str) -> str:
    cid = (cid or "").strip()
    if not cid:
        raise HTTPException(400, "Customer ID is required")
    if not CUSTOMER_ID_REGEX.match(cid):
        raise HTTPException(400, "Customer ID must be alphanumeric (letters, digits, - or _, max 32 chars, must start with a letter or digit)")
    return cid

@api.get("/customers")
async def list_customers(include_inactive: bool = False,
                         authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    q: Dict[str, Any] = {} if include_inactive else {"active": True}
    docs = await db.customers.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    # Attach cpo count per customer for UI hint
    for c in docs:
        c["po_count"] = await db.customer_pos.count_documents({"customer_id": c["customer_id"], "active": True})
    return docs

@api.get("/customers/{customer_id}")
async def get_customer(customer_id: str, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    c = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer not found")
    c["customer_pos"] = await db.customer_pos.find(
        {"customer_id": customer_id}, {"_id": 0, "attachment_b64": 0}
    ).to_list(200)
    return c

@api.post("/customers")
async def create_customer(body: Customer, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can manage customers")
    cid = _validate_customer_id(body.customer_id)
    body.customer_id = cid
    # Uniqueness (case-insensitive on both ID and name)
    if await db.customers.find_one({"customer_id": {"$regex": f"^{re.escape(cid)}$", "$options": "i"}}):
        raise HTTPException(400, f"Customer ID '{cid}' already exists")
    if body.name.strip() and await db.customers.find_one({
        "name": {"$regex": f"^{re.escape(body.name.strip())}$", "$options": "i"}
    }):
        raise HTTPException(400, f"Customer name '{body.name}' already exists — edit the existing record instead.")
    doc = body.model_dump()
    doc["name"] = body.name.strip()
    doc["customer_id"] = cid
    await db.customers.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("customer", cid, "create", u, "Initial creation", None, doc)
    return doc

@api.put("/customers/{customer_id}")
async def update_customer(customer_id: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    existing = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Customer not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")

    # Handle Customer ID change with CASCADE update to all references
    new_cid = body.pop("customer_id", None)
    if new_cid and new_cid != customer_id:
        new_cid = _validate_customer_id(new_cid)
        if await db.customers.find_one({"customer_id": {"$regex": f"^{re.escape(new_cid)}$", "$options": "i"}}):
            raise HTTPException(400, f"Customer ID '{new_cid}' already exists")
        # Cascade update
        await db.customers.update_one({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await db.customer_pos.update_many({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await db.projects.update_many({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await db.mrfs.update_many({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await db.pos.update_many({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await db.invoices.update_many({"customer_id": customer_id}, {"$set": {"customer_id": new_cid}})
        await master_audit("customer", new_cid, "rename_id", u, reason,
                           {"customer_id": customer_id}, {"customer_id": new_cid})
        customer_id = new_cid

    updates: Dict[str, Any] = {}
    for k in ("name", "gstin", "pan", "billing_address", "shipping_address",
              "contact_person", "phone", "email", "remarks"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "active" in body:
        updates["active"] = bool(body["active"])
    if updates:
        # Name uniqueness check on rename
        if "name" in updates and updates["name"] and updates["name"].lower() != (existing.get("name") or "").lower():
            dup = await db.customers.find_one({
                "customer_id": {"$ne": customer_id},
                "name": {"$regex": f"^{re.escape(updates['name'])}$", "$options": "i"}
            })
            if dup:
                raise HTTPException(400, f"Another customer already has the name '{updates['name']}'")
        await db.customers.update_one({"customer_id": customer_id}, {"$set": updates})
        old_snapshot = {k: existing.get(k) for k in updates}
        await master_audit("customer", customer_id, "update", u, reason, old_snapshot, updates)
    return await db.customers.find_one({"customer_id": customer_id}, {"_id": 0})

@api.delete("/customers/{customer_id}")
async def deactivate_customer(customer_id: str, reason: str = "Deactivated by admin",
                              authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    r = await db.customers.update_one({"customer_id": customer_id},
                                      {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    await master_audit("customer", customer_id, "deactivate", u, reason,
                       {"active": True}, {"active": False})
    return {"ok": True}

# ---- Customer POs (nested under Customer) ----
@api.post("/customers/{customer_id}/pos")
async def add_customer_po(customer_id: str, body: CustomerPO,
                          authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "purchase"):
        raise HTTPException(403, "Not allowed")
    cust = await db.customers.find_one({"customer_id": customer_id}, {"_id": 0, "customer_id": 1})
    if not cust:
        raise HTTPException(404, "Customer not found")
    body.customer_id = customer_id
    doc = body.model_dump()
    await db.customer_pos.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("customer_po", body.cpo_id, "create", u,
                       "Added customer PO", None,
                       {k: v for k, v in doc.items() if k != "attachment_b64"})
    return {k: v for k, v in doc.items() if k != "attachment_b64"}

@api.put("/customers/{customer_id}/pos/{cpo_id}")
async def update_customer_po(customer_id: str, cpo_id: str, body: dict,
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "purchase"):
        raise HTTPException(403, "Not allowed")
    reason = (body.pop("reason", "") or "").strip() or "Update customer PO"
    existing = await db.customer_pos.find_one({"cpo_id": cpo_id, "customer_id": customer_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Customer PO not found")
    updates: Dict[str, Any] = {}
    for k in ("po_number", "po_date", "validity_till", "remarks", "attachment_name", "attachment_b64"):
        if k in body:
            updates[k] = body[k]
    if "value" in body:
        try:
            updates["value"] = float(body["value"])
        except Exception:
            raise HTTPException(400, "Invalid value")
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.customer_pos.update_one({"cpo_id": cpo_id}, {"$set": updates})
    redacted_old = {k: (existing.get(k) if k != "attachment_b64" else "[file]") for k in updates}
    redacted_new = {k: (updates.get(k) if k != "attachment_b64" else "[file]") for k in updates}
    await master_audit("customer_po", cpo_id, "update", u, reason, redacted_old, redacted_new)
    return await db.customer_pos.find_one({"cpo_id": cpo_id}, {"_id": 0, "attachment_b64": 0})

@api.get("/customers/{customer_id}/pos/{cpo_id}/attachment")
async def get_customer_po_attachment(customer_id: str, cpo_id: str,
                                     authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    d = await db.customer_pos.find_one({"cpo_id": cpo_id, "customer_id": customer_id}, {"_id": 0})
    if not d or not d.get("attachment_b64"):
        raise HTTPException(404, "Attachment not found")
    return {"filename": d.get("attachment_name") or "customer_po", "content_b64": d["attachment_b64"]}

# ---------------------- Master-data audit log (view) ----------------------
@api.get("/master-audit")
async def master_audit_list(entity: Optional[str] = None,
                            entity_id: Optional[str] = None,
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    q: Dict[str, Any] = {}
    if entity: q["entity"] = entity
    if entity_id: q["entity_id"] = entity_id
    docs = await db.master_audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).limit(500).to_list(500)
    # Defensive: strip any stray ObjectIds/datetimes deep in old_value/new_value
    return [_strip_oids(d) for d in docs]

@api.get("/systems")
async def list_systems(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    return SYSTEMS

@api.get("/vendors")
async def list_vendors(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    return await db.vendors.find({"active": True}, {"_id": 0}).to_list(500)

@api.post("/vendors")
async def add_vendor(v: Vendor, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "purchase", "director"):
        raise HTTPException(403, "Not allowed")
    await db.vendors.insert_one(v.model_dump())
    await audit("vendor", v.vendor_id, "create", u, v.model_dump())
    return v

@api.get("/masters")
async def list_masters(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    items = await db.masters.find({"active": True}, {"_id": 0}).to_list(2000)
    grouped: Dict[str, List] = {"unit": [], "brand": [], "system": [], "material": [],
                                "model": [], "gst": [], "department": []}
    for it in items:
        grouped.setdefault(it["category"], []).append(it)
    grouped["system"] = grouped.get("system") or [{"name": s} for s in SYSTEMS]
    return grouped

@api.post("/masters")
async def add_master(m: MasterItem, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    doc = m.model_dump()
    doc["name"] = doc["name"].strip()
    if not doc["name"]:
        raise HTTPException(400, "Name required")
    # Category-specific validation
    if doc["category"] == "gst":
        try:
            float(doc.get("value") or "0")
        except Exception:
            raise HTTPException(400, "GST value must be a numeric percentage (e.g. 18)")
    # Prevent duplicate within same category (case-insensitive)
    dup = await db.masters.find_one({
        "category": doc["category"],
        "name": {"$regex": f"^{re.escape(doc['name'])}$", "$options": "i"},
        "active": True,
    })
    if dup:
        raise HTTPException(400, f"'{doc['name']}' already exists in {doc['category']}")
    await db.masters.insert_one(doc)
    doc.pop("_id", None)
    await master_audit(f"master.{doc['category']}", doc["item_id"], "create", u,
                       "Initial creation", None, doc)
    return doc

@api.put("/masters/{item_id}")
async def update_master(item_id: str, body: dict,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for master-data changes")
    existing = await db.masters.find_one({"item_id": item_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    updates: Dict[str, Any] = {}
    for k in ("name", "parent_id", "value"):
        if k in body:
            updates[k] = str(body[k] or "").strip() or None
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await db.masters.update_one({"item_id": item_id}, {"$set": updates})
    old_snap = {k: existing.get(k) for k in updates}
    await master_audit(f"master.{existing['category']}", item_id, "update", u,
                       reason, old_snap, updates)
    return await db.masters.find_one({"item_id": item_id}, {"_id": 0})

@api.delete("/masters/{item_id}")
async def deactivate_master(item_id: str, reason: str = "Deactivated",
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director")
    existing = await db.masters.find_one({"item_id": item_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Not found")
    await db.masters.update_one({"item_id": item_id}, {"$set": {"active": False}})
    await master_audit(f"master.{existing['category']}", item_id, "deactivate", u,
                       reason, {"active": True}, {"active": False})
    return {"ok": True}

# ---------------------- MRF ----------------------
async def next_mrf_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"mrf_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True
    )
    seq = r["seq"] if r else 1
    return f"MRF/{year}/{seq:04d}"

async def next_po_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"po_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True
    )
    seq = r["seq"] if r else 1
    return f"PO/{year}/{seq:04d}"

async def next_grn_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"grn_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True
    )
    seq = r["seq"] if r else 1
    return f"GRN/{year}/{seq:04d}"

async def next_invoice_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"inv_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True
    )
    seq = r["seq"] if r else 1
    return f"INV/{year}/{seq:04d}"

@api.post("/mrf")
async def create_mrf(body: MRFCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in MRF_CREATORS:
        raise HTTPException(403, "Not allowed to create MRF")
    # Project team assignment check (admin/director bypass)
    if u.role in ("site_engineer", "pm"):
        p = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Project not found")
        if u.role == "site_engineer":
            in_project = u.user_id in (p.get("site_engineers") or [])
            in_any_site = any(u.user_id in (s.get("site_engineers") or [])
                              for s in (p.get("sites") or []) if s.get("active", True))
            if not (in_project or in_any_site):
                raise HTTPException(403, "You are not assigned to this project")
        else:  # pm
            if u.user_id not in (p.get("project_managers") or []):
                raise HTTPException(403, "You are not the PM for this project")
    items = []
    for i in body.items:
        d = i.model_dump()
        if d.get("qty_approved") is None:
            d["qty_approved"] = i.qty_requested
        items.append(MRFItem(**d))
    # Snapshot customer info from project (for reporting / exports / cross-collection joins)
    proj = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
    cust_id = (proj or {}).get("customer_id")
    cust_name = ""
    if cust_id:
        c = await db.customers.find_one({"customer_id": cust_id}, {"_id": 0, "name": 1})
        cust_name = (c or {}).get("name") or ""
    if not cust_name:
        cust_name = (proj or {}).get("client") or ""
    mrf = MRF(
        mrf_number=await next_mrf_number(),
        project_id=body.project_id,
        site=body.site,
        required_by=body.required_by,
        requesting_person=body.requesting_person,
        system_category=body.system_category,
        customer_id=cust_id,
        customer_name=cust_name,
        items=items,
        attachments=body.attachments,
        remarks=body.remarks or "",
        status="draft",
        created_by=u.user_id,
    )
    await db.mrfs.insert_one(mrf.model_dump())
    await audit("mrf", mrf.mrf_id, "create", u, {"mrf_number": mrf.mrf_number})
    return mrf.model_dump()

@api.get("/mrf")
async def list_mrfs(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    system_category: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if status:
        q["status"] = status
    if project_id:
        q["project_id"] = project_id
    if system_category:
        q["system_category"] = system_category
    # Role-based visibility:
    # site_engineer -> only MRFs they created
    # pm -> MRFs from projects where they are project_manager
    # purchase/gm/director/admin -> all
    if u.role == "site_engineer":
        q["created_by"] = u.user_id
    elif u.role == "pm":
        prjs = await db.projects.find(
            {"project_managers": u.user_id}, {"_id": 0, "project_id": 1}
        ).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    elif u.role == "store":
        # Store user: see MRFs for the projects/sites they're posted at (via site_engineers list)
        prjs = await db.projects.find(
            {"$or": [
                {"site_engineers": u.user_id},
                {"sites.site_engineers": u.user_id},
            ]}, {"_id": 0, "project_id": 1}
        ).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    docs = await db.mrfs.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

async def _check_mrf_access(u: UserOut, mrf: dict):
    """Raise 403 if user cannot see this MRF."""
    if u.role in ("admin", "purchase", "gm", "director"):
        return
    if u.role == "site_engineer":
        if mrf.get("created_by") == u.user_id:
            return
        raise HTTPException(403, "Not allowed")
    if u.role == "pm":
        p = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0})
        if p and u.user_id in (p.get("project_managers") or []):
            return
        raise HTTPException(403, "Not allowed")
    if u.role == "store":
        p = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0})
        if p and (u.user_id in (p.get("site_engineers") or []) or
                  any(u.user_id in (s.get("site_engineers") or [])
                      for s in (p.get("sites") or []) if s.get("active", True))):
            return
        raise HTTPException(403, "Not allowed")
    raise HTTPException(403, "Not allowed")

async def _check_po_access(u: UserOut, po: dict):
    if u.role in ("admin", "purchase", "gm", "director"):
        return
    if u.role == "pm":
        p = await db.projects.find_one({"project_id": po.get("project_id")}, {"_id": 0})
        if p and u.user_id in (p.get("project_managers") or []):
            return
    if u.role == "site_engineer":
        # Site engineer can see POs originating from MRFs they created
        for mid in po.get("mrf_refs") or []:
            m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "created_by": 1})
            if m and m.get("created_by") == u.user_id:
                return
    if u.role == "store":
        p = await db.projects.find_one({"project_id": po.get("project_id")}, {"_id": 0})
        if p and (u.user_id in (p.get("site_engineers") or []) or
                  any(u.user_id in (s.get("site_engineers") or [])
                      for s in (p.get("sites") or []) if s.get("active", True))):
            return
    raise HTTPException(403, "Not allowed")

@api.get("/mrf/{mrf_id}")
async def get_mrf(mrf_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    d = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "MRF not found")
    await _check_mrf_access(u, d)
    return d

@api.post("/mrf/{mrf_id}/submit")
async def submit_mrf(mrf_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    d = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "MRF not found")
    # Only creator (site engineer/pm) or admin can submit
    if u.role not in ("admin", "director") and d.get("created_by") != u.user_id:
        raise HTTPException(403, "Only the MRF creator (or admin) can submit")
    if d["status"] not in ["draft", "returned"]:
        raise HTTPException(400, "Cannot submit from current status")
    await db.mrfs.update_one(
        {"mrf_id": mrf_id},
        {"$set": {"status": "pm_review", "updated_at": now_utc()}}
    )
    await audit("mrf", mrf_id, "submit", u)
    # Notify PMs of this project (fallback: all PMs)
    proj = await db.projects.find_one({"project_id": d["project_id"]}, {"_id": 0}) or {}
    pm_ids = list(proj.get("project_managers") or [])
    if not pm_ids:
        pms = await db.users.find({"role": "pm"}, {"_id": 0, "user_id": 1}).to_list(50)
        pm_ids = [p["user_id"] for p in pms]
    await notify(pm_ids, "MRF pending review",
                 f"{d['mrf_number']} needs your review", f"/mrf/{mrf_id}")
    return {"ok": True}

@api.post("/mrf/{mrf_id}/approve")
async def approve_mrf(mrf_id: str, body: ApprovalAction, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("pm", "gm", "director", "admin"):
        raise HTTPException(403, "Only PM/GM/Director/admin can authorise")
    d = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "MRF not found")
    if u.role == "pm":
        proj = await db.projects.find_one({"project_id": d["project_id"]}, {"_id": 0})
        if not proj or u.user_id not in (proj.get("project_managers") or []):
            raise HTTPException(403, "You are not the PM for this project")
    # GM and Director have global authorise rights (no project team check)

    if body.action == "return":
        await db.mrfs.update_one(
            {"mrf_id": mrf_id},
            {"$set": {"status": "returned", "pm_comments": body.comment or "",
                      "updated_at": now_utc()}}
        )
        await audit("mrf", mrf_id, "return", u, {"comment": body.comment})
        await notify([d["created_by"]], "MRF returned", f"{d['mrf_number']} returned for correction", f"/mrf/{mrf_id}")
        return {"ok": True, "status": "returned"}

    # apply item-level actions
    items = d["items"]
    if body.item_actions:
        for ia in body.item_actions:
            for it in items:
                if it["item_line_id"] == ia.get("item_line_id"):
                    if ia.get("action") == "reject":
                        it["status"] = "rejected"
                        it["rejection_reason"] = ia.get("reason", "")
                        it["qty_approved"] = 0
                    else:
                        it["status"] = "approved"
                        if ia.get("qty_approved") is not None:
                            it["qty_approved"] = float(ia["qty_approved"])
    else:
        for it in items:
            it["status"] = "approved"

    all_rejected = all(it["status"] == "rejected" for it in items)
    if body.action == "reject" or all_rejected:
        new_status = "rejected"
    else:
        new_status = "approved"

    await db.mrfs.update_one(
        {"mrf_id": mrf_id},
        {"$set": {"items": items, "status": new_status,
                  "pm_comments": body.comment or "", "updated_at": now_utc()}}
    )
    await audit("mrf", mrf_id, body.action, u, {"comment": body.comment, "items": body.item_actions})
    # Notify creator + purchase
    tgt = [d["created_by"]]
    if new_status == "approved":
        purchases = await db.users.find({"role": "purchase"}, {"_id": 0, "user_id": 1}).to_list(50)
        tgt += [p["user_id"] for p in purchases]
    await notify(tgt, f"MRF {new_status}", f"{d['mrf_number']} {new_status}", f"/mrf/{mrf_id}")
    return {"ok": True, "status": new_status}

@api.post("/mrf/{mrf_id}/send-to-purchase")
async def send_to_purchase(mrf_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("pm", "gm", "director", "admin"):
        raise HTTPException(403, "Not allowed")
    d = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not d or d["status"] != "approved":
        raise HTTPException(400, "MRF must be approved first")
    await db.mrfs.update_one({"mrf_id": mrf_id}, {"$set": {"status": "sent_to_purchase", "updated_at": now_utc()}})
    await audit("mrf", mrf_id, "send_to_purchase", u)
    return {"ok": True}

@api.delete("/mrf/{mrf_id}")
async def delete_mrf(mrf_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin can delete")
    await db.mrfs.update_one({"mrf_id": mrf_id}, {"$set": {"deleted": True}})
    await audit("mrf", mrf_id, "soft_delete", u)
    return {"ok": True}

@api.put("/mrf/{mrf_id}/items/{line_id}")
async def update_mrf_line(mrf_id: str, line_id: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    """Edit an MRF line item WITH mandatory reason. Records every field-level change
    (user, timestamp, reason, old value, new value) in mrfs.items[].change_log[]."""
    u = await get_current_user(authorization)
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is required for line-item edits")

    mrf = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    await _check_mrf_access(u, mrf)
    # Only creator OR pm/gm/director/admin can edit lines
    if u.role not in ("pm", "gm", "director", "admin") and mrf.get("created_by") != u.user_id:
        raise HTTPException(403, "Not allowed to edit this MRF")
    # Lock certain states from edits (except admin/director override)
    locked = {"received", "fully_received", "closed", "cancelled", "rejected"}
    if canonical_mrf_status(mrf.get("status")) in locked and u.role not in ("admin", "director"):
        raise HTTPException(400, f"MRF is in status '{mrf.get('status')}' — line edits are locked")

    items = mrf.get("items", [])
    target = next((it for it in items if it.get("item_line_id") == line_id), None)
    if not target:
        raise HTTPException(404, "Line item not found")

    changed: Dict[str, Any] = {}
    editable_fields = ["description", "specification", "part_number", "make", "model",
                       "unit", "qty_requested", "qty_approved", "priority", "remarks",
                       "billing_status", "status"]
    for k in editable_fields:
        if k in body:
            new_v = body[k]
            if k in ("qty_requested", "qty_approved"):
                try: new_v = float(new_v) if new_v is not None else new_v
                except Exception: raise HTTPException(400, f"{k} must be numeric")
            old_v = target.get(k)
            if new_v != old_v:
                changed[k] = {"old": old_v, "new": new_v}
                target[k] = new_v
    if not changed:
        raise HTTPException(400, "No changes provided")

    log_entry = {
        "log_id": gid("chl"),
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "timestamp": now_utc().isoformat(),
        "reason": reason, "changes": changed,
    }
    target.setdefault("change_log", []).append(log_entry)
    await db.mrfs.update_one({"mrf_id": mrf_id},
                             {"$set": {"items": items, "updated_at": now_utc()}})
    # Mirror into master_audit for global searchability
    await master_audit("mrf.item", f"{mrf['mrf_number']}#{line_id}", "update", u,
                       reason,
                       {k: v["old"] for k, v in changed.items()},
                       {k: v["new"] for k, v in changed.items()})
    return {"ok": True, "changes": changed, "log": log_entry}

# ---------------------- Purchase Orders ----------------------
@api.post("/po")
async def create_po(body: POCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only purchase/admin/director can create POs")

    # Validate: no rejected items
    mrf_refs = set()
    total = 0.0
    for it in body.items:
        mrf_refs.add(it.mrf_id)
        mrf = await db.mrfs.find_one({"mrf_id": it.mrf_id}, {"_id": 0})
        if not mrf:
            raise HTTPException(400, f"MRF {it.mrf_id} not found")
        if mrf["status"] not in ["approved", "sent_to_purchase", "partially_ordered"]:
            raise HTTPException(400, f"MRF {mrf['mrf_number']} not in purchasable state")
        for mi in mrf["items"]:
            if mi["item_line_id"] == it.item_line_id:
                if mi["status"] == "rejected":
                    raise HTTPException(400, f"Item {mi['description']} is rejected")
        gross = it.qty * it.rate
        after_disc = gross - it.discount
        gst_amt = after_disc * it.gst / 100
        total += after_disc + gst_amt
    total += body.freight + body.other_charges

    # Threshold-based approval flow
    thresholds = await get_thresholds()
    initial_status = _po_initial_status(total, thresholds["gm"], thresholds["director"])

    # Snapshot customer from project
    proj = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
    cust_id = (proj or {}).get("customer_id")
    cust_name = ""
    if cust_id:
        c = await db.customers.find_one({"customer_id": cust_id}, {"_id": 0, "name": 1})
        cust_name = (c or {}).get("name") or ""
    if not cust_name:
        cust_name = (proj or {}).get("client") or ""

    po = PO(
        po_number=await next_po_number(),
        vendor_id=body.vendor_id,
        project_id=body.project_id,
        delivery_site=body.delivery_site,
        items=body.items,
        delivery_schedule=body.delivery_schedule,
        payment_terms=body.payment_terms,
        warranty_terms=body.warranty_terms,
        freight=body.freight,
        other_charges=body.other_charges,
        authorised_signatory=body.authorised_signatory,
        vendor_quotation=body.vendor_quotation,
        mrf_refs=list(mrf_refs),
        total=round(total, 2),
        customer_id=cust_id,
        customer_name=cust_name,
        created_by=u.user_id,
    )
    po_doc = po.model_dump()
    po_doc["status"] = initial_status
    # items -> as dict
    po_doc["items"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in body.items]
    po_doc["approval_history"] = []
    po_doc["thresholds_applied"] = {"gm": thresholds["gm"], "director": thresholds["director"]}
    await db.pos.insert_one(po_doc)

    # Update MRF item qty_ordered and MRF status ONLY if PO is issued (auto-approved).
    # For pending_gm/director_approval, we hold the MRF status until PO is approved.
    if initial_status == "issued":
        for it in body.items:
            mrf = await db.mrfs.find_one({"mrf_id": it.mrf_id}, {"_id": 0})
            items = mrf["items"]
            for mi in items:
                if mi["item_line_id"] == it.item_line_id:
                    mi["qty_ordered"] = (mi.get("qty_ordered") or 0) + it.qty
            all_ordered = all(
                (mi.get("qty_ordered") or 0) >= (mi.get("qty_approved") or 0)
                for mi in items if mi["status"] != "rejected"
            )
            any_ordered = any((mi.get("qty_ordered") or 0) > 0 for mi in items)
            new_status = "fully_ordered" if all_ordered else ("partially_ordered" if any_ordered else mrf["status"])
            await db.mrfs.update_one({"mrf_id": it.mrf_id},
                                     {"$set": {"items": items, "status": new_status, "updated_at": now_utc()}})

    # Notify approvers if threshold not met
    if initial_status == "pending_gm_approval":
        approvers = await db.users.find({"role": {"$in": ["gm", "director"]}},
                                        {"_id": 0, "user_id": 1}).to_list(50)
        await notify([a["user_id"] for a in approvers], "PO pending GM approval",
                     f"{po.po_number} (₹{total:,.2f}) awaits GM approval", f"/po/{po.po_id}")
    elif initial_status == "pending_director_approval":
        approvers = await db.users.find({"role": "director"},
                                        {"_id": 0, "user_id": 1}).to_list(50)
        await notify([a["user_id"] for a in approvers], "PO pending Director approval",
                     f"{po.po_number} (₹{total:,.2f}) awaits Director approval", f"/po/{po.po_id}")

    await audit("po", po.po_id, "create", u, {"po_number": po.po_number, "total": total,
                                               "initial_status": initial_status})
    po_doc.pop("_id", None)
    return po_doc

@api.post("/po/{po_id}/approve")
async def approve_po(po_id: str, body: Optional[dict] = None,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("gm", "director", "admin"):
        raise HTTPException(403, "Only GM/Director/Admin can approve POs")
    body = body or {}
    action = (body.get("action") or "approve").lower()
    comment = body.get("comment") or ""
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    cur = po.get("status", "issued")
    if cur not in ("pending_gm_approval", "pending_director_approval"):
        raise HTTPException(400, f"PO is not awaiting approval (status={cur})")
    # Director-level POs require director (GM cannot approve those)
    if cur == "pending_director_approval" and u.role == "gm":
        raise HTTPException(403, "This PO exceeds GM threshold — Director approval required")

    if action == "reject":
        new_status = "rejected"
    else:
        new_status = "issued"

    hist_entry = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": comment, "timestamp": now_utc().isoformat(),
    }
    await db.pos.update_one(
        {"po_id": po_id},
        {"$set": {"status": new_status}, "$push": {"approval_history": hist_entry}},
    )

    # If approved, apply MRF qty_ordered updates (deferred from creation)
    if new_status == "issued":
        for it in po.get("items", []):
            mrf = await db.mrfs.find_one({"mrf_id": it.get("mrf_id")}, {"_id": 0})
            if not mrf:
                continue
            items = mrf["items"]
            for mi in items:
                if mi["item_line_id"] == it.get("item_line_id"):
                    mi["qty_ordered"] = (mi.get("qty_ordered") or 0) + float(it.get("qty") or 0)
            all_ordered = all(
                (mi.get("qty_ordered") or 0) >= (mi.get("qty_approved") or 0)
                for mi in items if mi["status"] != "rejected"
            )
            any_ordered = any((mi.get("qty_ordered") or 0) > 0 for mi in items)
            mrf_new = "fully_ordered" if all_ordered else ("partially_ordered" if any_ordered else mrf["status"])
            await db.mrfs.update_one({"mrf_id": mrf["mrf_id"]},
                                     {"$set": {"items": items, "status": mrf_new, "updated_at": now_utc()}})

    await audit("po", po_id, f"po_{action}", u, {"comment": comment, "new_status": new_status})
    # Notify creator
    creator = po.get("created_by")
    if creator:
        await notify([creator], f"PO {new_status}",
                     f"{po['po_number']} was {action}d by {u.name}", f"/po/{po_id}")
    return {"ok": True, "status": new_status}

@api.get("/po")
async def list_pos(project_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    docs = await db.pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    if u.role in ("admin", "purchase", "gm", "director"):
        return docs
    if u.role == "pm":
        prjs = await db.projects.find({"project_managers": u.user_id},
                                      {"_id": 0, "project_id": 1}).to_list(500)
        allowed = {p["project_id"] for p in prjs}
        return [p for p in docs if p.get("project_id") in allowed]
    if u.role == "site_engineer":
        # Only POs whose mrf_refs include an MRF created by this user
        my = await db.mrfs.find({"created_by": u.user_id},
                                {"_id": 0, "mrf_id": 1}).to_list(2000)
        my_ids = {m["mrf_id"] for m in my}
        return [p for p in docs if my_ids.intersection(p.get("mrf_refs") or [])]
    if u.role == "store":
        prjs = await db.projects.find(
            {"$or": [
                {"site_engineers": u.user_id},
                {"sites.site_engineers": u.user_id},
            ]}, {"_id": 0, "project_id": 1}).to_list(500)
        allowed = {p["project_id"] for p in prjs}
        return [p for p in docs if p.get("project_id") in allowed]
    return []

@api.get("/po/{po_id}")
async def get_po(po_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    d = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, d)
    return d

@api.post("/po/{po_id}/received")
async def mark_po_received(po_id: str, body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in GRN_ROLES:
        raise HTTPException(403, "Only site engineer/store/purchase/PM/director/admin can record receipt")
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    if po.get("status") in ("pending_gm_approval", "pending_director_approval", "rejected"):
        raise HTTPException(400, f"PO not yet approved (status={po.get('status')})")
    # Access check for non-admin/purchase
    await _check_po_access(u, po)

    # Body may include: {"items": [{"mrf_id": ..., "item_line_id": ..., "qty": <n>}]}
    # If no per-line qty provided, receive full remaining qty of every PO line.
    per_line = {}
    if body and isinstance(body.get("items"), list):
        for row in body["items"]:
            key = (row.get("mrf_id"), row.get("item_line_id"))
            try:
                per_line[key] = float(row.get("qty") or 0)
            except (TypeError, ValueError):
                per_line[key] = 0

    # Track per-line received qty on the PO itself
    po_items = po["items"]
    any_received = False
    grn_items: List[Dict[str, Any]] = []
    for pit in po_items:
        prev = float(pit.get("qty_received") or 0)
        ordered = float(pit.get("qty") or 0)
        remaining = max(ordered - prev, 0)
        if per_line:
            receive_now = per_line.get((pit["mrf_id"], pit["item_line_id"]), 0)
        else:
            receive_now = remaining
        # Clamp to what's still outstanding on this PO line
        receive_now = max(0.0, min(receive_now, remaining))
        if receive_now <= 0:
            continue
        pit["qty_received"] = prev + receive_now
        pit.setdefault("receipts", []).append({
            "date": now_utc().isoformat(),
            "qty": receive_now,
            "user_id": u.user_id,
            "user_name": u.name,
        })
        any_received = True
        grn_items.append({
            "mrf_id": pit["mrf_id"],
            "item_line_id": pit["item_line_id"],
            "description": pit.get("description", ""),
            "unit": pit.get("unit", ""),
            "qty": receive_now,
        })

        # Roll up to MRF item qty_received
        mrf = await db.mrfs.find_one({"mrf_id": pit["mrf_id"]}, {"_id": 0})
        if not mrf:
            continue
        items = mrf["items"]
        for mi in items:
            if mi["item_line_id"] == pit["item_line_id"]:
                mi["qty_received"] = (mi.get("qty_received") or 0) + receive_now
        all_recv = all(
            (mi.get("qty_received") or 0) >= (mi.get("qty_approved") or 0)
            for mi in items if mi["status"] != "rejected"
        )
        await db.mrfs.update_one(
            {"mrf_id": pit["mrf_id"]},
            {"$set": {"items": items,
                      "status": "received" if all_recv else mrf["status"],
                      "updated_at": now_utc()}}
        )

    # Roll up PO status: fully vs partially received
    fully = all(
        float(pi.get("qty_received") or 0) >= float(pi.get("qty") or 0)
        for pi in po_items
    )
    new_status = "received" if fully else ("partially_received" if any_received else po.get("status", "issued"))
    await db.pos.update_one(
        {"po_id": po_id},
        {"$set": {"items": po_items, "status": new_status}}
    )

    # Create GRN record if any qty was received
    grn_id = None
    grn_number = None
    if grn_items:
        grn_id = gid("grn")
        grn_number = await next_grn_number()
        await db.grns.insert_one({
            "grn_id": grn_id,
            "grn_number": grn_number,
            "po_id": po_id,
            "po_number": po["po_number"],
            "mrf_refs": po.get("mrf_refs", []),
            "vendor_id": po.get("vendor_id"),
            "project_id": po.get("project_id"),
            "date": now_utc(),
            "items": grn_items,
            "received_by": u.user_id,
            "received_by_name": u.name,
            "remarks": (body or {}).get("remarks", ""),
        })

    await audit("po", po_id, "received", u, {"status": new_status, "grn_number": grn_number,
                                              "per_line": grn_items})
    return {"ok": True, "status": new_status, "grn_id": grn_id, "grn_number": grn_number}

# ---------------------- Billing ----------------------
@api.get("/billing/items")
async def billing_items(
    filter: Optional[str] = None,  # not_billed / partially_billed / fully_billed / non_billable
    project_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only purchase/director/admin")
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    mrfs = await db.mrfs.find(q, {"_id": 0}).to_list(500)
    out = []
    for m in mrfs:
        for it in m["items"]:
            if it["status"] == "rejected":
                continue
            bstat = it.get("billing_status", "not_billed")
            if filter and bstat != filter:
                continue
            out.append({
                "mrf_id": m["mrf_id"], "mrf_number": m["mrf_number"],
                "project_id": m["project_id"], "site": m["site"],
                "item_line_id": it["item_line_id"], "description": it["description"],
                "unit": it["unit"], "qty_approved": it.get("qty_approved") or 0,
                "qty_received": it.get("qty_received") or 0,
                "qty_issued": it.get("qty_issued") or 0,
                "qty_billed": it.get("qty_billed") or 0,
                "billing_status": bstat, "billable": it.get("billable", True),
                "client_bill_ref": it.get("client_bill_ref", ""),
                "ra_bill_no": it.get("ra_bill_no", ""),
                "billing_date": it.get("billing_date", ""),
            })
    return out

@api.post("/billing/update")
async def update_billing(body: BillingUpdate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only billing/admin")
    mrf = await db.mrfs.find_one({"mrf_id": body.mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    items = mrf["items"]
    for it in items:
        if it["item_line_id"] == body.item_line_id:
            if body.qty_received is not None:
                it["qty_received"] = body.qty_received
            if body.qty_issued is not None:
                it["qty_issued"] = body.qty_issued
            if body.qty_billed is not None:
                it["qty_billed"] = body.qty_billed
            if body.client_bill_ref is not None:
                it["client_bill_ref"] = body.client_bill_ref
            if body.ra_bill_no is not None:
                it["ra_bill_no"] = body.ra_bill_no
            if body.billing_date is not None:
                it["billing_date"] = body.billing_date
            if body.billing_remarks is not None:
                it["billing_remarks"] = body.billing_remarks
            # Auto-compute billing status
            new_bstat = it.get("billing_status", "not_billed")
            if body.billing_status:
                if body.billing_status == "fully_billed":
                    qa = it.get("qty_approved") or 0
                    qr = it.get("qty_received") or qa
                    qb = it.get("qty_billed") or 0
                    if qb < qr and not body.override_reason:
                        raise HTTPException(400, "Cannot mark fully billed: billed < received. Provide override_reason.")
                new_bstat = body.billing_status
            else:
                qa = it.get("qty_approved") or 0
                qb = it.get("qty_billed") or 0
                if not it.get("billable", True):
                    new_bstat = "non_billable"
                elif qb <= 0:
                    new_bstat = "not_billed"
                elif qb >= qa:
                    new_bstat = "fully_billed"
                else:
                    new_bstat = "partially_billed"
            it["billing_status"] = new_bstat
    await db.mrfs.update_one({"mrf_id": body.mrf_id}, {"$set": {"items": items, "updated_at": now_utc()}})
    await audit("billing", body.item_line_id, "update", u, body.model_dump(exclude_none=True))
    return {"ok": True}

# ---------------------- Notifications ----------------------
@api.get("/notifications")
async def list_notifications(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    docs = await db.notifications.find({"user_id": u.user_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return docs

@api.post("/notifications/{nid}/read")
async def read_notif(nid: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    await db.notifications.update_one({"notification_id": nid, "user_id": u.user_id}, {"$set": {"read": True}})
    return {"ok": True}

# ---------------------- Reports / Dashboards ----------------------
@api.get("/reports/dashboard")
async def dashboard(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    mrfs = await db.mrfs.find({"deleted": False}, {"_id": 0}).to_list(1000)
    pos = await db.pos.find({"deleted": False}, {"_id": 0}).to_list(1000)
    total_mrf = len(mrfs)
    pending_pm = sum(1 for m in mrfs if m["status"] in ["pm_review", "submitted"])
    pending_purchase = sum(1 for m in mrfs if m["status"] in ["approved", "sent_to_purchase", "partially_ordered"])
    approved = sum(1 for m in mrfs if m["status"] == "approved")
    total_po = len(pos)
    po_value = sum(p.get("total", 0) for p in pos)

    # billable vs non-billable
    billable_value = 0
    non_billable_value = 0
    pending_billing_count = 0
    fully_billed_count = 0
    for m in mrfs:
        for it in m["items"]:
            if it.get("billable", True):
                billable_value += (it.get("qty_approved") or 0)
                if it.get("billing_status") in ["not_billed", "partially_billed"]:
                    pending_billing_count += 1
                if it.get("billing_status") == "fully_billed":
                    fully_billed_count += 1
            else:
                non_billable_value += (it.get("qty_approved") or 0)

    # ageing: draft/submitted older than 3 days
    now = now_utc()
    ageing_buckets = {"0-3": 0, "4-7": 0, "8-15": 0, "16+": 0}
    for m in mrfs:
        if m["status"] in ["approved", "closed", "received", "fully_ordered"]:
            continue
        created = m["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = (now - created).days
        if days <= 3:
            ageing_buckets["0-3"] += 1
        elif days <= 7:
            ageing_buckets["4-7"] += 1
        elif days <= 15:
            ageing_buckets["8-15"] += 1
        else:
            ageing_buckets["16+"] += 1

    return {
        "total_mrf": total_mrf,
        "pending_pm": pending_pm,
        "pending_purchase": pending_purchase,
        "approved": approved,
        "total_po": total_po,
        "po_value": round(po_value, 2),
        "billable_value": billable_value,
        "non_billable_value": non_billable_value,
        "pending_billing_count": pending_billing_count,
        "fully_billed_count": fully_billed_count,
        "ageing": ageing_buckets,
    }

@api.get("/reports/mrf-ageing")
async def mrf_ageing(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    mrfs = await db.mrfs.find({"deleted": False}, {"_id": 0}).to_list(1000)
    now = now_utc()
    out = []
    for m in mrfs:
        if m["status"] in ["closed", "received"]:
            continue
        created = m["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = (now - created).days
        out.append({"mrf_id": m["mrf_id"], "mrf_number": m["mrf_number"],
                    "status": m["status"], "days": days,
                    "project_id": m["project_id"], "site": m["site"]})
    out.sort(key=lambda x: -x["days"])
    return out

@api.get("/audit")
async def audit_logs(entity_id: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin can view audit trail")
    q = {}
    if entity_id:
        q["entity_id"] = entity_id
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).limit(200).to_list(200)
    return logs

# ---------------------- Settings: Purchase Thresholds ----------------------
@api.get("/settings/thresholds")
async def get_settings_thresholds(authorization: Optional[str] = Header(None)):
    """Any authenticated user can read thresholds (UI needs it to show approval hints)."""
    await get_current_user(authorization)
    return await get_thresholds()

@api.put("/settings/thresholds")
async def update_settings_thresholds(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("director", "admin"):
        raise HTTPException(403, "Only Director/Admin can change purchase thresholds")
    gm = body.get("gm")
    dr = body.get("director")
    if gm is None or dr is None:
        raise HTTPException(400, "Both 'gm' and 'director' threshold values required")
    try:
        gm = float(gm); dr = float(dr)
    except Exception:
        raise HTTPException(400, "Thresholds must be numeric")
    if gm < 0 or dr < 0:
        raise HTTPException(400, "Thresholds must be non-negative")
    if dr < gm:
        raise HTTPException(400, "Director threshold must be >= GM threshold")
    await db.settings.update_one(
        {"_id": "thresholds"},
        {"$set": {"gm": gm, "director": dr, "updated_by": u.user_id, "updated_at": now_utc()}},
        upsert=True,
    )
    await audit("settings", "thresholds", "update", u, {"gm": gm, "director": dr})
    return {"gm": gm, "director": dr}

# ---------------------- PDF ----------------------
# ---------------------- Branded PDF helpers ----------------------
VASU_PRIMARY = colors.HexColor('#002FA7')  # Vasu brand blue
VASU_ACCENT = colors.HexColor('#F7941D')   # Vasu orange
VASU_TAGLINE = "Enterprise Fire Safety · CCTV · Access Control · Structured Cabling"
VASU_ADDR = "Vasu Infosec Pvt Ltd  ·  Pune · Delhi  ·  vasuinfosec.com"
VASU_GSTIN = ""  # populated at runtime from env if provided

def _vasu_footer(canvas, doc):
    """Draws Vasu footer + page number on every page."""
    canvas.saveState()
    w, _ = A4
    canvas.setStrokeColor(VASU_PRIMARY)
    canvas.setLineWidth(0.6)
    canvas.line(15*mm, 12*mm, w - 15*mm, 12*mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15*mm, 7*mm, VASU_ADDR)
    canvas.drawRightString(w - 15*mm, 7*mm, f"Page {doc.page}")
    canvas.restoreState()

def _pdf_story(doc_type: str, doc_number: str, doc_date, project: dict,
               customer: Optional[dict], vendor: Optional[dict] = None,
               extra_ref: str = "") -> List:
    """Build a common branded header (VASU banner + Customer + Vendor + Project block)."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=20,
                                 textColor=VASU_PRIMARY, alignment=0, spaceAfter=2)
    tag_style = ParagraphStyle('tg', parent=styles['Normal'], fontSize=8,
                               textColor=colors.HexColor('#555'), spaceAfter=8)
    doc_title_style = ParagraphStyle('dt', parent=styles['Heading1'], fontSize=14,
                                     alignment=1, textColor=colors.HexColor('#111'),
                                     backColor=colors.HexColor('#EEF2FF'),
                                     borderPadding=6, spaceAfter=8)
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9, leading=12)

    story: List = []
    # Header row: brand banner
    story.append(Paragraph("VASU INFOSEC", title_style))
    story.append(Paragraph(VASU_TAGLINE, tag_style))

    # Document title band
    story.append(Paragraph(doc_type, doc_title_style))

    # Meta table: doc no + date + refs
    date_str = doc_date.strftime('%d-%b-%Y') if hasattr(doc_date, 'strftime') else str(doc_date)[:10]
    meta_rows = [
        [Paragraph(f"<b>{doc_type.split()[-1]} No.</b>", small), Paragraph(doc_number, small),
         Paragraph("<b>Date</b>", small), Paragraph(date_str, small)],
    ]
    if extra_ref:
        meta_rows.append([Paragraph("<b>References</b>", small),
                          Paragraph(extra_ref, small), "", ""])
    meta_tbl = Table(meta_rows, colWidths=[70, 200, 40, 100])
    meta_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor('#D5D8DE')),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor('#F2F5FF')),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor('#F2F5FF')),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 6))

    # Customer + Project + Vendor combined info block
    cust_lines = []
    if customer:
        cust_lines.append(f"<b>Customer ID:</b> {customer.get('customer_id','')}")
        cust_lines.append(f"<b>Customer:</b> {customer.get('name','')}")
        if customer.get('gstin'): cust_lines.append(f"GSTIN: {customer['gstin']}")
        if customer.get('billing_address'): cust_lines.append(customer['billing_address'])
        if customer.get('contact_person'): cust_lines.append(f"Contact: {customer['contact_person']} · {customer.get('phone','')}")
    else:
        cust_lines.append(f"<b>Client:</b> {project.get('client','—')}")

    proj_lines = [
        f"<b>Project:</b> {project.get('name','')} ({project.get('code','')})",
        f"<b>Site:</b> {project.get('site','')}",
    ]
    if project.get('system_categories'):
        proj_lines.append(f"Systems: {', '.join(project['system_categories'])}")

    party_rows = [[Paragraph("BILL TO / CUSTOMER", small),
                   Paragraph("PROJECT DETAILS", small)],
                  [Paragraph("<br/>".join(cust_lines), small),
                   Paragraph("<br/>".join(proj_lines), small)]]
    party = Table(party_rows, colWidths=[210, 210])
    party.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor('#D5D8DE')),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]))
    story.append(party)
    story.append(Spacer(1, 8))

    if vendor:
        vend_txt = (f"<b>Vendor:</b> {vendor.get('name','')} "
                    f"({vendor.get('gstin','')})<br/>"
                    f"{vendor.get('address','')} · Contact: {vendor.get('contact','')}")
        story.append(Paragraph(vend_txt, small))
        story.append(Spacer(1, 6))

    return story

@api.get("/po/{po_id}/pdf")
async def po_pdf(po_id: str, token: Optional[str] = None,
                 authorization: Optional[str] = Header(None)):
    # Allow token via query for browser download
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, po)
    vendor = await db.vendors.find_one({"vendor_id": po["vendor_id"]}, {"_id": 0}) or {}
    project = await db.projects.find_one({"project_id": po["project_id"]}, {"_id": 0}) or {}
    po_mrf_nums = []
    for mid in po.get("mrf_refs") or []:
        m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "mrf_number": 1})
        if m: po_mrf_nums.append(m["mrf_number"])

    # Customer snapshot (fall back to project's customer)
    cid = po.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    story = _pdf_story("PURCHASE ORDER", po["po_number"], po["date"], project, cust, vendor, extra_ref=", ".join(po_mrf_nums))

    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)

    data = [["#", "Description", "Unit", "Qty", "Rate", "Disc", "GST%", "Total"]]
    for idx, it in enumerate(po["items"], 1):
        gross = it["qty"] * it["rate"]
        after_disc = gross - (it.get("discount") or 0)
        gst_amt = after_disc * (it.get("gst") or 0) / 100
        total = after_disc + gst_amt
        data.append([str(idx), it["description"][:40], it["unit"], f"{it['qty']}", f"{it['rate']}",
                     f"{it.get('discount', 0)}", f"{it.get('gst', 0)}", f"{total:.2f}"])
    tbl = Table(data, colWidths=[20, 180, 40, 40, 50, 40, 40, 60])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#002FA7')),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Freight:</b> ₹{po.get('freight',0):,.2f}  <b>Other:</b> ₹{po.get('other_charges',0):,.2f}  <b>Grand Total:</b> ₹{po.get('total',0):,.2f}", small))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Delivery:</b> {po.get('delivery_schedule','')}", small))
    story.append(Paragraph(f"<b>Payment:</b> {po.get('payment_terms','')}", small))
    story.append(Paragraph(f"<b>Warranty:</b> {po.get('warranty_terms','')}", small))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"<b>Authorised Signatory:</b> {po.get('authorised_signatory','')}", small))
    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{po["po_number"].replace("/","_")}.pdf"'})

# ---------------------- Excel ----------------------
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB

def _safe_cell(v: Any) -> Any:
    """Neutralize spreadsheet formula-injection payloads."""
    if isinstance(v, str) and v and v[0] in ("=", "+", "-", "@"):
        return "'" + v
    return v

def _excel_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@api.get("/export/mrf")
async def export_mrf(token: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "pm"):
        raise HTTPException(403, "Not allowed")
    mrfs = await db.mrfs.find({"deleted": False}, {"_id": 0}).to_list(1000)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MRFs"
    headers = ["MRF#", "Date", "Customer ID", "Customer Name", "Project", "Site", "Requester", "System", "Status", "Item", "Qty", "Approved", "Billing"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    # Preload project code / customer name lookup
    for m in mrfs:
        for it in m["items"]:
            ws.append([_safe_cell(m["mrf_number"]),
                       m["date"].strftime("%Y-%m-%d") if isinstance(m["date"], datetime) else str(m["date"]),
                       _safe_cell(m.get("customer_id") or ""),
                       _safe_cell(m.get("customer_name") or ""),
                       _safe_cell(m["project_id"]), _safe_cell(m["site"]),
                       _safe_cell(m["requesting_person"]), _safe_cell(m["system_category"]),
                       _safe_cell(m["status"]), _safe_cell(it["description"]),
                       it["qty_requested"], it.get("qty_approved") or 0,
                       _safe_cell(it.get("billing_status", ""))])
    return _excel_response(wb, "mrf_export.xlsx")

@api.get("/export/po")
async def export_po(token: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Not allowed")
    pos = await db.pos.find({"deleted": False}, {"_id": 0}).to_list(1000)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "POs"
    ws.append(["PO#", "Date", "Customer ID", "Customer Name", "Vendor", "Project", "MRF Refs", "Total", "Status"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    for p in pos:
        ws.append([_safe_cell(p["po_number"]),
                   p["date"].strftime("%Y-%m-%d") if isinstance(p["date"], datetime) else str(p["date"]),
                   _safe_cell(p.get("customer_id") or ""),
                   _safe_cell(p.get("customer_name") or ""),
                   _safe_cell(p.get("vendor_id", "")), _safe_cell(p.get("project_id", "")),
                   _safe_cell(", ".join(p.get("mrf_refs", []))),
                   p.get("total", 0), _safe_cell(p.get("status", ""))])
    return _excel_response(wb, "po_export.xlsx")

# ---------------------- Tally-compatible Excel Voucher Export ----------------------
@api.get("/export/tally")
async def export_tally(kind: str = "purchase", token: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    """Emit Tally-compatible Excel voucher rows.

    - kind=purchase → one row per PO line item (Purchase voucher).
    - kind=invoice  → one row per vendor invoice line item (Purchase voucher, matches invoice).
    Column layout follows Tally's standard "Purchase" template so users can import via
    XML import / Excel-to-Tally utilities.
    """
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/director/admin")
    kind = (kind or "purchase").lower()
    if kind not in ("purchase", "invoice"):
        raise HTTPException(400, "kind must be 'purchase' or 'invoice'")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Voucher"
    headers = [
        "Voucher Date", "Voucher Type", "Voucher No", "Reference No", "Reference Date",
        "Party Ledger", "Party GSTIN", "Party State",
        "Customer ID", "Customer Name",
        "Item Name", "HSN/SAC", "Unit", "Quantity", "Rate", "Discount",
        "Taxable Value", "GST Rate %", "CGST", "SGST", "IGST",
        "Line Total", "Narration",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center")

    # Preload vendors
    vendors = {v["vendor_id"]: v for v in await db.vendors.find({}, {"_id": 0}).to_list(1000)}

    def _split_gst(taxable: float, gst_pct: float, party_state: str) -> tuple:
        """Approximate CGST/SGST vs IGST split (assumes intra-state if state == 'MH')."""
        gst_amt = taxable * gst_pct / 100
        # Simplified: if party state contains 'MH' or 'Maharashtra' → intra-state
        intra = ("MH" in (party_state or "").upper()) or ("MAHARASHTRA" in (party_state or "").upper())
        if intra:
            return (round(gst_amt / 2, 2), round(gst_amt / 2, 2), 0.0)
        return (0.0, 0.0, round(gst_amt, 2))

    def _row(voucher_type: str, vdate: str, vno: str, ref_no: str, ref_date: str,
             vend: dict, cust_id: str, cust_name: str, item: dict, narration: str):
        gst_pct = float(item.get("gst") or 0)
        qty = float(item.get("qty") or 0)
        rate = float(item.get("rate") or 0)
        disc = float(item.get("discount") or 0)
        taxable = qty * rate - disc
        cgst, sgst, igst = _split_gst(taxable, gst_pct, (vend or {}).get("address", ""))
        line_total = round(taxable + cgst + sgst + igst, 2)
        ws.append([
            _safe_cell(vdate), _safe_cell(voucher_type), _safe_cell(vno),
            _safe_cell(ref_no), _safe_cell(ref_date),
            _safe_cell((vend or {}).get("name", "")),
            _safe_cell((vend or {}).get("gstin", "")),
            _safe_cell((vend or {}).get("address", "")[:20]),
            _safe_cell(cust_id or ""), _safe_cell(cust_name or ""),
            _safe_cell(item.get("description", "")),
            _safe_cell(item.get("hsn_code", "") or ""),
            _safe_cell(item.get("unit", "")),
            qty, rate, disc,
            round(taxable, 2), gst_pct, cgst, sgst, igst,
            line_total, _safe_cell(narration),
        ])

    if kind == "purchase":
        pos = await db.pos.find({"deleted": False}, {"_id": 0}).sort("date", 1).to_list(2000)
        for p in pos:
            vend = vendors.get(p.get("vendor_id"))
            vdate = p["date"].strftime("%d-%m-%Y") if isinstance(p.get("date"), datetime) else str(p.get("date"))[:10]
            for it in p.get("items", []):
                narration = f"PO {p['po_number']} · MRF {', '.join(p.get('mrf_refs') or [])[:60]}"
                _row("Purchase", vdate, p["po_number"], "", "", vend,
                     p.get("customer_id"), p.get("customer_name"), it, narration)
    else:  # invoice
        invs = await db.invoices.find({}, {"_id": 0}).sort("created_at", 1).to_list(2000)
        for inv in invs:
            vend = vendors.get(inv.get("vendor_id"))
            vdate = str(inv.get("invoice_date", ""))[:10]
            for it in inv.get("items", []):
                narration = f"Vendor Inv {inv.get('vendor_invoice_number','')} · PO {inv.get('po_number','')}"
                _row("Purchase", vdate, inv["invoice_number"],
                     inv.get("vendor_invoice_number", ""), vdate,
                     vend, inv.get("customer_id"), inv.get("customer_name"), it, narration)

    # Auto-width columns
    for col_idx, header in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, len(header) + 2)

    return _excel_response(wb, f"tally_{kind}_voucher.xlsx")

# ---------------------- GRN ----------------------
@api.get("/po/{po_id}/grns")
async def list_grns_for_po(po_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, po)
    grns = await db.grns.find({"po_id": po_id}, {"_id": 0}).sort("date", -1).to_list(200)
    return grns

@api.get("/grns")
async def list_all_grns(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "gm", "director", "admin", "pm"):
        raise HTTPException(403, "Only purchase/pm/gm/director/admin")
    return await db.grns.find({}, {"_id": 0}).sort("date", -1).to_list(500)

@api.get("/grn/{grn_id}/pdf")
async def grn_pdf(grn_id: str, token: Optional[str] = None,
                  authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    grn = await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})
    if not grn:
        raise HTTPException(404, "GRN not found")
    po = await db.pos.find_one({"po_id": grn.get("po_id")}, {"_id": 0})
    if po:
        await _check_po_access(u, po)
    elif u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Not allowed")
    vendor = await db.vendors.find_one({"vendor_id": grn.get("vendor_id")}, {"_id": 0}) or {}
    project = await db.projects.find_one({"project_id": grn.get("project_id")}, {"_id": 0}) or {}
    grn_mrf_nums = []
    for mid in grn.get("mrf_refs") or []:
        m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "mrf_number": 1})
        if m: grn_mrf_nums.append(m["mrf_number"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)

    # Resolve customer from PO snapshot / project
    cid = (po or {}).get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    story = _pdf_story("GOODS RECEIVED NOTE", grn["grn_number"],
                       grn.get("date"), project, cust, vendor,
                       extra_ref=f"PO {grn.get('po_number','')}  ·  MRF {', '.join(grn_mrf_nums)}")

    story.append(Paragraph(f"<b>Received by:</b> {grn.get('received_by_name','')}", small))
    story.append(Spacer(1, 6))

    data = [["#", "Description", "Unit", "Qty Received"]]
    for idx, it in enumerate(grn.get("items", []), 1):
        data.append([str(idx), (it.get("description") or "")[:60], it.get("unit", ""), str(it.get("qty", ""))])
    tbl = Table(data, colWidths=[25, 320, 60, 80])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    if grn.get("remarks"):
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Remarks:</b> {grn['remarks']}", small))
    story += [
        Spacer(1, 40),
        Paragraph("_______________________________&nbsp;&nbsp;&nbsp;&nbsp;_______________________________", small),
        Paragraph("Received By&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Vendor Signature", small),
    ]
    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{grn["grn_number"].replace("/","_")}.pdf"'})

# ---------------------- Excel Bulk Import ----------------------
@api.get("/import/vendors/template")
async def vendor_template(token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    await get_current_user(auth)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Vendors"
    cols = ["name", "address", "gstin", "contact", "email"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    ws.append(["Sample Vendor Pvt Ltd", "Bangalore", "29AAACS0000A1Z5", "9800000000", "sales@sample.com"])
    return _excel_response(wb, "vendor_template.xlsx")

@api.get("/import/mrf/template")
async def mrf_template(token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    await get_current_user(auth)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "MRF"
    cols = ["project_code", "site", "required_by", "requesting_person", "system_category",
            "description", "specification", "part_number", "unit", "qty_requested",
            "purpose", "drawing_ref", "billable", "boq_ref", "remarks"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    ws.append(["VIS-101", "Bangalore Whitefield", "2026-05-15", "Ravi Kumar", "Fire Alarm",
               "Smoke Detector Photoelectric", "Honeywell 5251E", "5251E", "Nos", 25,
               "Level 1 Common Area", "FA-DWG-01", "Y", "BOQ-05", "Urgent"])
    return _excel_response(wb, "mrf_template.xlsx")

@api.post("/import/vendors")
async def import_vendors(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin" and u.role != "purchase":
        raise HTTPException(403, "Only admin/purchase")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)")
    fname = (file.filename or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xlsm")):
        raise HTTPException(400, "Only .xlsx / .xlsm allowed")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:
        raise HTTPException(400, f"Invalid xlsx: {e}")
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise HTTPException(400, "Empty sheet")
    header = [str(c or "").strip().lower() for c in rows[0]]
    inserted, skipped, errors = 0, 0, []
    for idx, row in enumerate(rows[1:], start=2):
        rec = {header[i]: (row[i] if i < len(row) else None) for i in range(len(header))}
        name = (rec.get("name") or "").strip() if rec.get("name") else ""
        if not name:
            skipped += 1; continue
        existing = await db.vendors.find_one({"name": name}, {"_id": 0})
        if existing:
            skipped += 1; continue
        try:
            v = {
                "vendor_id": gid("vnd"), "name": name,
                "address": str(rec.get("address") or ""),
                "gstin": str(rec.get("gstin") or ""),
                "contact": str(rec.get("contact") or ""),
                "email": str(rec.get("email") or ""),
                "active": True,
            }
            await db.vendors.insert_one(v)
            inserted += 1
            await audit("vendor", v["vendor_id"], "import", u, {"name": name})
        except Exception as e:
            errors.append(f"row {idx}: {e}")
    return {"inserted": inserted, "skipped": skipped, "errors": errors}

@api.post("/import/mrf")
async def import_mrf(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "site_engineer", "pm", "director"):
        raise HTTPException(403, "Only admin/site engineer/project manager can import MRFs")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)")
    fname = (file.filename or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xlsm")):
        raise HTTPException(400, "Only .xlsx / .xlsm allowed")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:
        raise HTTPException(400, f"Invalid xlsx: {e}")
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise HTTPException(400, "Empty sheet")
    header = [str(c or "").strip().lower() for c in rows[0]]

    # Group by (project_code, site, required_by, requesting_person, system_category)
    projects = {p["code"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    errors: List[str] = []
    for idx, row in enumerate(rows[1:], start=2):
        rec = {header[i]: (row[i] if i < len(row) else None) for i in range(len(header))}
        code = str(rec.get("project_code") or "").strip()
        if not code or code not in projects:
            errors.append(f"row {idx}: unknown project_code '{code}'")
            continue
        if not rec.get("description"):
            errors.append(f"row {idx}: description required")
            continue
        key = (code, str(rec.get("site") or ""), str(rec.get("required_by") or ""),
               str(rec.get("requesting_person") or ""), str(rec.get("system_category") or "Other"))
        item = {
            "description": str(rec.get("description")),
            "specification": str(rec.get("specification") or ""),
            "part_number": str(rec.get("part_number") or ""),
            "unit": str(rec.get("unit") or "Nos"),
            "qty_requested": float(rec.get("qty_requested") or 0),
            "purpose": str(rec.get("purpose") or ""),
            "drawing_ref": str(rec.get("drawing_ref") or ""),
            "billable": str(rec.get("billable") or "Y").strip().upper() != "N",
            "boq_ref": str(rec.get("boq_ref") or ""),
            "remarks": str(rec.get("remarks") or ""),
        }
        groups.setdefault(key, []).append(item)

    created: List[str] = []
    for key, items in groups.items():
        code, site, required_by, requester, syscat = key
        proj = projects[code]
        mrf_items = []
        for it in items:
            d = dict(it)
            d["qty_approved"] = d["qty_requested"]
            mrf_items.append(MRFItem(**d))
        mrf = MRF(
            mrf_number=await next_mrf_number(),
            project_id=proj["project_id"],
            site=site or proj.get("site", ""),
            required_by=required_by,
            requesting_person=requester,
            system_category=syscat,
            items=mrf_items,
            attachments=[],
            remarks="Imported from Excel",
            status="draft",
            created_by=u.user_id,
        )
        await db.mrfs.insert_one(mrf.model_dump())
        await audit("mrf", mrf.mrf_id, "import", u, {"mrf_number": mrf.mrf_number, "items": len(mrf_items)})
        created.append(mrf.mrf_number)

    return {"created": created, "errors": errors, "count": len(created)}

# ---------------------- Invoice ----------------------
class InvoiceItemIn(BaseModel):
    mrf_id: Optional[str] = ""
    item_line_id: Optional[str] = ""
    description: str
    unit: str = "Nos"
    qty: float
    rate: float
    discount: float = 0
    gst: float = 18

class InvoiceCreate(BaseModel):
    po_id: str
    vendor_invoice_number: Optional[str] = ""
    invoice_date: Optional[str] = ""
    items: List[InvoiceItemIn]
    freight: float = 0
    other_charges: float = 0
    remarks: Optional[str] = ""

@api.post("/invoice")
async def create_invoice(body: InvoiceCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ["purchase", "director", "admin"]:
        raise HTTPException(403, "Only purchase/billing/admin")
    po = await db.pos.find_one({"po_id": body.po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")

    # Validate that item_line_ids exist on this PO and per-line qty is not over-invoiced
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
            max_qty = max(0.0, float(po_line.get("qty") or 0) - already_invoiced.get(it.item_line_id, 0))
            if it.qty > max_qty + 1e-6:
                raise HTTPException(400,
                    f"Qty {it.qty} exceeds remaining invoiceable qty {max_qty} for '{po_line.get('description','')}'")
        gross = it.qty * it.rate
        after_disc = gross - it.discount
        gst_amt = after_disc * it.gst / 100
        subtotal += after_disc
        gst_total += gst_amt
        items.append({**it.model_dump(), "line_total": round(after_disc + gst_amt, 2)})
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
    q = {}
    if po_id:
        q["po_id"] = po_id
    docs = await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

@api.get("/invoice/{inv_id}")
async def get_invoice(inv_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    d = await db.invoices.find_one({"invoice_id": inv_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Invoice not found")
    return d

@api.get("/po/{po_id}/invoices")
async def list_po_invoices(po_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
    return await db.invoices.find({"po_id": po_id}, {"_id": 0}).sort("created_at", -1).to_list(200)

@api.get("/invoice/{inv_id}/pdf")
async def invoice_pdf(inv_id: str, token: Optional[str] = None,
                      authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
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
        if m: mrf_nums.append(m["mrf_number"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)

    cid = inv.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    story = _pdf_story("VENDOR INVOICE", inv["invoice_number"],
                       inv["invoice_date"], project, cust, vendor,
                       extra_ref=f"Vendor Ref: {inv.get('vendor_invoice_number') or '—'}  ·  PO: {inv['po_number']}  ·  MRF: {', '.join(mrf_nums) or '—'}")

    data = [["#", "Description", "Unit", "Qty", "Rate", "Disc", "GST%", "Total"]]
    for idx, it in enumerate(inv["items"], 1):
        data.append([str(idx), (it["description"] or "")[:40], it.get("unit", ""),
                     str(it["qty"]), f"{it['rate']}", f"{it.get('discount', 0)}",
                     f"{it.get('gst', 0)}", f"{it.get('line_total', 0):.2f}"])
    tbl = Table(data, colWidths=[20, 180, 40, 40, 50, 40, 40, 60])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Subtotal:</b> ₹{inv['subtotal']:,.2f}  <b>GST:</b> ₹{inv['gst_total']:,.2f}  "
        f"<b>Freight:</b> ₹{inv.get('freight', 0):,.2f}  <b>Other:</b> ₹{inv.get('other_charges', 0):,.2f}  "
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
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{inv["invoice_number"].replace("/","_")}.pdf"'})

# ---------------------- GRN vs PO Variance Report ----------------------
@api.get("/reports/grn-variance")
async def grn_variance(
    project_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    if vendor_id:
        q["vendor_id"] = vendor_id
    pos = await db.pos.find(q, {"_id": 0}).to_list(1000)
    # Preload invoice totals per PO
    inv_totals: Dict[str, float] = {}
    inv_docs = await db.invoices.find({}, {"_id": 0}).to_list(2000)
    for iv in inv_docs:
        inv_totals[iv["po_id"]] = inv_totals.get(iv["po_id"], 0) + float(iv.get("total") or 0)
    out = []
    for p in pos:
        po_val_ord = 0.0
        po_val_recv = 0.0
        short_lines = 0
        line_count = len(p.get("items", []))
        for it in p.get("items", []):
            qty = float(it.get("qty") or 0)
            recv = float(it.get("qty_received") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst = float(it.get("gst") or 0)
            ord_val = qty * rate - disc
            ord_val = ord_val + ord_val * gst / 100
            recv_val = 0.0
            if qty > 0:
                recv_val = ord_val * (recv / qty)
            po_val_ord += ord_val
            po_val_recv += recv_val
            if recv < qty:
                short_lines += 1
        po_val_ord += float(p.get("freight") or 0) + float(p.get("other_charges") or 0)
        po_val_recv += float(p.get("freight") or 0) + float(p.get("other_charges") or 0) if p.get("status") == "received" else 0
        inv_total = inv_totals.get(p["po_id"], 0)
        variance = round(po_val_ord - po_val_recv, 2)
        invoice_variance = round(inv_total - po_val_recv, 2)
        out.append({
            "po_id": p["po_id"],
            "po_number": p["po_number"],
            "date": p["date"].strftime("%Y-%m-%d") if isinstance(p["date"], datetime) else str(p["date"]),
            "vendor_id": p.get("vendor_id"),
            "project_id": p.get("project_id"),
            "status": p.get("status", "issued"),
            "line_count": line_count,
            "short_lines": short_lines,
            "value_ordered": round(po_val_ord, 2),
            "value_received": round(po_val_recv, 2),
            "variance": variance,
            "invoice_total": round(inv_total, 2),
            "invoice_variance": invoice_variance,
        })
    out.sort(key=lambda r: (-abs(r["variance"]), r["po_number"]))
    return out

# ---------------------- Seed ----------------------
@api.post("/seed")
async def seed_data(authorization: Optional[str] = Header(None)):
    """Idempotent seed of demo data. Requires admin, or dev-mode when no users exist yet."""
    user_count = await db.users.count_documents({})
    if user_count > 0:
        # Bootstrap complete — only admin may reseed
        u = await get_current_user(authorization)
        if u.role != "admin":
            raise HTTPException(403, "Only admin can seed once users exist")
    # (Otherwise: no users yet, allow unauthenticated bootstrap.)
    # Users — legacy demo (dev/QA) + real Vasu Infosec roster
    demo_users = [
        # Legacy demo users (kept for dev-login & smoke tests)
        {"email": "director@vasu.dev", "name": "Vishal (Director demo)", "role": "director"},
        {"email": "pm@vasu.dev", "name": "Priya (PM demo)", "role": "pm"},
        {"email": "gm@vasu.dev", "name": "Girish (GM demo)", "role": "gm"},
        {"email": "purchase@vasu.dev", "name": "Kumar (Purchase demo)", "role": "purchase"},
        {"email": "admin@vasu.dev", "name": "Master Admin", "role": "admin"},
        {"email": "siteeng@vasu.dev", "name": "Sanjay (Site Engineer demo)", "role": "site_engineer"},
        # Real Vasu Infosec roster (Google-sign-in enabled). Roles pre-assigned.
        {"email": "vivek@vasuinfosec.com", "name": "Vivek (Director)", "role": "director"},
        {"email": "balkrishna@vasuinfosec.com", "name": "Balkrishna (GM)", "role": "gm"},
        {"email": "saket.iyer@vasuinfosec.com", "name": "Saket Iyer (PM · Pune)", "role": "pm"},
        {"email": "himanshu@vasuinfosec.com", "name": "Himanshu (PM · Delhi)", "role": "pm"},
        {"email": "wasim@vasuinfosec.com", "name": "Wasim (Purchase · Pune)", "role": "purchase"},
        {"email": "sanjeev@vasuinfosec.com", "name": "Sanjeev (Purchase · Delhi)", "role": "purchase"},
        {"email": "pundlik@vasuinfosec.com", "name": "Pundlik (Admin)", "role": "admin"},
        {"email": "chand@vasuinfosec.com", "name": "Chand (Site Engineer)", "role": "site_engineer"},
        {"email": "saurabh@vasuinfosec.com", "name": "Saurabh (Site Engineer)", "role": "site_engineer"},
        {"email": "abhishek.yadav@vasuinfosec.com", "name": "Abhishek Yadav (Site Engineer)", "role": "site_engineer"},
        {"email": "shivsaran@vasuinfosec.com", "name": "Shiv Saran (Site Engineer)", "role": "site_engineer"},
        {"email": "abhishek@vasuinfosec.com", "name": "Abhishek (Stores)", "role": "store"},
    ]
    for u in demo_users:
        existing = await db.users.find_one({"email": u["email"]}, {"_id": 0})
        if not existing:
            await db.users.insert_one({
                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                "email": u["email"], "name": u["name"], "picture": "",
                "role": u["role"], "is_active": True, "created_at": now_utc(),
            })
        else:
            # Only backfill display name; do NOT overwrite an already-set role
            # (admins may have adjusted roles in the UI).
            await db.users.update_one(
                {"email": u["email"]},
                {"$set": {"name": u["name"]},
                 "$setOnInsert": {"role": u["role"]}}
            )
            # If existing role is legacy or missing, canonicalize
            cur = existing.get("role")
            if not cur or cur in LEGACY_ROLE_MAP:
                await db.users.update_one({"email": u["email"]},
                                          {"$set": {"role": u["role"]}})

    # Projects
    projects = [
        {"code": "VIS-101", "name": "ABC IT Park Fire Safety", "site": "Bangalore Whitefield", "client": "ABC Ltd"},
        {"code": "VIS-102", "name": "XYZ Data Center CCTV", "site": "Hyderabad Gachibowli", "client": "XYZ Corp"},
        {"code": "VIS-103", "name": "PQR Mall Access Control", "site": "Mumbai Andheri", "client": "PQR Group"},
    ]
    for p in projects:
        existing = await db.projects.find_one({"code": p["code"]}, {"_id": 0})
        if not existing:
            await db.projects.insert_one({"project_id": gid("prj"), **p, "active": True,
                                          "site_engineers": [], "project_managers": []})

    # Seed team assignments (idempotent)
    # - site_engineer demo user -> site_engineers on all seed projects
    # - pm demo + real PMs (saket, himanshu) -> project_managers on all seed projects
    se_user = await db.users.find_one({"email": "siteeng@vasu.dev"}, {"_id": 0, "user_id": 1})
    pm_user = await db.users.find_one({"email": "pm@vasu.dev"}, {"_id": 0, "user_id": 1})
    saket = await db.users.find_one({"email": "saket.iyer@vasuinfosec.com"}, {"_id": 0, "user_id": 1})
    himanshu = await db.users.find_one({"email": "himanshu@vasuinfosec.com"}, {"_id": 0, "user_id": 1})
    se_ids = [x["user_id"] for x in (se_user, pm_user) if x]  # legacy pm@ kept as SE for backwards compat
    pm_ids = [x["user_id"] for x in (pm_user, saket, himanshu) if x]
    if se_ids or pm_ids:
        add_ops: Dict[str, Any] = {}
        if se_ids:
            add_ops["site_engineers"] = {"$each": se_ids}
        if pm_ids:
            add_ops["project_managers"] = {"$each": pm_ids}
        await db.projects.update_many(
            {"code": {"$in": [p["code"] for p in projects]}},
            {"$addToSet": add_ops},
        )

    # Vendors
    vendors = [
        {"name": "Honeywell India Pvt Ltd", "gstin": "29AAACH1234A1Z5", "contact": "9880012345", "address": "Bangalore"},
        {"name": "Siemens Ltd", "gstin": "27AAACS4567B1Z6", "contact": "9820098765", "address": "Mumbai"},
        {"name": "Bosch Security Systems", "gstin": "33AAACB7890C1Z7", "contact": "9840001122", "address": "Chennai"},
        {"name": "Ravel Electronics", "gstin": "33AABCR2345D1Z8", "contact": "9840066001", "address": "Chennai"},
        {"name": "Anixter India Cabling", "gstin": "06AAACA9988E1Z9", "contact": "9910044556", "address": "Gurgaon"},
    ]
    for v in vendors:
        existing = await db.vendors.find_one({"name": v["name"]}, {"_id": 0})
        if not existing:
            await db.vendors.insert_one({"vendor_id": gid("vnd"), **v, "email": "", "active": True})

    # Masters (units, brands)
    masters = [
        {"name": "Nos", "category": "unit"}, {"name": "Meter", "category": "unit"},
        {"name": "Kg", "category": "unit"}, {"name": "Set", "category": "unit"},
        {"name": "Roll", "category": "unit"},
        {"name": "Honeywell", "category": "brand"}, {"name": "Siemens", "category": "brand"},
        {"name": "Bosch", "category": "brand"}, {"name": "Hikvision", "category": "brand"},
        {"name": "CP Plus", "category": "brand"},
    ]
    for m in masters:
        existing = await db.masters.find_one({"name": m["name"], "category": m["category"]}, {"_id": 0})
        if not existing:
            await db.masters.insert_one({"item_id": gid("itm"), **m, "active": True})

    # Materials
    materials = [
        "Smoke Detector Photoelectric", "Heat Detector Fixed 57°C", "Manual Call Point",
        "Sounder Strobe Wall Mount", "Fire Extinguisher CO2 4.5kg",
        "IP CCTV Camera 4MP Bullet", "Access Control Reader RFID",
        "Cat6 UTP Cable 305m Box", "Fire Alarm Control Panel 4-Zone",
        "FM200 Gas Cylinder 40L",
    ]
    for m in materials:
        existing = await db.masters.find_one({"name": m, "category": "material"}, {"_id": 0})
        if not existing:
            await db.masters.insert_one({"item_id": gid("itm"), "name": m, "category": "material", "active": True})

    # GST rates (standard Indian slabs)
    gst_rates = [("Nil", "0"), ("5%", "5"), ("12%", "12"), ("18%", "18"), ("28%", "28")]
    for name, val in gst_rates:
        existing = await db.masters.find_one({"name": name, "category": "gst"}, {"_id": 0})
        if not existing:
            await db.masters.insert_one({"item_id": gid("itm"), "name": name, "category": "gst",
                                         "value": val, "active": True})

    # Departments
    departments = ["Fire Safety", "IT & Networking", "Operations", "Projects", "Purchase", "Accounts"]
    for d in departments:
        existing = await db.masters.find_one({"name": d, "category": "department"}, {"_id": 0})
        if not existing:
            await db.masters.insert_one({"item_id": gid("itm"), "name": d, "category": "department",
                                         "active": True})

    # Migrate legacy project.client strings -> Customer records (permanent Customer IDs).
    # Any project without a customer_id but with a non-empty client string gets a matching Customer.
    legacy_projects = await db.projects.find(
        {"$and": [{"client": {"$nin": [None, ""]}},
                  {"$or": [{"customer_id": None}, {"customer_id": {"$exists": False}}]}]},
        {"_id": 0, "project_id": 1, "client": 1}
    ).to_list(500)
    for lp in legacy_projects:
        client_name = (lp.get("client") or "").strip()
        if not client_name:
            continue
        # See if a Customer already exists with that name (case-insensitive)
        cust = await db.customers.find_one(
            {"name": {"$regex": f"^{re.escape(client_name)}$", "$options": "i"}}, {"_id": 0}
        )
        if not cust:
            # Generate a safe alphanumeric customer_id from the name (fallback if collision)
            base = re.sub(r"[^A-Za-z0-9]+", "", client_name).upper()[:10] or "CUST"
            candidate = f"CUST-{base}"
            suffix = 1
            while await db.customers.find_one({"customer_id": candidate}, {"_id": 0}):
                candidate = f"CUST-{base}-{suffix:02d}"; suffix += 1
            cust = {
                "customer_id": candidate,
                "name": client_name, "gstin": "", "pan": "",
                "billing_address": "", "shipping_address": "",
                "contact_person": "", "phone": "", "email": "",
                "remarks": "Auto-created from legacy project.client string",
                "active": True, "created_at": now_utc(),
            }
            await db.customers.insert_one(cust)
        # Link project -> customer
        await db.projects.update_one(
            {"project_id": lp["project_id"]},
            {"$set": {"customer_id": cust["customer_id"]}},
        )

    return {"ok": True, "message": "Seed complete", "logins": [u["email"] for u in demo_users]}

# ---------------------- Startup ----------------------
@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.mrfs.create_index("mrf_id", unique=True)
    await db.mrfs.create_index("mrf_number", unique=True)
    await db.pos.create_index("po_id", unique=True)
    await db.pos.create_index("po_number", unique=True)
    await db.customers.create_index("customer_id", unique=True)
    await db.customer_pos.create_index("cpo_id", unique=True)

@app.on_event("shutdown")
async def shutdown():
    client.close()

@api.get("/")
async def root():
    return {"app": "Vasu Infosec MRF & PO", "ok": True}

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
