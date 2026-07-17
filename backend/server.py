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
from typing import List, Optional, Literal, Dict, Any, Tuple

import httpx
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, Response, UploadFile, File, Body
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, EmailStr, field_validator

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
GRN_ROLES = {"purchase", "admin"}  # Only Purchase creates GRN; Admin (Accounts) can also.
GRN_APPROVER_ROLES = {"admin", "director"}  # Accounts / Director approve GRN
DC_ROLES = {"purchase", "admin"}
DC_APPROVER_ROLES = {"admin", "director"}
CS_ROLES_UPLOAD_DEFERRED_ROLES = {"purchase", "admin"}
CS_APPROVER_ROLES = {"pm", "gm", "director"}

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
    # ---- Phase 3: master-driven selection (dropdown-only for site engineers) ----
    material_id: Optional[str] = None      # FK -> masters.item_id (category=material)
    make: Optional[str] = ""               # from masters.brand
    make_id: Optional[str] = None
    model: Optional[str] = ""              # from masters.model
    model_id: Optional[str] = None
    priority: Optional[str] = "normal"     # low | normal | high | urgent

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v):
        if v is None or v == "":
            return "normal"
        s = str(v).lower().strip()
        if s not in ("low", "normal", "high", "urgent"):
            raise ValueError("priority must be one of low, normal, high, urgent")
        return s

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

# ---------------------- Delivery Challan ----------------------
class DCItemIn(BaseModel):
    """One line on a Delivery Challan."""
    description: str
    unit: str = "nos"
    qty: float
    material_uid: Optional[str] = ""
    variant_uid: Optional[str] = ""
    make: Optional[str] = ""
    model: Optional[str] = ""
    remarks: Optional[str] = ""
    # optional back-links so we can trace DC back to source records
    mrf_id: Optional[str] = ""
    po_id: Optional[str] = ""
    grn_id: Optional[str] = ""
    item_line_id: Optional[str] = ""

class DCCreate(BaseModel):
    dc_type: str = "outbound"  # inbound | outbound
    po_id: Optional[str] = ""
    grn_id: Optional[str] = ""
    mrf_refs: List[str] = []
    project_id: str
    customer_id: Optional[str] = ""
    vendor_id: Optional[str] = ""
    from_location: str
    to_location: str
    dispatch_date: str
    vehicle_no: Optional[str] = ""
    driver_name: Optional[str] = ""
    driver_contact: Optional[str] = ""
    transporter: Optional[str] = ""
    e_way_bill_no: Optional[str] = ""
    e_way_bill_date: Optional[str] = ""
    items: List[DCItemIn]
    remarks: Optional[str] = ""
    authorised_signatory: Optional[str] = ""
    vendor_dc_ref: Optional[str] = ""  # for inbound DC — vendor's DC number

class DC(DCCreate):
    dc_id: str = Field(default_factory=lambda: gid("dc"))
    dc_number: str
    date: datetime = Field(default_factory=now_utc)
    status: str = "pending_approval"  # pending_approval | approved | rejected | cancelled | in_transit | delivered
    approval_history: List[Dict[str, Any]] = []
    customer_name: Optional[str] = ""
    vendor_name: Optional[str] = ""
    created_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: Optional[datetime] = None
    deleted: bool = False

# ---------------------- Comparative Statement (import-only) ----------------------
class ComparativeVendorQuote(BaseModel):
    vendor_id: Optional[str] = ""
    vendor_name: str
    quote_number: Optional[str] = ""
    quote_date: Optional[str] = ""
    amount: float = 0.0
    gst_incl: bool = False
    validity: Optional[str] = ""
    remarks: Optional[str] = ""

class ComparativeStatementCreate(BaseModel):
    mrf_id: Optional[str] = ""
    po_id: Optional[str] = ""
    project_id: Optional[str] = ""
    customer_id: Optional[str] = ""
    title: str
    remarks: Optional[str] = ""
    prepared_by: Optional[str] = ""  # who created it outside the app
    prepared_on: Optional[str] = ""
    vendors: List[ComparativeVendorQuote] = []
    l1_vendor: Optional[str] = ""
    l1_amount: Optional[float] = 0
    selected_vendor: Optional[str] = ""
    selection_reason: Optional[str] = ""
    file_name: str
    mime_type: str
    file_base64: str  # base64-encoded attachment

class ComparativeStatement(ComparativeStatementCreate):
    cs_id: str = Field(default_factory=lambda: gid("cs"))
    cs_number: str
    uploaded_by: str
    uploaded_by_name: Optional[str] = ""
    uploaded_at: datetime = Field(default_factory=now_utc)
    file_size: int = 0
    status: str = "pending_approval"  # pending_approval | approved | rejected | superseded | cancelled
    approval_history: List[Dict[str, Any]] = []
    deleted: bool = False

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
    # Login audit
    try:
        await audit("auth", user_id, "login", UserOut(**user),
                    {"method": "emergent", "email": email})
    except Exception:
        pass
    return {"session_token": session_token, "user": UserOut(**user).model_dump()}

@api.get("/auth/me", response_model=UserOut)
async def me(authorization: Optional[str] = Header(None)):
    return await get_current_user(authorization)

@api.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        if sess:
            u = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
            if u:
                try:
                    await audit("auth", u["user_id"], "logout", UserOut(**u), {})
                except Exception:
                    pass
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
    try:
        await audit("auth", user_id, "login", UserOut(**user),
                    {"method": "dev-login", "email": email, "role": role})
    except Exception:
        pass
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

# ---------------------- Phase 4: Material Master (MAT-####) + Variants (VAR-####) ----------------------
MATERIAL_STATUSES = {"pending_pm_review", "approved", "rejected", "pending_gm_approval", "needs_correction"}
MAT_WORD_LIMIT = 100

async def _next_seq(name: str) -> int:
    """Atomic monotonic counter for MAT/VAR sequences."""
    doc = await db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"n": 1}}, upsert=True, return_document=True
    )
    return int(doc["n"]) if doc else 1

def _mat_uid(n: int) -> str: return f"MAT-{n:04d}"
def _var_uid(n: int) -> str: return f"VAR-{n:04d}"
def _norm(s: str) -> str: return re.sub(r"\s+", " ", (s or "").strip()).lower()
def _word_count(s: str) -> int: return len([w for w in re.split(r"\s+", (s or "").strip()) if w])

class MaterialIn(BaseModel):
    description: str
    category: str = ""      # system_category (FAS/FFT/GSS/CCTV etc.)
    unit: str = ""
    gst_rate: Optional[float] = None
    item_code: Optional[str] = ""   # user-editable short recall code
    remarks: Optional[str] = ""

async def _ensure_variant(material_uid: str, make: str, model: str,
                          material_id: Optional[str] = None) -> Dict[str, Any]:
    """Get or create a variant (idempotent). Prevents duplicate (mat, make, model)."""
    make = (make or "").strip()
    model = (model or "").strip()
    q = {"material_uid": material_uid, "make_norm": _norm(make), "model_norm": _norm(model)}
    existing = await db.variants.find_one(q, {"_id": 0})
    if existing:
        return existing
    n = await _next_seq("variants")
    doc = {
        "variant_uid": _var_uid(n),
        "material_uid": material_uid,
        "material_id": material_id,
        "make": make, "make_norm": _norm(make),
        "model": model, "model_norm": _norm(model),
        "created_at": now_utc(),
    }
    try:
        await db.variants.insert_one(doc)
    except DuplicateKeyError:
        existing = await db.variants.find_one(q, {"_id": 0})
        return existing or doc
    doc.pop("_id", None)
    return doc

@api.get("/materials")
async def list_materials(status: Optional[str] = None,
                         q: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    """List materials. Default returns ONLY approved. Pass ?status=all to see everything."""
    await get_current_user(authorization)
    filt: Dict[str, Any] = {}
    if status and status != "all":
        filt["status"] = status
    elif not status:
        filt["status"] = "approved"
    if q:
        filt["$or"] = [
            {"description": {"$regex": re.escape(q), "$options": "i"}},
            {"item_code": {"$regex": re.escape(q), "$options": "i"}},
            {"material_uid": {"$regex": re.escape(q), "$options": "i"}},
        ]
    docs = await db.materials.find(filt, {"_id": 0}).sort([("material_uid", 1)]).to_list(2000)
    return docs

@api.get("/materials/counts")
async def material_counts(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    out: Dict[str, int] = {}
    async for r in db.materials.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        out[r["_id"]] = r["n"]
    return out

@api.post("/materials")
async def create_material(body: MaterialIn, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only Purchase/Admin/Director can add materials")
    desc = (body.description or "").strip()
    if not desc:
        raise HTTPException(400, "Description is required")
    if _word_count(desc) > MAT_WORD_LIMIT:
        raise HTTPException(400, f"Description exceeds {MAT_WORD_LIMIT} words")
    norm = _norm(desc)
    dup = await db.materials.find_one({"description_norm": norm}, {"_id": 0, "material_uid": 1, "status": 1})
    if dup:
        raise HTTPException(400, f"Material already exists as {dup['material_uid']} (status: {dup['status']})")
    n = await _next_seq("materials")
    doc = {
        "material_uid": _mat_uid(n),
        "description": desc,
        "description_norm": norm,
        "category": (body.category or "").strip(),
        "unit": (body.unit or "").strip(),
        "gst_rate": float(body.gst_rate) if body.gst_rate is not None else None,
        "item_code": (body.item_code or "").strip(),
        "remarks": (body.remarks or "").strip(),
        # Admin/Director bypass PM review (still audited)
        "status": "approved" if u.role in ("admin", "director") else "pending_pm_review",
        "created_by": u.user_id, "created_by_name": u.name,
        "created_at": now_utc(), "updated_at": now_utc(),
        "approved_by": u.user_id if u.role in ("admin", "director") else None,
        "approved_at": now_utc() if u.role in ("admin", "director") else None,
    }
    await db.materials.insert_one(doc)
    doc.pop("_id", None)
    await master_audit("material", doc["material_uid"], "create", u,
                       "New material added", None, doc)
    return doc

@api.put("/materials/{material_uid}")
async def update_material(material_uid: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    """Edit a material. If it's approved, changes go to pending_gm_approval (GM approves).
    If it's still pending_pm_review, edits are inline (Purchase can amend before PM sees it)."""
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only Purchase/Admin/Director can edit materials")
    mat = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})
    if not mat:
        raise HTTPException(404, "Material not found")
    reason = (body.pop("reason", "") or "").strip()
    if not reason:
        raise HTTPException(400, "Reason is required for material changes")
    updates: Dict[str, Any] = {}
    for k in ("description", "category", "unit", "item_code", "remarks"):
        if k in body:
            updates[k] = (str(body[k] or "")).strip()
    if "gst_rate" in body:
        try: updates["gst_rate"] = float(body["gst_rate"]) if body["gst_rate"] is not None else None
        except Exception: raise HTTPException(400, "gst_rate must be numeric")
    if not updates:
        raise HTTPException(400, "Nothing to update")
    if "description" in updates:
        if _word_count(updates["description"]) > MAT_WORD_LIMIT:
            raise HTTPException(400, f"Description exceeds {MAT_WORD_LIMIT} words")
        updates["description_norm"] = _norm(updates["description"])
        # Dedup check (case-insensitive) — allow the same material_uid to keep its own
        dup = await db.materials.find_one({
            "description_norm": updates["description_norm"],
            "material_uid": {"$ne": material_uid},
        })
        if dup:
            raise HTTPException(400, f"Another material already has this description: {dup['material_uid']}")
    was_approved = mat.get("status") == "approved"
    if was_approved and u.role not in ("admin", "director"):
        updates["status"] = "pending_gm_approval"
        updates["pending_change"] = {"changed_by": u.user_id, "changed_at": now_utc().isoformat(), "reason": reason}
    updates["updated_at"] = now_utc()
    await db.materials.update_one({"material_uid": material_uid}, {"$set": updates})
    old_snap = {k: mat.get(k) for k in updates if k in mat}
    await master_audit("material", material_uid,
                       "edit_requires_gm" if was_approved else "update",
                       u, reason, old_snap, updates)
    return await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})

@api.post("/materials/{material_uid}/action")
async def material_action(material_uid: str, body: dict,
                          authorization: Optional[str] = Header(None)):
    """PM approve / reject a pending material. Also handles the 'needs_correction' flag toggle."""
    u = await get_current_user(authorization)
    if u.role not in ("pm", "admin", "director"):
        raise HTTPException(403, "Only PM/Admin/Director can approve materials")
    action = (body.get("action") or "").lower()
    reason = (body.get("reason") or "").strip()
    if action not in ("approve", "reject", "flag"):
        raise HTTPException(400, "action must be approve/reject/flag")
    mat = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})
    if not mat:
        raise HTTPException(404, "Material not found")
    if mat.get("status") not in ("pending_pm_review", "needs_correction"):
        raise HTTPException(400, f"Cannot {action}: material is '{mat.get('status')}'")
    new_status = {"approve": "approved", "reject": "rejected", "flag": "needs_correction"}[action]
    upd: Dict[str, Any] = {"status": new_status, "updated_at": now_utc()}
    if action == "approve":
        upd["approved_by"] = u.user_id
        upd["approved_at"] = now_utc()
    await db.materials.update_one({"material_uid": material_uid}, {"$set": upd})
    await master_audit("material", material_uid, f"pm_{action}", u,
                       reason or f"PM {action}", {"status": mat.get("status")}, upd)
    return await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})

@api.post("/materials/{material_uid}/gm-approve")
async def gm_approve_material(material_uid: str, body: dict,
                              authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("gm", "director", "admin"):
        raise HTTPException(403, "Only GM/Director/Admin can approve material changes")
    mat = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})
    if not mat:
        raise HTTPException(404, "Material not found")
    if mat.get("status") != "pending_gm_approval":
        raise HTTPException(400, f"Not awaiting GM approval (status={mat.get('status')})")
    action = (body.get("action") or "approve").lower()
    reason = (body.get("reason") or "").strip()
    new_status = "approved" if action == "approve" else "rejected"
    await db.materials.update_one({"material_uid": material_uid},
                                  {"$set": {"status": new_status,
                                            "gm_action_by": u.user_id,
                                            "gm_action_at": now_utc(),
                                            "pending_change": None,
                                            "updated_at": now_utc()}})
    await master_audit("material", material_uid, f"gm_{action}", u, reason,
                       {"status": "pending_gm_approval"}, {"status": new_status})
    return await db.materials.find_one({"material_uid": material_uid}, {"_id": 0})

@api.post("/materials/bulk-action")
async def bulk_material_action(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("pm", "admin", "director"):
        raise HTTPException(403, "Only PM/Admin/Director")
    action = (body.get("action") or "").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be approve/reject")
    uids = body.get("material_uids") or []
    reason = body.get("reason") or f"Bulk {action}"
    ok, skipped = 0, 0
    for uid in uids:
        mat = await db.materials.find_one({"material_uid": uid}, {"_id": 0})
        if not mat or mat.get("status") not in ("pending_pm_review", "needs_correction"):
            skipped += 1
            continue
        new_status = "approved" if action == "approve" else "rejected"
        upd = {"status": new_status, "updated_at": now_utc()}
        if action == "approve":
            upd["approved_by"] = u.user_id
            upd["approved_at"] = now_utc()
        await db.materials.update_one({"material_uid": uid}, {"$set": upd})
        await master_audit("material", uid, f"pm_{action}_bulk", u, reason,
                           {"status": mat.get("status")}, upd)
        ok += 1
    return {"ok": ok, "skipped": skipped}

# ---- Bulk import (Excel/CSV) ----
@api.get("/import/materials/template")
async def material_import_template(token: Optional[str] = None,
                                   authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only Purchase/Admin/Director")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Materials"
    headers = ["Material Description", "Category", "Make", "Model", "Unit",
               "GST Rate %", "Item Code", "Remarks"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    # Sample rows
    ws.append(["Smoke Detector Photoelectric 2-wire", "Fire Alarm", "Legrand", "XC-500", "Nos", 18, "SD-2W", "Sample row — delete before upload"])
    ws.append(["Fire Alarm Control Panel 4-Zone", "Fire Alarm", "Honeywell", "NFS2-3030", "Nos", 18, "FACP-4Z", ""])
    # Column widths
    widths = [50, 20, 18, 18, 10, 12, 14, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    return _excel_response(wb, "material_import_template.xlsx")

@api.post("/import/materials")
async def import_materials(payload: dict, authorization: Optional[str] = Header(None)):
    """Body: {'rows': [{Material Description, Category, Make, Model, Unit, GST Rate %, Item Code, Remarks}]}.
    OR upload via multipart. Accepted format for MVP: JSON payload with rows array.
    """
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "admin", "director"):
        raise HTTPException(403, "Only Purchase can bulk-import materials")
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "No rows to import")
    created, duplicates, errors, needs_correction = [], [], [], []
    for idx, r in enumerate(rows, 2):  # start at row 2 (1 is header)
        desc = str(r.get("Material Description") or r.get("description") or "").strip()
        if not desc:
            errors.append({"row": idx, "reason": "empty description"})
            continue
        wc = _word_count(desc)
        if wc > MAT_WORD_LIMIT:
            errors.append({"row": idx, "description": desc[:60] + "…",
                           "reason": f"description has {wc} words (max {MAT_WORD_LIMIT})"})
            needs_correction.append({"row": idx, "description": desc, "words": wc})
            continue
        norm = _norm(desc)
        existing = await db.materials.find_one({"description_norm": norm}, {"_id": 0, "material_uid": 1})
        if existing:
            duplicates.append({"row": idx, "material_uid": existing["material_uid"], "description": desc})
            continue
        try:
            gst = float(r.get("GST Rate %") or r.get("gst_rate") or 0)
        except Exception:
            gst = None
        n = await _next_seq("materials")
        doc = {
            "material_uid": _mat_uid(n),
            "description": desc, "description_norm": norm,
            "category": str(r.get("Category") or r.get("category") or "").strip(),
            "make": str(r.get("Make") or r.get("make") or "").strip(),
            "model": str(r.get("Model") or r.get("model") or "").strip(),
            "unit": str(r.get("Unit") or r.get("unit") or "").strip(),
            "gst_rate": gst,
            "item_code": str(r.get("Item Code") or r.get("item_code") or "").strip(),
            "remarks": str(r.get("Remarks") or r.get("remarks") or "").strip(),
            "status": "pending_pm_review",
            "created_by": u.user_id, "created_by_name": u.name,
            "created_at": now_utc(), "updated_at": now_utc(),
            "source": "bulk_import",
        }
        await db.materials.insert_one(doc)
        doc.pop("_id", None)
        # If make provided, register a variant (still pending until material approved)
        if doc["make"]:
            await _ensure_variant(doc["material_uid"], doc["make"], doc["model"], doc["material_uid"])
        created.append({"material_uid": doc["material_uid"], "description": desc})
    await master_audit("material.bulk_import", f"batch_{now_utc().timestamp()}", "bulk_import", u,
                       f"Purchase bulk import: {len(created)} created, {len(duplicates)} dup, {len(errors)} err",
                       None, {"created": len(created), "duplicates": len(duplicates), "errors": len(errors)})
    return {
        "created": created, "duplicates": duplicates, "errors": errors,
        "needs_correction": needs_correction,
        "summary": {
            "created": len(created), "duplicates": len(duplicates),
            "errors": len(errors), "flagged_word_limit": len(needs_correction),
        },
    }

# ---- Variants ----
@api.get("/variants")
async def list_variants(material_uid: Optional[str] = None,
                        authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    q: Dict[str, Any] = {}
    if material_uid: q["material_uid"] = material_uid
    return await db.variants.find(q, {"_id": 0}).sort("variant_uid", 1).to_list(2000)

@api.post("/variants")
async def create_variant(body: dict, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("purchase", "site_engineer", "pm", "admin", "director"):
        raise HTTPException(403, "Not allowed")
    material_uid = (body.get("material_uid") or "").strip()
    if not material_uid:
        raise HTTPException(400, "material_uid required")
    mat = await db.materials.find_one({"material_uid": material_uid}, {"_id": 0, "status": 1})
    if not mat:
        raise HTTPException(404, "Material not found")
    if mat.get("status") != "approved" and u.role not in ("admin", "director"):
        raise HTTPException(400, "Cannot add variants to un-approved materials")
    return await _ensure_variant(
        material_uid,
        body.get("make") or "",
        body.get("model") or "",
        material_uid,
    )

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

async def next_dc_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"dc_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    seq = r["seq"] if r else 1
    return f"DC/{year}/{seq:04d}"

async def next_cs_number() -> str:
    year = datetime.now().year
    r = await db.counters.find_one_and_update(
        {"_id": f"cs_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    seq = r["seq"] if r else 1
    return f"CS/{year}/{seq:04d}"

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
    await audit("mrf", mrf.mrf_id, "create", u,
                {"mrf_number": mrf.mrf_number,
                 "old_value": None,
                 "new_value": {"status": "draft",
                               "project_id": mrf.project_id,
                               "customer_id": cust_id,
                               "customer_name": cust_name,
                               "item_count": len(items),
                               "site": mrf.site}})
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
    await audit("mrf", mrf_id, "submit", u,
                {"old_value": {"status": d["status"]},
                 "new_value": {"status": "pm_review"},
                 "mrf_number": d["mrf_number"]})
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
        await audit("mrf", mrf_id, "return", u,
                    {"reason": body.comment or "", "comment": body.comment,
                     "old_value": {"status": d["status"]},
                     "new_value": {"status": "returned"},
                     "mrf_number": d["mrf_number"]})
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
    await audit("mrf", mrf_id, body.action, u,
                {"reason": body.comment or "", "comment": body.comment,
                 "items": body.item_actions,
                 "old_value": {"status": d.get("status")},
                 "new_value": {"status": new_status},
                 "mrf_number": d["mrf_number"]})
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
    await audit("mrf", mrf_id, "send_to_purchase", u,
                {"old_value": {"status": d.get("status")},
                 "new_value": {"status": "sent_to_purchase"},
                 "mrf_number": d.get("mrf_number")})
    return {"ok": True}

@api.put("/mrf/{mrf_id}")
async def update_mrf_draft(mrf_id: str, body: dict,
                           authorization: Optional[str] = Header(None)):
    """Update a Draft or Returned MRF. Site engineers can only edit their own drafts.
    After submission, editing is blocked (per spec) unless the MRF is returned."""
    u = await get_current_user(authorization)
    mrf = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    # Only draft or returned MRFs are editable via this endpoint
    editable_states = {"draft", "returned"}
    if canonical_mrf_status(mrf.get("status")) not in editable_states and mrf.get("status") not in editable_states:
        raise HTTPException(400, f"MRF is '{mrf.get('status')}' — cannot edit after submission (only 'returned' MRFs can be re-edited)")
    # RBAC: creator OR admin/director
    if u.role not in ("admin", "director") and mrf.get("created_by") != u.user_id:
        raise HTTPException(403, "Only the MRF creator (or admin/director) can edit this draft")

    updates: Dict[str, Any] = {}
    for k in ("site", "required_by", "requesting_person", "system_category", "remarks", "attachments"):
        if k in body:
            updates[k] = body[k]
    if "items" in body and isinstance(body["items"], list):
        # Preserve existing item_line_id if provided
        new_items = []
        old_items = {it.get("item_line_id"): it for it in mrf.get("items", [])}
        for i in body["items"]:
            line_id = i.get("item_line_id") or f"mli_{uuid.uuid4().hex[:12]}"
            base = old_items.get(line_id) or {}
            merged = {**base, **i, "item_line_id": line_id}
            merged.setdefault("status", "pending")
            merged.setdefault("billing_status", "not_billed")
            merged.setdefault("qty_received", 0)
            merged.setdefault("qty_issued", 0)
            merged.setdefault("qty_billed", 0)
            merged.setdefault("qty_ordered", 0)
            if merged.get("qty_approved") is None:
                merged["qty_approved"] = merged.get("qty_requested")
            new_items.append(merged)
        updates["items"] = new_items

    if body.get("project_id") and body["project_id"] != mrf.get("project_id"):
        proj = await db.projects.find_one({"project_id": body["project_id"]}, {"_id": 0}) or {}
        cid = proj.get("customer_id")
        cust_name = ""
        if cid:
            c = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) or {}
            cust_name = c.get("name") or ""
        updates["project_id"] = body["project_id"]
        updates["customer_id"] = cid
        updates["customer_name"] = cust_name or proj.get("client") or ""

    if not updates:
        raise HTTPException(400, "Nothing to update")

    # If Site Engineer changed project — customer snapshot already refreshed above.

    updates["updated_at"] = now_utc()
    await db.mrfs.update_one({"mrf_id": mrf_id}, {"$set": updates})
    # Compute a compact old/new diff for the audit trail
    old_snap = {k: mrf.get(k) for k in updates.keys() if k != "updated_at"}
    new_snap = {k: v for k, v in updates.items() if k != "updated_at"}
    await audit("mrf", mrf_id, "edit_draft", u,
                {"old_value": old_snap, "new_value": new_snap,
                 "mrf_number": mrf.get("mrf_number"),
                 "reason": body.get("reason") or ""})
    return await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})

@api.delete("/mrf/{mrf_id}")
async def delete_mrf(mrf_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin can delete")
    m = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0, "mrf_number": 1, "status": 1})
    await db.mrfs.update_one({"mrf_id": mrf_id}, {"$set": {"deleted": True}})
    await audit("mrf", mrf_id, "soft_delete", u,
                {"old_value": {"deleted": False, "status": (m or {}).get("status")},
                 "new_value": {"deleted": True},
                 "mrf_number": (m or {}).get("mrf_number")})
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
            if k == "priority" and new_v not in (None, "", "low", "normal", "high", "urgent"):
                raise HTTPException(400, "priority must be one of low, normal, high, urgent")
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

    await audit("po", po.po_id, "create", u,
                {"po_number": po.po_number,
                 "old_value": None,
                 "new_value": {"total": total, "status": initial_status,
                               "vendor_id": po_doc.get("vendor_id"),
                               "customer_id": cust_id,
                               "project_id": po_doc.get("project_id"),
                               "item_count": len(po_doc.get("items") or [])},
                 "total": total,
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

    await audit("po", po_id, f"po_{action}", u,
                {"comment": comment, "old_value": {"status": cur},
                 "new_value": {"status": new_status},
                 "reason": comment,
                 "po_number": po.get("po_number")})
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
            "customer_id": po.get("customer_id"),
            "date": now_utc(),
            "items": grn_items,
            "received_by": u.user_id,
            "received_by_name": u.name,
            "remarks": (body or {}).get("remarks", ""),
            "status": "pending_approval",  # awaits admin/accounts approval
            "approval_history": [],
        })
        await audit("grn", grn_id, "create", u,
                    {"grn_number": grn_number,
                     "old_value": None,
                     "new_value": {"status": "pending_approval",
                                   "po_number": po["po_number"],
                                   "item_count": len(grn_items)},
                     "record_number": grn_number,
                     "reason": (body or {}).get("remarks", "")})

    await audit("po", po_id, "received", u,
                {"old_value": {"status": po.get("status")},
                 "new_value": {"status": new_status},
                 "grn_number": grn_number,
                 "per_line": grn_items,
                 "po_number": po.get("po_number"),
                 "reason": (body or {}).get("remarks", "")})
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
                     entity: Optional[str] = None,
                     action: Optional[str] = None,
                     user_id: Optional[str] = None,
                     user_role: Optional[str] = None,
                     since: Optional[str] = None,
                     limit: int = 200,
                     authorization: Optional[str] = Header(None)):
    """Unified audit trail feed.

    Access model:
    - Admin / Director / GM / Purchase: full system audit visibility (all events).
    - PM: audit entries for MRFs/POs on their projects + their own actions + all master-data audits.
    - Site Engineer: audit for MRFs they created + PO events referring to those MRFs + their own actions.
    - Store: audit for MRFs they raised + GRN/received events + their own actions.

    Additional filters: `entity`, `action` (prefix match), `user_id`, `user_role`,
    `since` (ISO8601 date/datetime — inclusive lower bound), `limit` (max 500).
    """
    u = await get_current_user(authorization)
    limit = max(1, min(int(limit or 200), 500))

    if entity_id:
        # Entity-scoped audit — access is gated by ability to read that entity.
        if entity_id.startswith("mrf_"):
            m = await db.mrfs.find_one({"mrf_id": entity_id}, {"_id": 0})
            if not m:
                raise HTTPException(404, "MRF not found")
            await _check_mrf_access(u, m)
        elif entity_id.startswith("po_"):
            p = await db.pos.find_one({"po_id": entity_id}, {"_id": 0})
            if not p:
                raise HTTPException(404, "PO not found")
            await _check_po_access(u, p)
        else:
            # Customer / vendor / material / master audits — visible to
            # management (admin/director/gm/purchase/pm) and to the acting user.
            if u.role not in ("admin", "director", "purchase", "pm", "gm"):
                # site_engineer / store can still see logs they themselves generated
                pass

    q: Dict[str, Any] = {}
    if entity_id: q["entity_id"] = entity_id
    if entity: q["entity"] = entity
    if action: q["action"] = {"$regex": f"^{action}"}
    if user_id: q["user_id"] = user_id
    if user_role: q["user_role"] = user_role
    if since:
        try:
            dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q["timestamp"] = {"$gte": dt}
        except Exception:
            raise HTTPException(400, "since must be ISO8601")

    # Global-view RBAC scoping when NO entity_id is supplied.
    if not entity_id:
        if u.role in ("admin", "director", "gm", "purchase"):
            pass  # full access
        elif u.role == "pm":
            # PM: audits for their projects' MRFs/POs + their own actions +
            # all master-data audits (they need visibility into upstream data changes).
            prjs = await db.projects.find({"project_managers": u.user_id},
                                          {"_id": 0, "project_id": 1}).to_list(500)
            proj_ids = [p["project_id"] for p in prjs]
            mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
                {"project_id": {"$in": proj_ids}}, {"_id": 0, "mrf_id": 1}).to_list(5000)]
            po_ids = [p["po_id"] for p in await db.pos.find(
                {"project_id": {"$in": proj_ids}}, {"_id": 0, "po_id": 1}).to_list(5000)]
            or_clauses: List[Dict[str, Any]] = [
                {"user_id": u.user_id},
                {"entity_id": {"$in": mrf_ids}} if mrf_ids else {"entity_id": "__none__"},
                {"entity_id": {"$in": po_ids}} if po_ids else {"entity_id": "__none__"},
                {"entity": {"$in": ["customer", "vendor", "project", "material", "customer_po",
                                     "master.material", "master.category", "master.department",
                                     "material.bulk_import"]}},
            ]
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        elif u.role == "site_engineer":
            mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
                {"created_by": u.user_id}, {"_id": 0, "mrf_id": 1}).to_list(5000)]
            or_clauses = [{"user_id": u.user_id}]
            if mrf_ids:
                or_clauses.append({"entity_id": {"$in": mrf_ids}})
                # Also include POs that reference their MRFs
                po_ids = [p["po_id"] for p in await db.pos.find(
                    {"mrf_refs": {"$in": mrf_ids}}, {"_id": 0, "po_id": 1}).to_list(5000)]
                if po_ids:
                    or_clauses.append({"entity_id": {"$in": po_ids}})
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        elif u.role == "store":
            or_clauses = [
                {"user_id": u.user_id},
                {"action": {"$regex": "^received|^po_received|grn"}},
            ]
            q = {"$and": [q, {"$or": or_clauses}]} if q else {"$or": or_clauses}
        else:
            # Unknown role — restrict to own actions only.
            q = {"$and": [q, {"user_id": u.user_id}]} if q else {"user_id": u.user_id}

    logs = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return [_strip_oids(d) for d in logs]

@api.get("/audit/facets")
async def audit_facets(authorization: Optional[str] = Header(None)):
    """Filter options for the audit UI: distinct entities, actions, and users."""
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director", "gm", "purchase", "pm"):
        raise HTTPException(403, "Not allowed")
    ents = await db.audit_logs.distinct("entity")
    acts = await db.audit_logs.distinct("action")
    users_docs = await db.audit_logs.aggregate([
        {"$group": {"_id": "$user_id",
                    "name": {"$first": "$user_name"},
                    "role": {"$first": "$user_role"}}},
        {"$limit": 200},
    ]).to_list(200)
    users = [{"user_id": d["_id"], "name": d.get("name"), "role": d.get("role")}
             for d in users_docs if d.get("_id")]
    return {"entities": sorted([e for e in ents if e]),
            "actions": sorted([a for a in acts if a]),
            "users": users}

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
# Detailed company block (env-overridable). These appear on all outbound documents.
VASU_LEGAL_NAME = os.getenv("VASU_LEGAL_NAME", "Vasu Infosec Pvt Ltd")
VASU_GSTIN = os.getenv("VASU_GSTIN", "27AAFCV0000A1Z0")
VASU_PAN = os.getenv("VASU_PAN", "AAFCV0000A")
VASU_STATE = os.getenv("VASU_STATE", "Maharashtra")
VASU_STATE_CODE = os.getenv("VASU_STATE_CODE", "27")
VASU_CIN = os.getenv("VASU_CIN", "")
VASU_ADDR_FULL = os.getenv(
    "VASU_ADDR_FULL",
    "Corporate Office: Pune, Maharashtra · Branch: Delhi · www.vasuinfosec.com",
)
VASU_CONTACT = os.getenv("VASU_CONTACT", "accounts@vasuinfosec.com  ·  +91-20-0000-0000")

# ---------------------- Export helpers (validation / audit / enrichment) ----------------------
async def _log_export(user: UserOut, entity: str, entity_id: str, fmt: str,
                      record_number: str = "", extras: Optional[dict] = None):
    """Audit every download/export so ops can prove regulatory compliance."""
    details = {"format": fmt, "record_number": record_number}
    if extras:
        details.update(extras)
    await audit(entity, entity_id, f"export_{fmt}", user, details)

async def _resolve_material_info(item: dict) -> dict:
    """Enrich a PO/MRF line with MAT/VAR UIDs, HSN, category, make/model.
    Returns a dict with keys: material_uid, variant_uid, hsn_code, make, model, category, gst_pct.
    Non-fatal — returns empty strings when unresolved.
    """
    out = {
        "material_uid": item.get("material_uid") or "",
        "variant_uid": item.get("variant_uid") or "",
        "hsn_code": item.get("hsn_code") or "",
        "make": item.get("make") or "",
        "model": item.get("model") or "",
        "category": item.get("category") or "",
        "gst_pct": float(item.get("gst") or 0),
    }
    mat = None
    if out["material_uid"]:
        mat = await db.materials.find_one({"material_uid": out["material_uid"]}, {"_id": 0})
    if not mat:
        desc = (item.get("description") or "").strip()
        if desc:
            mat = await db.materials.find_one({"description_norm": _norm(desc)}, {"_id": 0})
    if mat:
        out["material_uid"] = out["material_uid"] or mat.get("material_uid", "")
        out["hsn_code"] = out["hsn_code"] or (mat.get("hsn_code") or "")
        out["category"] = out["category"] or (mat.get("category") or "")
        if not out["gst_pct"] and mat.get("gst_rate") is not None:
            out["gst_pct"] = float(mat.get("gst_rate") or 0)
    # Resolve variant by (material_uid, make, model)
    if out["material_uid"] and (out["make"] or out["model"]) and not out["variant_uid"]:
        v = await db.variants.find_one(
            {"material_uid": out["material_uid"],
             "make_norm": _norm(out["make"]),
             "model_norm": _norm(out["model"])},
            {"_id": 0, "variant_uid": 1},
        )
        if v:
            out["variant_uid"] = v.get("variant_uid", "")
    return out


def _split_gst_amt(taxable: float, gst_pct: float, intra_state: bool) -> tuple:
    """Return (cgst, sgst, igst)."""
    gst_amt = round(taxable * gst_pct / 100, 2)
    if intra_state:
        half = round(gst_amt / 2, 2)
        return (half, gst_amt - half, 0.0)
    return (0.0, 0.0, gst_amt)


def _is_intra_state(party_state_or_addr: str) -> bool:
    s = (party_state_or_addr or "").upper()
    return ("MAHARASHTRA" in s) or (" MH" in f" {s}") or s.endswith(" MH") or s == "MH"


def _validate_po_for_export(po: dict, vendor: Optional[dict], customer: Optional[dict],
                            project: Optional[dict], fmt: str) -> tuple:
    """Return (missing_mandatory, warnings). Mandatory = blocks export unless ?force=1."""
    missing: List[str] = []
    warnings: List[str] = []

    # Vendor mandatory
    if not (vendor and vendor.get("name")):
        missing.append("Vendor name")
    if vendor and not (vendor.get("gstin") or "").strip():
        warnings.append("Vendor GSTIN")
    if vendor and not (vendor.get("address") or "").strip():
        warnings.append("Vendor address")

    # Customer mandatory (permanent Customer ID + name)
    if not (customer and customer.get("customer_id")):
        missing.append("Customer ID (permanent)")
    if not (customer and customer.get("name")):
        missing.append("Customer name")
    if customer and not (customer.get("gstin") or "").strip():
        warnings.append("Customer GSTIN")

    # Project mandatory
    if not project:
        missing.append("Project")
    else:
        if not project.get("code"):
            warnings.append("Project code")

    # PO metadata
    if not po.get("po_number"):
        missing.append("PO number")
    if not po.get("date"):
        missing.append("PO date")

    # Line items
    items = po.get("items") or []
    if not items:
        missing.append("At least one line item")
    for i, it in enumerate(items, 1):
        if not (it.get("description") or "").strip():
            missing.append(f"Item {i} description")
        if float(it.get("qty") or 0) <= 0:
            missing.append(f"Item {i} qty > 0")
        if float(it.get("rate") or 0) < 0:
            missing.append(f"Item {i} rate ≥ 0")
        if not (it.get("unit") or "").strip():
            warnings.append(f"Item {i} unit")
        # HSN mandatory ONLY for Tally (GST filing). Warning for PDF/Excel.
        if not (it.get("hsn_code") or "").strip():
            if fmt == "tally":
                missing.append(f"Item {i} HSN/SAC (required for Tally)")
            else:
                warnings.append(f"Item {i} HSN/SAC")

    # Vasu GSTIN — mandatory for tally, warning otherwise
    if not VASU_GSTIN:
        (missing if fmt == "tally" else warnings).append("Vasu GSTIN (env: VASU_GSTIN)")

    return missing, warnings


def _validate_mrf_for_export(mrf: dict, project: Optional[dict], customer: Optional[dict],
                             fmt: str) -> tuple:
    missing: List[str] = []
    warnings: List[str] = []
    if not (customer and customer.get("customer_id")):
        # MRFs may pre-date customer master — warn only.
        warnings.append("Customer ID (permanent)")
    if not project:
        missing.append("Project")
    if not mrf.get("mrf_number"):
        missing.append("MRF number")
    items = mrf.get("items") or []
    if not items:
        missing.append("At least one line item")
    for i, it in enumerate(items, 1):
        if not (it.get("description") or "").strip():
            missing.append(f"Item {i} description")
        if float(it.get("qty_requested") or 0) <= 0:
            missing.append(f"Item {i} qty_requested > 0")
    return missing, warnings


def _validation_error(missing: List[str], warnings: List[str], fmt: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "error": "export_validation_failed",
            "format": fmt,
            "missing_mandatory": missing,
            "warnings": warnings,
            "hint": "Fix mandatory fields, or retry with ?force=1 to bypass (audit-logged).",
        },
    )


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
    # Header row: brand banner + Vasu identity
    story.append(Paragraph("VASU INFOSEC", title_style))
    story.append(Paragraph(VASU_TAGLINE, tag_style))

    # Vasu identity strip (legal name + GSTIN + PAN + state)
    identity_bits = [f"<b>{VASU_LEGAL_NAME}</b>"]
    if VASU_GSTIN: identity_bits.append(f"GSTIN: {VASU_GSTIN}")
    if VASU_PAN: identity_bits.append(f"PAN: {VASU_PAN}")
    if VASU_STATE: identity_bits.append(f"State: {VASU_STATE} ({VASU_STATE_CODE})")
    story.append(Paragraph("  ·  ".join(identity_bits),
                           ParagraphStyle('id', parent=styles['Normal'], fontSize=8,
                                          textColor=colors.HexColor('#333'), spaceAfter=2)))
    story.append(Paragraph(VASU_ADDR_FULL,
                           ParagraphStyle('id2', parent=styles['Normal'], fontSize=8,
                                          textColor=colors.HexColor('#555'), spaceAfter=6)))

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
                 force: Optional[int] = 0,
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
    po_mrf_nums: List[str] = []
    for mid in po.get("mrf_refs") or []:
        m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "mrf_number": 1})
        if m: po_mrf_nums.append(m["mrf_number"])

    # Customer snapshot (fall back to project's customer)
    cid = po.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    # Validate mandatory data
    missing, warnings = _validate_po_for_export(po, vendor, cust, project, "pdf")
    if missing and not force:
        raise _validation_error(missing, warnings, "pdf")

    # Enrich each PO item with MAT/VAR/HSN
    enriched: List[dict] = []
    for it in po.get("items", []):
        info = await _resolve_material_info(it)
        row = dict(it)
        row.update(info)
        enriched.append(row)

    # Resolve customer PO reference (latest active CPO on the customer)
    cpo_ref = ""
    if cust and cust.get("customer_id"):
        cpos = await db.customers.find_one({"customer_id": cust["customer_id"]},
                                            {"_id": 0, "pos": 1})
        if cpos and isinstance(cpos.get("pos"), list) and cpos["pos"]:
            active = [p for p in cpos["pos"] if p.get("active", True)]
            active.sort(key=lambda p: p.get("po_date") or "", reverse=True)
            if active:
                cpo_ref = f"{active[0].get('po_number','')} dt {active[0].get('po_date','')}".strip()

    # Determine intra-state for CGST/SGST vs IGST
    intra = _is_intra_state((vendor or {}).get("address") or VASU_STATE)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    extra_ref_parts = []
    if po_mrf_nums:
        extra_ref_parts.append("MRF: " + ", ".join(po_mrf_nums))
    if cpo_ref:
        extra_ref_parts.append("Customer PO: " + cpo_ref)
    if po.get("vendor_quotation"):
        extra_ref_parts.append("Vendor Quote: " + str(po["vendor_quotation"]))
    story = _pdf_story("PURCHASE ORDER", po["po_number"], po["date"], project, cust, vendor,
                       extra_ref="  ·  ".join(extra_ref_parts))

    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, leading=10)
    smallb = ParagraphStyle('sb', parent=styles['Normal'], fontSize=8, leading=10,
                            fontName="Helvetica-Bold")

    # Items table with MAT/VAR/HSN/Make/Model + GST breakdown
    header = ["#", "MAT / VAR", "Description", "Make / Model", "HSN", "Unit",
              "Qty", "Rate", "Disc", "Taxable", "GST %", "Total"]
    data = [[Paragraph(h, smallb) for h in header]]
    subtotal_taxable = 0.0
    total_cgst = total_sgst = total_igst = 0.0
    for idx, it in enumerate(enriched, 1):
        qty = float(it.get("qty") or 0)
        rate = float(it.get("rate") or 0)
        disc = float(it.get("discount") or 0)
        gst_pct = float(it.get("gst") or it.get("gst_pct") or 0)
        taxable = qty * rate - disc
        cgst, sgst, igst = _split_gst_amt(taxable, gst_pct, intra)
        line_total = round(taxable + cgst + sgst + igst, 2)
        subtotal_taxable += taxable
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst
        mat_var = ((it.get("material_uid") or "-") + "\n" +
                   (it.get("variant_uid") or "-"))
        make_model = ((it.get("make") or "-") + "\n" +
                      (it.get("model") or "-"))
        data.append([
            Paragraph(str(idx), small),
            Paragraph(mat_var, small),
            Paragraph((it.get("description") or "")[:80], small),
            Paragraph(make_model, small),
            Paragraph(it.get("hsn_code") or "—", small),
            Paragraph(it.get("unit") or "", small),
            Paragraph(f"{qty:g}", small),
            Paragraph(f"{rate:,.2f}", small),
            Paragraph(f"{disc:,.2f}" if disc else "—", small),
            Paragraph(f"{taxable:,.2f}", small),
            Paragraph(f"{gst_pct:g}%", small),
            Paragraph(f"{line_total:,.2f}", small),
        ])
    tbl = Table(data, colWidths=[16, 52, 130, 56, 40, 24, 26, 40, 32, 46, 26, 44], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor('#B7BEC9')),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
        ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))

    # Tax summary block
    freight = float(po.get('freight') or 0)
    other = float(po.get('other_charges') or 0)
    grand = round(subtotal_taxable + total_cgst + total_sgst + total_igst + freight + other, 2)
    sum_rows = [
        [Paragraph("<b>Taxable Value</b>", small), Paragraph(f"₹ {subtotal_taxable:,.2f}", small)],
    ]
    if intra:
        sum_rows.append([Paragraph("CGST", small), Paragraph(f"₹ {total_cgst:,.2f}", small)])
        sum_rows.append([Paragraph("SGST", small), Paragraph(f"₹ {total_sgst:,.2f}", small)])
    else:
        sum_rows.append([Paragraph("IGST", small), Paragraph(f"₹ {total_igst:,.2f}", small)])
    sum_rows.append([Paragraph("Freight", small), Paragraph(f"₹ {freight:,.2f}", small)])
    sum_rows.append([Paragraph("Other Charges", small), Paragraph(f"₹ {other:,.2f}", small)])
    sum_rows.append([Paragraph("<b>Grand Total</b>", smallb),
                     Paragraph(f"<b>₹ {grand:,.2f}</b>", smallb)])
    sum_tbl = Table(sum_rows, colWidths=[380, 130])
    sum_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor('#D5D8DE')),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor('#EEF2FF')),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1, 10))

    # Terms & Authorisation block
    story.append(Paragraph(f"<b>Delivery Schedule:</b> {po.get('delivery_schedule','—') or '—'}", small))
    story.append(Paragraph(f"<b>Payment Terms:</b> {po.get('payment_terms','—') or '—'}", small))
    story.append(Paragraph(f"<b>Warranty:</b> {po.get('warranty_terms','—') or '—'}", small))
    if po.get("vendor_quotation"):
        story.append(Paragraph(f"<b>Vendor Quotation Ref:</b> {po['vendor_quotation']}", small))
    story.append(Spacer(1, 6))

    # Authorised signatories — from approval history (GM/Director) + explicit signatory
    signers: List[str] = []
    for h in (po.get("approval_history") or []):
        if (h.get("action") or "").lower() == "approve":
            role = (h.get("user_role") or "").upper()
            nm = h.get("user_name") or ""
            ts = (h.get("timestamp") or "")[:10]
            signers.append(f"{nm} ({role}) · {ts}")
    if po.get("authorised_signatory"):
        signers.append(str(po["authorised_signatory"]))
    if not signers:
        signers.append("For Vasu Infosec Pvt Ltd — Authorised Signatory")
    story.append(Paragraph("<b>Authorisation</b>", smallb))
    for s in signers:
        story.append(Paragraph(f"• {s}", small))

    # Warnings block (soft — printed at bottom)
    if warnings:
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"<font color='#B45309'><b>Advisory:</b> Optional fields missing — {', '.join(warnings[:8])}"
            + ("…" if len(warnings) > 8 else "") + "</font>", small))

    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    await _log_export(u, "po", po_id, "pdf", po["po_number"],
                      {"warnings": warnings, "forced": bool(force and missing)})
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

async def _po_excel_workbook(pos_list: List[dict], single: bool = False):
    """Build a rich per-line PO Excel workbook. Reused by bulk & single exports."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PO Line Items"
    headers = [
        "PO#", "PO Date", "Status", "Customer ID", "Customer Name", "Customer GSTIN",
        "Project Code", "Project Name", "Site",
        "Vendor Name", "Vendor GSTIN", "Vendor Address",
        "MRF Refs", "Customer PO Ref", "Vendor Quote",
        "Line #", "MAT UID", "VAR UID", "Description", "Make", "Model",
        "HSN/SAC", "Unit", "Qty", "Rate", "Discount",
        "Taxable Value", "GST %", "CGST", "SGST", "IGST", "Line Total",
        "Freight (PO)", "Other Charges (PO)", "PO Grand Total",
        "Delivery Schedule", "Payment Terms", "Warranty",
        "Authorised Signatory", "Approved By (history)",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    # Preload lookups
    vend_map = {v["vendor_id"]: v for v in await db.vendors.find({}, {"_id": 0}).to_list(2000)}
    proj_map = {p["project_id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    cust_map = {}
    for c in await db.customers.find({}, {"_id": 0}).to_list(500):
        cust_map[c["customer_id"]] = c
    # Preload MRF numbers
    mrf_ids = set()
    for p in pos_list:
        for mid in p.get("mrf_refs") or []:
            mrf_ids.add(mid)
    mrf_num_map = {}
    if mrf_ids:
        for m in await db.mrfs.find({"mrf_id": {"$in": list(mrf_ids)}},
                                     {"_id": 0, "mrf_id": 1, "mrf_number": 1}).to_list(2000):
            mrf_num_map[m["mrf_id"]] = m.get("mrf_number", "")

    for p in pos_list:
        vend = vend_map.get(p.get("vendor_id")) or {}
        proj = proj_map.get(p.get("project_id")) or {}
        cust = cust_map.get(p.get("customer_id")) or {}
        intra = _is_intra_state(vend.get("address") or VASU_STATE)
        pdate = p["date"].strftime("%Y-%m-%d") if isinstance(p.get("date"), datetime) else str(p.get("date", ""))[:10]
        mrf_refs = ", ".join(sorted({mrf_num_map.get(x, x) for x in (p.get("mrf_refs") or [])}))
        cpo_ref = ""
        if cust.get("customer_id"):
            cpos = cust.get("pos") or []
            active = sorted([x for x in cpos if x.get("active", True)],
                            key=lambda x: x.get("po_date") or "", reverse=True)
            if active:
                cpo_ref = f"{active[0].get('po_number','')} dt {active[0].get('po_date','')}"
        signers = "; ".join([
            f"{h.get('user_name','')}({(h.get('user_role') or '').upper()})"
            for h in (p.get("approval_history") or [])
            if (h.get("action") or "").lower() == "approve"
        ]) or ""
        for idx, it in enumerate(p.get("items") or [], 1):
            info = await _resolve_material_info(it)
            qty = float(it.get("qty") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst_pct = float(it.get("gst") or 0) or info.get("gst_pct") or 0
            taxable = round(qty * rate - disc, 2)
            cgst, sgst, igst = _split_gst_amt(taxable, gst_pct, intra)
            line_total = round(taxable + cgst + sgst + igst, 2)
            ws.append([
                _safe_cell(p.get("po_number", "")), _safe_cell(pdate),
                _safe_cell(p.get("status", "")),
                _safe_cell(cust.get("customer_id") or p.get("customer_id") or ""),
                _safe_cell(cust.get("name") or p.get("customer_name") or ""),
                _safe_cell(cust.get("gstin") or ""),
                _safe_cell(proj.get("code") or ""), _safe_cell(proj.get("name") or ""),
                _safe_cell(p.get("delivery_site") or proj.get("site") or ""),
                _safe_cell(vend.get("name") or ""),
                _safe_cell(vend.get("gstin") or ""),
                _safe_cell(vend.get("address") or ""),
                _safe_cell(mrf_refs), _safe_cell(cpo_ref),
                _safe_cell(p.get("vendor_quotation") or ""),
                idx,
                _safe_cell(info.get("material_uid") or ""),
                _safe_cell(info.get("variant_uid") or ""),
                _safe_cell(it.get("description") or ""),
                _safe_cell(info.get("make") or ""), _safe_cell(info.get("model") or ""),
                _safe_cell(info.get("hsn_code") or ""),
                _safe_cell(it.get("unit") or ""),
                qty, rate, disc,
                taxable, gst_pct, cgst, sgst, igst, line_total,
                float(p.get("freight") or 0),
                float(p.get("other_charges") or 0),
                float(p.get("total") or 0),
                _safe_cell(p.get("delivery_schedule") or ""),
                _safe_cell(p.get("payment_terms") or ""),
                _safe_cell(p.get("warranty_terms") or ""),
                _safe_cell(p.get("authorised_signatory") or ""),
                _safe_cell(signers),
            ])

    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 30))
    return wb


async def _po_tally_workbook(pos_list: List[dict]):
    """Build a Tally-compatible Purchase-voucher workbook for one or many POs."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Voucher"
    headers = [
        "Voucher Date", "Voucher Type", "Voucher No", "Reference No", "Reference Date",
        "Company GSTIN", "Company State", "Company State Code",
        "Party Ledger", "Party GSTIN", "Party State",
        "Customer ID", "Customer Name", "Customer GSTIN",
        "Project Code",
        "MAT UID", "VAR UID", "Item Name", "Make", "Model",
        "HSN/SAC", "Unit", "Quantity", "Rate", "Discount",
        "Taxable Value", "GST Rate %", "CGST", "SGST", "IGST",
        "Line Total", "Narration",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    vend_map = {v["vendor_id"]: v for v in await db.vendors.find({}, {"_id": 0}).to_list(2000)}
    proj_map = {p["project_id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    cust_map = {c["customer_id"]: c for c in await db.customers.find({}, {"_id": 0}).to_list(500)}

    for p in pos_list:
        vend = vend_map.get(p.get("vendor_id")) or {}
        proj = proj_map.get(p.get("project_id")) or {}
        cust = cust_map.get(p.get("customer_id")) or {}
        intra = _is_intra_state(vend.get("address") or VASU_STATE)
        vdate = p["date"].strftime("%d-%m-%Y") if isinstance(p.get("date"), datetime) else str(p.get("date"))[:10]
        for it in p.get("items", []):
            info = await _resolve_material_info(it)
            qty = float(it.get("qty") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst_pct = float(it.get("gst") or 0) or info.get("gst_pct") or 0
            taxable = round(qty * rate - disc, 2)
            cgst, sgst, igst = _split_gst_amt(taxable, gst_pct, intra)
            line_total = round(taxable + cgst + sgst + igst, 2)
            narration = f"PO {p.get('po_number','')} · Project {proj.get('code','')} · Customer {cust.get('customer_id','')}"
            ws.append([
                _safe_cell(vdate), _safe_cell("Purchase"), _safe_cell(p.get("po_number", "")),
                "", "",
                _safe_cell(VASU_GSTIN), _safe_cell(VASU_STATE), _safe_cell(VASU_STATE_CODE),
                _safe_cell(vend.get("name", "")),
                _safe_cell(vend.get("gstin", "")),
                _safe_cell((vend.get("address", "") or "")[:40]),
                _safe_cell(cust.get("customer_id", "")),
                _safe_cell(cust.get("name", "")),
                _safe_cell(cust.get("gstin", "")),
                _safe_cell(proj.get("code", "")),
                _safe_cell(info.get("material_uid") or ""),
                _safe_cell(info.get("variant_uid") or ""),
                _safe_cell(it.get("description", "")),
                _safe_cell(info.get("make") or ""), _safe_cell(info.get("model") or ""),
                _safe_cell(info.get("hsn_code") or ""),
                _safe_cell(it.get("unit", "")),
                qty, rate, disc,
                taxable, gst_pct, cgst, sgst, igst,
                line_total, _safe_cell(narration),
            ])

    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    return wb


async def _mrf_pdf_bytes(mrf: dict, project: dict, customer: Optional[dict]) -> bytes:
    """Branded MRF PDF (Material Requisition Form)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    mdate = mrf.get("date")
    extra = f"Requested by: {mrf.get('requesting_person','')}  ·  System: {mrf.get('system_category','')}"
    if mrf.get("required_by"):
        extra += f"  ·  Required by: {mrf['required_by']}"
    story = _pdf_story("MATERIAL REQUISITION FORM", mrf.get("mrf_number", ""),
                       mdate, project, customer, extra_ref=extra)
    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, leading=10)
    smallb = ParagraphStyle('sb', parent=styles['Normal'], fontSize=8, leading=10,
                            fontName="Helvetica-Bold")

    header = ["#", "MAT / VAR", "Description", "Make / Model", "Unit",
              "Qty Req.", "Qty Appr.", "Priority", "Status", "Purpose"]
    data = [[Paragraph(h, smallb) for h in header]]
    for idx, it in enumerate(mrf.get("items") or [], 1):
        info = await _resolve_material_info(it)
        mv = ((info.get("material_uid") or "-") + "\n" + (info.get("variant_uid") or "-"))
        mkmd = ((info.get("make") or it.get("make") or "-") + "\n" +
                (info.get("model") or it.get("model") or "-"))
        data.append([
            Paragraph(str(idx), small),
            Paragraph(mv, small),
            Paragraph((it.get("description") or "")[:70], small),
            Paragraph(mkmd, small),
            Paragraph(it.get("unit") or "", small),
            Paragraph(f"{float(it.get('qty_requested') or 0):g}", small),
            Paragraph(f"{float(it.get('qty_approved') or 0):g}", small),
            Paragraph((it.get("priority") or "normal").upper(), small),
            Paragraph((it.get("status") or "pending").upper(), small),
            Paragraph((it.get("purpose") or "-")[:40], small),
        ])
    tbl = Table(data, colWidths=[16, 52, 130, 60, 26, 38, 38, 36, 44, 76], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor('#B7BEC9')),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    if mrf.get("remarks"):
        story.append(Paragraph(f"<b>Remarks:</b> {mrf['remarks']}", small))
    story.append(Paragraph(f"<b>Status:</b> {(mrf.get('status') or 'draft').upper()}", small))
    story.append(Spacer(1, 6))
    # Approval history
    hist = mrf.get("approval_history") or []
    if hist:
        story.append(Paragraph("<b>Approval Trail</b>", smallb))
        for h in hist:
            ts = (h.get("timestamp") or "")[:16].replace("T", " ")
            story.append(Paragraph(
                f"• {h.get('user_name','')} ({(h.get('user_role') or '').upper()}) — "
                f"{(h.get('action') or '').upper()} at {ts}"
                + (f" — “{h['comment']}”" if h.get('comment') else ""), small))
    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    return buf.read()


@api.get("/export/mrf")
async def export_mrf(token: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "pm", "gm"):
        raise HTTPException(403, "Not allowed")
    mrfs = await db.mrfs.find({"deleted": False}, {"_id": 0}).to_list(2000)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MRFs"
    headers = [
        "MRF#", "Date", "Status", "Customer ID", "Customer Name",
        "Project", "Site", "Requester", "System",
        "Line#", "MAT UID", "VAR UID", "Description", "Make", "Model",
        "Unit", "Qty Requested", "Qty Approved", "Qty Ordered", "Qty Received",
        "Priority", "Item Status", "Billing Status", "Remarks",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    proj_map = {p["project_id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    for m in mrfs:
        proj = proj_map.get(m.get("project_id")) or {}
        for idx, it in enumerate(m.get("items") or [], 1):
            info = await _resolve_material_info(it)
            ws.append([
                _safe_cell(m.get("mrf_number", "")),
                m["date"].strftime("%Y-%m-%d") if isinstance(m.get("date"), datetime) else str(m.get("date", "")),
                _safe_cell(m.get("status", "")),
                _safe_cell(m.get("customer_id") or ""),
                _safe_cell(m.get("customer_name") or ""),
                _safe_cell(proj.get("code") or m.get("project_id", "")),
                _safe_cell(m.get("site", "")),
                _safe_cell(m.get("requesting_person", "")),
                _safe_cell(m.get("system_category", "")),
                idx,
                _safe_cell(info.get("material_uid") or ""),
                _safe_cell(info.get("variant_uid") or ""),
                _safe_cell(it.get("description", "")),
                _safe_cell(info.get("make") or ""),
                _safe_cell(info.get("model") or ""),
                _safe_cell(it.get("unit", "")),
                float(it.get("qty_requested") or 0),
                float(it.get("qty_approved") or 0),
                float(it.get("qty_ordered") or 0),
                float(it.get("qty_received") or 0),
                _safe_cell((it.get("priority") or "normal")),
                _safe_cell(it.get("status", "")),
                _safe_cell(it.get("billing_status", "")),
                _safe_cell(it.get("remarks", "")),
            ])
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    await _log_export(u, "mrf", "bulk", "excel", f"count={len(mrfs)}")
    return _excel_response(wb, "mrf_export.xlsx")


@api.get("/export/po")
async def export_po(token: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "gm", "pm"):
        raise HTTPException(403, "Not allowed")
    pos = await db.pos.find({"deleted": False}, {"_id": 0}).sort("date", -1).to_list(2000)
    wb = await _po_excel_workbook(pos, single=False)
    await _log_export(u, "po", "bulk", "excel", f"count={len(pos)}")
    return _excel_response(wb, "po_export.xlsx")


@api.get("/export/tally")
async def export_tally(kind: str = "purchase", token: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    """Bulk Tally purchase-voucher rows. kind=purchase | invoice."""
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/director/admin")
    kind = (kind or "purchase").lower()
    if kind not in ("purchase", "invoice"):
        raise HTTPException(400, "kind must be 'purchase' or 'invoice'")

    if kind == "purchase":
        pos = await db.pos.find({"deleted": False}, {"_id": 0}).sort("date", 1).to_list(2000)
        wb = await _po_tally_workbook(pos)
        fname = "tally_purchase_voucher.xlsx"
        await _log_export(u, "tally", "bulk_purchase", "tally", f"count={len(pos)}")
        return _excel_response(wb, fname)

    # invoice-based purchase voucher (vendor invoices)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Voucher"
    headers = [
        "Voucher Date", "Voucher Type", "Voucher No", "Reference No", "Reference Date",
        "Company GSTIN", "Company State",
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
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    vendors = {v["vendor_id"]: v for v in await db.vendors.find({}, {"_id": 0}).to_list(1000)}
    invs = await db.invoices.find({}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    for inv in invs:
        vend = vendors.get(inv.get("vendor_id")) or {}
        vdate = str(inv.get("invoice_date", ""))[:10]
        intra = _is_intra_state(vend.get("address") or VASU_STATE)
        for it in inv.get("items", []):
            info = await _resolve_material_info(it)
            qty = float(it.get("qty") or 0)
            rate = float(it.get("rate") or 0)
            disc = float(it.get("discount") or 0)
            gst_pct = float(it.get("gst") or 0) or info.get("gst_pct") or 0
            taxable = round(qty * rate - disc, 2)
            cgst, sgst, igst = _split_gst_amt(taxable, gst_pct, intra)
            line_total = round(taxable + cgst + sgst + igst, 2)
            ws.append([
                _safe_cell(vdate), _safe_cell("Purchase"), _safe_cell(inv["invoice_number"]),
                _safe_cell(inv.get("vendor_invoice_number", "")), _safe_cell(vdate),
                _safe_cell(VASU_GSTIN), _safe_cell(VASU_STATE),
                _safe_cell(vend.get("name", "")),
                _safe_cell(vend.get("gstin", "")),
                _safe_cell((vend.get("address", "") or "")[:40]),
                _safe_cell(inv.get("customer_id", "")),
                _safe_cell(inv.get("customer_name", "")),
                _safe_cell(it.get("description", "")),
                _safe_cell(info.get("hsn_code") or ""),
                _safe_cell(it.get("unit", "")),
                qty, rate, disc,
                taxable, gst_pct, cgst, sgst, igst,
                line_total,
                _safe_cell(f"Vendor Inv {inv.get('vendor_invoice_number','')} · PO {inv.get('po_number','')}"),
            ])
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    await _log_export(u, "tally", "bulk_invoice", "tally", f"count={len(invs)}")
    return _excel_response(wb, "tally_invoice_voucher.xlsx")


# ---------------------- Unified single-record export dispatchers ----------------------
_ALLOWED_PO_FORMATS = ("pdf", "excel", "tally")
_ALLOWED_MRF_FORMATS = ("pdf", "excel")


@api.get("/po/{po_id}/export")
async def po_export_dispatch(po_id: str,
                             format: str = "pdf",
                             force: Optional[int] = 0,
                             token: Optional[str] = None,
                             authorization: Optional[str] = Header(None)):
    """Unified download endpoint for a single PO. format = pdf | excel | tally."""
    fmt = (format or "pdf").lower()
    if fmt not in _ALLOWED_PO_FORMATS:
        raise HTTPException(400, f"format must be one of {_ALLOWED_PO_FORMATS}")
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")
    await _check_po_access(u, po)

    if fmt == "pdf":
        # Delegate to enriched po_pdf which validates internally
        return await po_pdf(po_id, token=token, force=force, authorization=authorization)

    # Excel / Tally single-record path — validate first
    vendor = await db.vendors.find_one({"vendor_id": po["vendor_id"]}, {"_id": 0}) or {}
    project = await db.projects.find_one({"project_id": po["project_id"]}, {"_id": 0}) or {}
    cid = po.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None
    missing, warnings = _validate_po_for_export(po, vendor, cust, project, fmt)
    if missing and not force:
        raise _validation_error(missing, warnings, fmt)

    if fmt == "excel":
        wb = await _po_excel_workbook([po], single=True)
        await _log_export(u, "po", po_id, "excel", po["po_number"],
                          {"warnings": warnings, "forced": bool(force and missing)})
        return _excel_response(wb, f"{po['po_number'].replace('/', '_')}_details.xlsx")

    # tally
    wb = await _po_tally_workbook([po])
    await _log_export(u, "po", po_id, "tally", po["po_number"],
                      {"warnings": warnings, "forced": bool(force and missing)})
    return _excel_response(wb, f"{po['po_number'].replace('/', '_')}_tally.xlsx")


@api.get("/mrf/{mrf_id}/pdf")
async def mrf_pdf_route(mrf_id: str, token: Optional[str] = None,
                        force: Optional[int] = 0,
                        authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    mrf = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    await _check_mrf_access(u, mrf)
    project = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0}) or {}
    cid = mrf.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None
    missing, warnings = _validate_mrf_for_export(mrf, project, cust, "pdf")
    if missing and not force:
        raise _validation_error(missing, warnings, "pdf")
    pdf_bytes = await _mrf_pdf_bytes(mrf, project, cust)
    await _log_export(u, "mrf", mrf_id, "pdf", mrf.get("mrf_number", ""),
                      {"warnings": warnings, "forced": bool(force and missing)})
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{mrf["mrf_number"].replace("/","_")}.pdf"'})


@api.get("/mrf/{mrf_id}/export")
async def mrf_export_dispatch(mrf_id: str,
                              format: str = "pdf",
                              force: Optional[int] = 0,
                              token: Optional[str] = None,
                              authorization: Optional[str] = Header(None)):
    fmt = (format or "pdf").lower()
    if fmt not in _ALLOWED_MRF_FORMATS:
        raise HTTPException(400, f"format must be one of {_ALLOWED_MRF_FORMATS}")
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    mrf = await db.mrfs.find_one({"mrf_id": mrf_id}, {"_id": 0})
    if not mrf:
        raise HTTPException(404, "MRF not found")
    await _check_mrf_access(u, mrf)

    if fmt == "pdf":
        return await mrf_pdf_route(mrf_id, token=token, force=force, authorization=authorization)

    # Excel single-MRF export
    project = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0}) or {}
    cid = mrf.get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None
    missing, warnings = _validate_mrf_for_export(mrf, project, cust, "excel")
    if missing and not force:
        raise _validation_error(missing, warnings, "excel")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MRF Line Items"
    headers = [
        "MRF#", "Date", "Status", "Customer ID", "Customer Name",
        "Project", "Site", "Requester", "System",
        "Line#", "MAT UID", "VAR UID", "Description", "Make", "Model",
        "Unit", "Qty Requested", "Qty Approved", "Qty Ordered", "Qty Received",
        "Priority", "Item Status", "Billing Status", "Purpose", "Remarks",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for idx, it in enumerate(mrf.get("items") or [], 1):
        info = await _resolve_material_info(it)
        ws.append([
            _safe_cell(mrf.get("mrf_number", "")),
            mrf["date"].strftime("%Y-%m-%d") if isinstance(mrf.get("date"), datetime) else str(mrf.get("date", "")),
            _safe_cell(mrf.get("status", "")),
            _safe_cell(mrf.get("customer_id") or ""),
            _safe_cell(mrf.get("customer_name") or ""),
            _safe_cell(project.get("code") or mrf.get("project_id", "")),
            _safe_cell(mrf.get("site", "")),
            _safe_cell(mrf.get("requesting_person", "")),
            _safe_cell(mrf.get("system_category", "")),
            idx,
            _safe_cell(info.get("material_uid") or ""),
            _safe_cell(info.get("variant_uid") or ""),
            _safe_cell(it.get("description", "")),
            _safe_cell(info.get("make") or ""),
            _safe_cell(info.get("model") or ""),
            _safe_cell(it.get("unit", "")),
            float(it.get("qty_requested") or 0),
            float(it.get("qty_approved") or 0),
            float(it.get("qty_ordered") or 0),
            float(it.get("qty_received") or 0),
            _safe_cell((it.get("priority") or "normal")),
            _safe_cell(it.get("status", "")),
            _safe_cell(it.get("billing_status", "")),
            _safe_cell(it.get("purpose", "")),
            _safe_cell(it.get("remarks", "")),
        ])
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    await _log_export(u, "mrf", mrf_id, "excel", mrf.get("mrf_number", ""),
                      {"warnings": warnings, "forced": bool(force and missing)})
    return _excel_response(wb, f"{mrf['mrf_number'].replace('/', '_')}_details.xlsx")


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

@api.post("/grn/{grn_id}/approve")
async def approve_grn(grn_id: str, body: Dict[str, Any] = Body(default={}),
                      authorization: Optional[str] = Header(None)):
    """Admin/Accounts (or Director) approves or rejects a GRN."""
    u = await get_current_user(authorization)
    if u.role not in GRN_APPROVER_ROLES:
        raise HTTPException(403, "Only admin/accounts or director can approve GRN")
    grn = await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})
    if not grn: raise HTTPException(404, "GRN not found")
    action = (body.get("action") or "approve").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    current = grn.get("status") or "pending_approval"
    if current not in ("pending_approval", "rejected"):
        raise HTTPException(400, f"Cannot {action}: GRN is '{current}'")
    new_status = "approved" if action == "approve" else "rejected"
    hist = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": body.get("comment") or "",
        "timestamp": now_utc().isoformat(),
    }
    await db.grns.update_one(
        {"grn_id": grn_id},
        {"$set": {"status": new_status},
         "$push": {"approval_history": hist}},
    )
    await audit("grn", grn_id, f"grn_{action}", u,
                {"grn_number": grn.get("grn_number"),
                 "record_number": grn.get("grn_number"),
                 "old_value": {"status": current},
                 "new_value": {"status": new_status},
                 "reason": body.get("comment") or ""})
    return await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})


@api.get("/grn/{grn_id}")
async def get_grn(grn_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    grn = await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})
    if not grn: raise HTTPException(404, "GRN not found")
    po = await db.pos.find_one({"po_id": grn.get("po_id")}, {"_id": 0})
    if po:
        await _check_po_access(u, po)
    elif u.role not in ("purchase", "director", "admin", "store", "gm"):
        raise HTTPException(403, "Not allowed")
    return grn


@api.get("/grn/{grn_id}/pdf")
async def grn_pdf(grn_id: str, token: Optional[str] = None,
                  force: Optional[int] = 0,
                  authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    grn = await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})
    if not grn:
        raise HTTPException(404, "GRN not found")
    po = await db.pos.find_one({"po_id": grn.get("po_id")}, {"_id": 0})
    if po:
        await _check_po_access(u, po)
    elif u.role not in ("purchase", "director", "admin", "store"):
        raise HTTPException(403, "Not allowed")
    vendor = await db.vendors.find_one({"vendor_id": grn.get("vendor_id")}, {"_id": 0}) or {}
    project = await db.projects.find_one({"project_id": grn.get("project_id")}, {"_id": 0}) or {}
    grn_mrf_nums = []
    for mid in grn.get("mrf_refs") or []:
        m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "mrf_number": 1})
        if m: grn_mrf_nums.append(m["mrf_number"])

    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, leading=10)
    smallb = ParagraphStyle('sb', parent=styles['Normal'], fontSize=8, leading=10,
                            fontName="Helvetica-Bold")

    # Resolve customer from PO snapshot / project
    cid = (po or {}).get("customer_id") or project.get("customer_id")
    cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0}) if cid else None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    story = _pdf_story("GOODS RECEIVED NOTE", grn["grn_number"],
                       grn.get("date"), project, cust, vendor,
                       extra_ref=f"PO {grn.get('po_number','')}  ·  MRF {', '.join(grn_mrf_nums)}")

    story.append(Paragraph(f"<b>Received by:</b> {grn.get('received_by_name','')}", small))
    if grn.get("vehicle_no"):
        story.append(Paragraph(f"<b>Vehicle:</b> {grn['vehicle_no']}  ·  "
                               f"<b>Driver:</b> {grn.get('driver_name','')}", small))
    if grn.get("vendor_dc_ref"):
        story.append(Paragraph(f"<b>Vendor DC/Invoice ref:</b> {grn['vendor_dc_ref']}", small))
    story.append(Spacer(1, 6))

    header = ["#", "MAT / VAR", "Description", "Make / Model", "HSN", "Unit", "Qty Received", "Remarks"]
    data = [[Paragraph(h, smallb) for h in header]]
    for idx, it in enumerate(grn.get("items", []), 1):
        info = await _resolve_material_info(it)
        mv = ((info.get("material_uid") or "-") + "\n" + (info.get("variant_uid") or "-"))
        mm2 = ((info.get("make") or "-") + "\n" + (info.get("model") or "-"))
        data.append([
            Paragraph(str(idx), small),
            Paragraph(mv, small),
            Paragraph((it.get("description") or "")[:80], small),
            Paragraph(mm2, small),
            Paragraph(info.get("hsn_code") or "—", small),
            Paragraph(it.get("unit", ""), small),
            Paragraph(f"{float(it.get('qty') or 0):g}", small),
            Paragraph((it.get("remarks") or "")[:40], small),
        ])
    tbl = Table(data, colWidths=[16, 56, 150, 68, 44, 30, 52, 88], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor('#B7BEC9')),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    if grn.get("remarks"):
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Remarks:</b> {grn['remarks']}", small))
    story += [
        Spacer(1, 30),
        Paragraph("_______________________________&nbsp;&nbsp;&nbsp;&nbsp;_______________________________", small),
        Paragraph("Received By&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Vendor Signature", small),
    ]
    doc.build(story, onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    await _log_export(u, "grn", grn_id, "pdf", grn["grn_number"])
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{grn["grn_number"].replace("/","_")}.pdf"'})


async def _grn_excel_workbook(grns: List[dict]) -> "openpyxl.Workbook":
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "GRN Line Items"
    headers = [
        "GRN#", "Date", "PO#", "MRF Refs", "Customer ID", "Customer Name",
        "Vendor Name", "Project Code", "Site",
        "Vehicle", "Driver", "Vendor DC/Inv Ref",
        "Line#", "MAT UID", "VAR UID", "Description", "Make", "Model", "HSN", "Unit",
        "Qty Received", "Remarks", "Received By",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    proj_map = {p["project_id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    vend_map = {v["vendor_id"]: v for v in await db.vendors.find({}, {"_id": 0}).to_list(2000)}
    cust_map = {c["customer_id"]: c for c in await db.customers.find({}, {"_id": 0}).to_list(500)}
    for g in grns:
        vend = vend_map.get(g.get("vendor_id")) or {}
        proj = proj_map.get(g.get("project_id")) or {}
        cust = cust_map.get(g.get("customer_id")) or {}
        mrfnums = ""
        if g.get("mrf_refs"):
            docs = await db.mrfs.find({"mrf_id": {"$in": g["mrf_refs"]}},
                                       {"_id": 0, "mrf_number": 1}).to_list(1000)
            mrfnums = ", ".join(sorted([m["mrf_number"] for m in docs]))
        gdate = g["date"].strftime("%Y-%m-%d") if isinstance(g.get("date"), datetime) else str(g.get("date", ""))[:10]
        for idx, it in enumerate(g.get("items") or [], 1):
            info = await _resolve_material_info(it)
            ws.append([
                _safe_cell(g.get("grn_number", "")), _safe_cell(gdate),
                _safe_cell(g.get("po_number", "")),
                _safe_cell(mrfnums),
                _safe_cell(cust.get("customer_id") or g.get("customer_id") or ""),
                _safe_cell(cust.get("name") or ""),
                _safe_cell(vend.get("name") or ""),
                _safe_cell(proj.get("code") or ""),
                _safe_cell(g.get("delivery_site") or proj.get("site") or ""),
                _safe_cell(g.get("vehicle_no") or ""),
                _safe_cell(g.get("driver_name") or ""),
                _safe_cell(g.get("vendor_dc_ref") or ""),
                idx,
                _safe_cell(info.get("material_uid") or ""),
                _safe_cell(info.get("variant_uid") or ""),
                _safe_cell(it.get("description") or ""),
                _safe_cell(info.get("make") or ""),
                _safe_cell(info.get("model") or ""),
                _safe_cell(info.get("hsn_code") or ""),
                _safe_cell(it.get("unit", "")),
                float(it.get("qty") or 0),
                _safe_cell(it.get("remarks") or ""),
                _safe_cell(g.get("received_by_name") or ""),
            ])
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    return wb


def _validate_grn_for_export(grn: dict, project: Optional[dict],
                             customer: Optional[dict], fmt: str) -> tuple:
    missing: List[str] = []
    warnings: List[str] = []
    if not grn.get("grn_number"):
        missing.append("GRN number")
    if not project:
        warnings.append("Project")
    if not (customer and customer.get("customer_id")):
        warnings.append("Customer ID (permanent)")
    items = grn.get("items") or []
    if not items:
        missing.append("At least one received line")
    for i, it in enumerate(items, 1):
        if not (it.get("description") or "").strip():
            missing.append(f"Item {i} description")
        if float(it.get("qty") or 0) <= 0:
            missing.append(f"Item {i} qty > 0")
    return missing, warnings


@api.get("/grn/{grn_id}/export")
async def grn_export_dispatch(grn_id: str,
                              format: str = "pdf",
                              force: Optional[int] = 0,
                              token: Optional[str] = None,
                              authorization: Optional[str] = Header(None)):
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "excel"):
        raise HTTPException(400, "format must be 'pdf' or 'excel'")
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    grn = await db.grns.find_one({"grn_id": grn_id}, {"_id": 0})
    if not grn:
        raise HTTPException(404, "GRN not found")
    po = await db.pos.find_one({"po_id": grn.get("po_id")}, {"_id": 0})
    if po:
        await _check_po_access(u, po)
    elif u.role not in ("purchase", "director", "admin", "store"):
        raise HTTPException(403, "Not allowed")

    if fmt == "pdf":
        return await grn_pdf(grn_id, token=token, force=force, authorization=authorization)

    project = await db.projects.find_one({"project_id": grn.get("project_id")}, {"_id": 0}) or {}
    cust = None
    cid = (po or {}).get("customer_id") or project.get("customer_id") or grn.get("customer_id")
    if cid:
        cust = await db.customers.find_one({"customer_id": cid}, {"_id": 0})
    missing, warnings = _validate_grn_for_export(grn, project, cust, fmt)
    if missing and not force:
        raise _validation_error(missing, warnings, fmt)
    wb = await _grn_excel_workbook([grn])
    await _log_export(u, "grn", grn_id, "excel", grn["grn_number"],
                      {"warnings": warnings, "forced": bool(force and missing)})
    return _excel_response(wb, f"{grn['grn_number'].replace('/', '_')}_details.xlsx")


@api.get("/export/grn")
async def export_grn(token: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "store", "pm", "gm"):
        raise HTTPException(403, "Not allowed")
    grns = await db.grns.find({"deleted": {"$ne": True}}, {"_id": 0}).sort("date", -1).to_list(2000)
    wb = await _grn_excel_workbook(grns)
    await _log_export(u, "grn", "bulk", "excel", f"count={len(grns)}")
    return _excel_response(wb, "grn_export.xlsx")


# ---------------------- Delivery Challan ----------------------
def _dc_pdf_story(dc: dict, project: dict, customer: Optional[dict],
                  vendor: Optional[dict]) -> list:
    styles = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, leading=10)
    smallb = ParagraphStyle('sb', parent=styles['Normal'], fontSize=8, leading=10,
                            fontName="Helvetica-Bold")
    ttl = "DELIVERY CHALLAN"
    if (dc.get("dc_type") or "").lower() == "inbound":
        ttl = "DELIVERY CHALLAN (Inbound)"
    story = _pdf_story(ttl, dc.get("dc_number", ""), dc.get("date"),
                       project, customer, vendor,
                       extra_ref=f"Type: {(dc.get('dc_type') or '').upper()}"
                                 + (f"  ·  PO {dc.get('po_id','')}" if dc.get("po_id") else ""))
    # Logistics block
    logistics = [
        f"<b>From:</b> {dc.get('from_location','—')}",
        f"<b>To:</b> {dc.get('to_location','—')}",
        f"<b>Dispatch Date:</b> {dc.get('dispatch_date','—')}",
        f"<b>Vehicle:</b> {dc.get('vehicle_no','—')}",
        f"<b>Driver:</b> {dc.get('driver_name','—')} ({dc.get('driver_contact','')})",
        f"<b>Transporter:</b> {dc.get('transporter','—')}",
    ]
    if dc.get("e_way_bill_no"):
        logistics.append(f"<b>E-Way Bill:</b> {dc['e_way_bill_no']}"
                          + (f" dt {dc['e_way_bill_date']}" if dc.get("e_way_bill_date") else ""))
    if dc.get("vendor_dc_ref"):
        logistics.append(f"<b>Vendor DC Ref:</b> {dc['vendor_dc_ref']}")
    for l in logistics:
        story.append(Paragraph(l, small))
    story.append(Spacer(1, 6))

    header = ["#", "MAT / VAR", "Description", "Make / Model", "Unit", "Qty", "Remarks"]
    data = [[Paragraph(h, smallb) for h in header]]
    for idx, it in enumerate(dc.get("items") or [], 1):
        mv = ((it.get("material_uid") or "-") + "\n" + (it.get("variant_uid") or "-"))
        mm2 = ((it.get("make") or "-") + "\n" + (it.get("model") or "-"))
        data.append([
            Paragraph(str(idx), small),
            Paragraph(mv, small),
            Paragraph((it.get("description") or "")[:80], small),
            Paragraph(mm2, small),
            Paragraph(it.get("unit") or "", small),
            Paragraph(f"{float(it.get('qty') or 0):g}", small),
            Paragraph((it.get("remarks") or "")[:60], small),
        ])
    tbl = Table(data, colWidths=[16, 60, 170, 74, 30, 44, 110], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), VASU_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor('#B7BEC9')),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
    ]))
    story.append(tbl)
    if dc.get("remarks"):
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Remarks:</b> {dc['remarks']}", small))
    # Declaration
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<i>This is a Delivery Challan, not a tax invoice. Material dispatched for "
        "project execution / job-work / return. Goods received in good condition unless "
        "recorded otherwise.</i>", small))
    story += [
        Spacer(1, 24),
        Paragraph(f"<b>Authorised Signatory</b> — {dc.get('authorised_signatory') or 'Vasu Infosec Pvt Ltd'}", small),
        Spacer(1, 20),
        Paragraph("Prepared By: __________________  &nbsp;&nbsp;&nbsp;  Driver Signature: __________________  &nbsp;&nbsp;&nbsp;  Receiver Signature: __________________", small),
    ]
    return story


async def _dc_excel_workbook(dcs: List[dict]) -> "openpyxl.Workbook":
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Delivery Challan"
    headers = [
        "DC#", "Date", "Type", "Status", "PO#", "GRN#", "Customer ID", "Customer Name",
        "Vendor Name", "Project Code", "From", "To", "Dispatch Date",
        "Vehicle", "Driver", "Driver Contact", "Transporter", "E-Way Bill", "E-Way Date",
        "Vendor DC Ref",
        "Line#", "MAT UID", "VAR UID", "Description", "Make", "Model", "Unit", "Qty",
        "Item Remarks", "DC Remarks", "Authorised Signatory",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    proj_map = {p["project_id"]: p for p in await db.projects.find({}, {"_id": 0}).to_list(500)}
    for dc in dcs:
        proj = proj_map.get(dc.get("project_id")) or {}
        ddate = dc["date"].strftime("%Y-%m-%d") if isinstance(dc.get("date"), datetime) else str(dc.get("date", ""))[:10]
        po = None
        if dc.get("po_id"):
            po = await db.pos.find_one({"po_id": dc["po_id"]}, {"_id": 0, "po_number": 1})
        grn = None
        if dc.get("grn_id"):
            grn = await db.grns.find_one({"grn_id": dc["grn_id"]}, {"_id": 0, "grn_number": 1})
        for idx, it in enumerate(dc.get("items") or [], 1):
            ws.append([
                _safe_cell(dc.get("dc_number", "")), _safe_cell(ddate),
                _safe_cell(dc.get("dc_type", "")),
                _safe_cell(dc.get("status", "")),
                _safe_cell((po or {}).get("po_number", "")),
                _safe_cell((grn or {}).get("grn_number", "")),
                _safe_cell(dc.get("customer_id", "")),
                _safe_cell(dc.get("customer_name", "")),
                _safe_cell(dc.get("vendor_name", "")),
                _safe_cell(proj.get("code", "")),
                _safe_cell(dc.get("from_location", "")),
                _safe_cell(dc.get("to_location", "")),
                _safe_cell(dc.get("dispatch_date", "")),
                _safe_cell(dc.get("vehicle_no", "")),
                _safe_cell(dc.get("driver_name", "")),
                _safe_cell(dc.get("driver_contact", "")),
                _safe_cell(dc.get("transporter", "")),
                _safe_cell(dc.get("e_way_bill_no", "")),
                _safe_cell(dc.get("e_way_bill_date", "")),
                _safe_cell(dc.get("vendor_dc_ref", "")),
                idx,
                _safe_cell(it.get("material_uid", "")),
                _safe_cell(it.get("variant_uid", "")),
                _safe_cell(it.get("description", "")),
                _safe_cell(it.get("make", "")),
                _safe_cell(it.get("model", "")),
                _safe_cell(it.get("unit", "")),
                float(it.get("qty") or 0),
                _safe_cell(it.get("remarks", "")),
                _safe_cell(dc.get("remarks", "")),
                _safe_cell(dc.get("authorised_signatory", "")),
            ])
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(12, min(len(h) + 2, 28))
    return wb


def _validate_dc_for_export(dc: dict, project: Optional[dict], fmt: str) -> tuple:
    missing: List[str] = []
    warnings: List[str] = []
    if not dc.get("dc_number"):
        missing.append("DC number")
    if not project:
        missing.append("Project")
    if not (dc.get("from_location") or "").strip():
        missing.append("From location")
    if not (dc.get("to_location") or "").strip():
        missing.append("To location")
    if not (dc.get("dispatch_date") or "").strip():
        missing.append("Dispatch date")
    if not (dc.get("items") or []):
        missing.append("At least one line item")
    if not (dc.get("vehicle_no") or "").strip():
        warnings.append("Vehicle number")
    if not (dc.get("driver_name") or "").strip():
        warnings.append("Driver name")
    for i, it in enumerate(dc.get("items") or [], 1):
        if not (it.get("description") or "").strip():
            missing.append(f"Item {i} description")
        if float(it.get("qty") or 0) <= 0:
            missing.append(f"Item {i} qty > 0")
    return missing, warnings


DC_ROLES_LEGACY_ORDER = {"purchase", "admin"}  # kept for reference

# Reset the primary DC_ROLES set (was rebuilt above; keeping single source of truth).


async def _check_dc_access(u: UserOut, dc: dict):
    # Project-scoped for pm/site_engineer; open for purchase/store/director/admin/gm
    if u.role in ("director", "admin", "purchase", "gm"):
        return
    if u.role == "store":
        return
    if u.role == "pm":
        proj = await db.projects.find_one({"project_id": dc.get("project_id")},
                                          {"_id": 0, "project_managers": 1})
        if proj and u.user_id in (proj.get("project_managers") or []):
            return
    if u.role == "site_engineer":
        proj = await db.projects.find_one({"project_id": dc.get("project_id")},
                                          {"_id": 0, "site_engineers": 1})
        if proj and u.user_id in (proj.get("site_engineers") or []):
            return
    raise HTTPException(403, "Not authorised for this DC")


@api.post("/dc")
async def create_dc(body: DCCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in DC_ROLES:
        raise HTTPException(403, "Not allowed to create DC")
    if not body.items:
        raise HTTPException(400, "At least one line item required")
    proj = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
    if not proj:
        raise HTTPException(404, "Project not found")
    # Access check for PM/SE
    if u.role == "pm" and u.user_id not in (proj.get("project_managers") or []):
        raise HTTPException(403, "Not a PM for this project")
    if u.role == "site_engineer" and u.user_id not in (proj.get("site_engineers") or []):
        raise HTTPException(403, "Not a Site Engineer for this project")

    cust_name = ""
    if body.customer_id:
        c = await db.customers.find_one({"customer_id": body.customer_id}, {"_id": 0, "name": 1})
        if c: cust_name = c.get("name") or ""
    vend_name = ""
    if body.vendor_id:
        v = await db.vendors.find_one({"vendor_id": body.vendor_id}, {"_id": 0, "name": 1})
        if v: vend_name = v.get("name") or ""
    dc_number = await next_dc_number()
    dc = DC(
        **body.model_dump(),
        dc_number=dc_number,
        customer_name=cust_name,
        vendor_name=vend_name,
        created_by=u.user_id,
    )
    await db.dcs.insert_one(dc.model_dump())
    await audit("dc", dc.dc_id, "create", u,
                {"dc_number": dc.dc_number,
                 "old_value": None,
                 "new_value": {"status": "issued", "dc_type": dc.dc_type,
                               "item_count": len(dc.items),
                               "project_id": dc.project_id,
                               "from_location": dc.from_location,
                               "to_location": dc.to_location}})
    return await db.dcs.find_one({"dc_id": dc.dc_id}, {"_id": 0})


@api.get("/dc")
async def list_dcs(project_id: Optional[str] = None,
                   status: Optional[str] = None,
                   dc_type: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": {"$ne": True}}
    if project_id: q["project_id"] = project_id
    if status: q["status"] = status
    if dc_type: q["dc_type"] = dc_type
    # Role-scoping
    if u.role == "pm":
        prjs = await db.projects.find({"project_managers": u.user_id},
                                       {"_id": 0, "project_id": 1}).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    elif u.role == "site_engineer":
        prjs = await db.projects.find({"site_engineers": u.user_id},
                                       {"_id": 0, "project_id": 1}).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    rows = await db.dcs.find(q, {"_id": 0}).sort("date", -1).to_list(500)
    return rows


@api.get("/dc/{dc_id}")
async def get_dc(dc_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    return dc


@api.put("/dc/{dc_id}")
async def update_dc(dc_id: str, body: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    if u.role not in DC_ROLES:
        raise HTTPException(403, "Not allowed")
    # Lock edits once approved (except Admin/Director can override via cancel)
    if dc.get("status") == "approved" and u.role not in ("admin", "director"):
        raise HTTPException(400, "DC is approved and locked; only admin/director can override")
    ALLOWED = {
        "status", "dispatch_date", "vehicle_no", "driver_name", "driver_contact",
        "transporter", "e_way_bill_no", "e_way_bill_date", "remarks",
        "authorised_signatory", "items", "from_location", "to_location", "vendor_dc_ref",
    }
    updates = {k: v for k, v in body.items() if k in ALLOWED and k != "reason"}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    # Prevent direct status manipulation via PUT; force use of /approve or /cancel
    if "status" in updates and updates["status"] in ("approved", "rejected", "cancelled"):
        if u.role not in ("admin", "director"):
            raise HTTPException(403, "Use /approve or /cancel to change protected status")
    old_snap = {k: dc.get(k) for k in updates.keys()}
    updates["updated_at"] = now_utc()
    await db.dcs.update_one({"dc_id": dc_id}, {"$set": updates})
    await audit("dc", dc_id, "edit", u,
                {"dc_number": dc.get("dc_number"),
                 "old_value": old_snap, "new_value": {k: v for k, v in updates.items() if k != "updated_at"},
                 "reason": body.get("reason") or ""})
    return await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})


@api.post("/dc/{dc_id}/approve")
async def approve_dc(dc_id: str, body: Dict[str, Any] = Body(default={}),
                     authorization: Optional[str] = Header(None)):
    """Admin/Accounts (or Director) approves or rejects a Delivery Challan."""
    u = await get_current_user(authorization)
    if u.role not in DC_APPROVER_ROLES:
        raise HTTPException(403, "Only admin/accounts or director can approve DC")
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    action = (body.get("action") or "approve").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    if dc.get("status") not in ("pending_approval", "rejected", "issued"):
        raise HTTPException(400, f"Cannot {action}: DC is '{dc.get('status')}'")
    new_status = "approved" if action == "approve" else "rejected"
    hist = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": body.get("comment") or "",
        "timestamp": now_utc().isoformat(),
    }
    await db.dcs.update_one(
        {"dc_id": dc_id},
        {"$set": {"status": new_status, "updated_at": now_utc()},
         "$push": {"approval_history": hist}},
    )
    await audit("dc", dc_id, f"dc_{action}", u,
                {"dc_number": dc.get("dc_number"),
                 "record_number": dc.get("dc_number"),
                 "old_value": {"status": dc.get("status")},
                 "new_value": {"status": new_status},
                 "reason": body.get("comment") or ""})
    return await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})


@api.delete("/dc/{dc_id}")
async def delete_dc(dc_id: str, reason: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can cancel DC")
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    await db.dcs.update_one({"dc_id": dc_id},
                            {"$set": {"deleted": True, "status": "cancelled"}})
    await audit("dc", dc_id, "cancel", u,
                {"dc_number": dc.get("dc_number"),
                 "old_value": {"status": dc.get("status")},
                 "new_value": {"status": "cancelled"},
                 "reason": reason or ""})
    return {"ok": True}


@api.get("/dc/{dc_id}/pdf")
async def dc_pdf(dc_id: str, token: Optional[str] = None,
                 force: Optional[int] = 0,
                 authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    project = await db.projects.find_one({"project_id": dc["project_id"]}, {"_id": 0}) or {}
    cust = await db.customers.find_one({"customer_id": dc.get("customer_id")}, {"_id": 0}) if dc.get("customer_id") else None
    vend = await db.vendors.find_one({"vendor_id": dc.get("vendor_id")}, {"_id": 0}) if dc.get("vendor_id") else None
    missing, warnings = _validate_dc_for_export(dc, project, "pdf")
    if missing and not force:
        raise _validation_error(missing, warnings, "pdf")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    doc.build(_dc_pdf_story(dc, project, cust, vend),
              onFirstPage=_vasu_footer, onLaterPages=_vasu_footer)
    buf.seek(0)
    await _log_export(u, "dc", dc_id, "pdf", dc["dc_number"],
                      {"warnings": warnings, "forced": bool(force and missing)})
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{dc["dc_number"].replace("/","_")}.pdf"'})


@api.get("/dc/{dc_id}/export")
async def dc_export_dispatch(dc_id: str,
                             format: str = "pdf",
                             force: Optional[int] = 0,
                             token: Optional[str] = None,
                             authorization: Optional[str] = Header(None)):
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "excel"):
        raise HTTPException(400, "format must be 'pdf' or 'excel'")
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    dc = await db.dcs.find_one({"dc_id": dc_id}, {"_id": 0})
    if not dc: raise HTTPException(404, "DC not found")
    await _check_dc_access(u, dc)
    if fmt == "pdf":
        return await dc_pdf(dc_id, token=token, force=force, authorization=authorization)
    project = await db.projects.find_one({"project_id": dc["project_id"]}, {"_id": 0}) or {}
    missing, warnings = _validate_dc_for_export(dc, project, fmt)
    if missing and not force:
        raise _validation_error(missing, warnings, fmt)
    wb = await _dc_excel_workbook([dc])
    await _log_export(u, "dc", dc_id, "excel", dc["dc_number"],
                      {"warnings": warnings, "forced": bool(force and missing)})
    return _excel_response(wb, f"{dc['dc_number'].replace('/', '_')}_details.xlsx")


@api.get("/export/dc")
async def export_dc(token: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in ("purchase", "director", "admin", "pm", "gm", "store"):
        raise HTTPException(403, "Not allowed")
    dcs = await db.dcs.find({"deleted": {"$ne": True}}, {"_id": 0}).sort("date", -1).to_list(2000)
    wb = await _dc_excel_workbook(dcs)
    await _log_export(u, "dc", "bulk", "excel", f"count={len(dcs)}")
    return _excel_response(wb, "dc_export.xlsx")


# ---------------------- Comparative Statement (import-only) ----------------------
CS_ROLES_UPLOAD = {"purchase", "admin"}  # only Purchase (and Admin/Accounts) can upload/edit CS
CS_ROLES_VIEW = {"purchase", "pm", "gm", "director", "admin", "site_engineer"}


@api.post("/comparative-statement")
async def create_cs(body: ComparativeStatementCreate,
                    authorization: Optional[str] = Header(None)):
    """Import a Comparative Statement prepared outside the app (Excel/PDF).
    File is stored inline as base64. Metadata (L1/L2/L3, selected vendor, remarks)
    accepted alongside. Attach via mrf_id or po_id (or both)."""
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_UPLOAD:
        raise HTTPException(403, "Not allowed to upload Comparative Statement")
    if not body.file_base64:
        raise HTTPException(400, "file_base64 is required")
    if not (body.mrf_id or body.po_id):
        raise HTTPException(400, "Attach to either mrf_id or po_id")

    # Try to compute size from base64 (approximate)
    try:
        import base64 as _b64
        raw = _b64.b64decode((body.file_base64.split(",", 1)[-1]).encode("utf-8"), validate=False)
        size = len(raw)
    except Exception:
        size = 0
    if size > 15 * 1024 * 1024:
        raise HTTPException(413, "File exceeds 15 MB")

    # Resolve project/customer from attached record if not supplied
    project_id = body.project_id
    customer_id = body.customer_id
    if body.mrf_id and not project_id:
        m = await db.mrfs.find_one({"mrf_id": body.mrf_id},
                                    {"_id": 0, "project_id": 1, "customer_id": 1})
        if m:
            project_id = m.get("project_id") or project_id
            customer_id = m.get("customer_id") or customer_id
    if body.po_id and not project_id:
        p = await db.pos.find_one({"po_id": body.po_id},
                                   {"_id": 0, "project_id": 1, "customer_id": 1})
        if p:
            project_id = p.get("project_id") or project_id
            customer_id = p.get("customer_id") or customer_id

    cs_number = await next_cs_number()
    cs = ComparativeStatement(
        **body.model_dump(exclude={"project_id", "customer_id"}),
        project_id=project_id or "",
        customer_id=customer_id or "",
        cs_number=cs_number,
        uploaded_by=u.user_id,
        uploaded_by_name=u.name,
        file_size=size,
    )
    doc = cs.model_dump()
    await db.comparative_statements.insert_one(dict(doc))
    await audit("comparative_statement", cs.cs_id, "upload", u,
                {"cs_number": cs.cs_number, "record_number": cs.cs_number,
                 "old_value": None,
                 "new_value": {"mrf_id": cs.mrf_id, "po_id": cs.po_id,
                               "title": cs.title, "file_name": cs.file_name,
                               "l1_vendor": cs.l1_vendor,
                               "selected_vendor": cs.selected_vendor,
                               "size": size},
                 "reason": body.remarks or ""})
    # Return without the base64 payload
    out = await db.comparative_statements.find_one(
        {"cs_id": cs.cs_id}, {"_id": 0, "file_base64": 0}
    )
    return _strip_oids(out)


@api.get("/comparative-statement")
async def list_cs(mrf_id: Optional[str] = None,
                  po_id: Optional[str] = None,
                  project_id: Optional[str] = None,
                  customer_id: Optional[str] = None,
                  authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    q: Dict[str, Any] = {"deleted": {"$ne": True}}
    if mrf_id: q["mrf_id"] = mrf_id
    if po_id: q["po_id"] = po_id
    if project_id: q["project_id"] = project_id
    if customer_id: q["customer_id"] = customer_id
    if u.role == "site_engineer":
        # SEs only see CS for MRFs they raised
        mrf_ids = [m["mrf_id"] for m in await db.mrfs.find(
            {"created_by": u.user_id}, {"_id": 0, "mrf_id": 1}).to_list(5000)]
        q["mrf_id"] = {"$in": mrf_ids}
    # Never ship base64 payloads in the list
    rows = await db.comparative_statements.find(q, {"_id": 0, "file_base64": 0}).sort("uploaded_at", -1).to_list(500)
    return rows


@api.get("/comparative-statement/{cs_id}")
async def get_cs(cs_id: str, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id},
                                                    {"_id": 0, "file_base64": 0})
    if not cs: raise HTTPException(404, "CS not found")
    return cs


@api.get("/comparative-statement/{cs_id}/download")
async def download_cs(cs_id: str, token: Optional[str] = None,
                      authorization: Optional[str] = Header(None)):
    """Return the original imported file as an attachment."""
    auth = authorization or (f"Bearer {token}" if token else None)
    u = await get_current_user(auth)
    if u.role not in CS_ROLES_VIEW:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id}, {"_id": 0})
    if not cs: raise HTTPException(404, "CS not found")
    import base64 as _b64
    b64 = cs.get("file_base64") or ""
    if not b64:
        raise HTTPException(404, "No file attached to this CS")
    try:
        raw = _b64.b64decode((b64.split(",", 1)[-1]).encode("utf-8"), validate=False)
    except Exception:
        raise HTTPException(500, "Corrupt attachment")
    fname = cs.get("file_name") or f"{cs.get('cs_number','CS').replace('/','_')}.bin"
    mime = cs.get("mime_type") or "application/octet-stream"
    await _log_export(u, "comparative_statement", cs_id,
                      "download", cs.get("cs_number", ""))
    return StreamingResponse(io.BytesIO(raw), media_type=mime,
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.put("/comparative-statement/{cs_id}")
async def update_cs(cs_id: str, body: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in CS_ROLES_UPLOAD:
        raise HTTPException(403, "Not allowed")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id}, {"_id": 0, "file_base64": 0})
    if not cs: raise HTTPException(404, "CS not found")
    # Lock edits after approval — Admin/Director can still override
    if cs.get("status") == "approved" and u.role not in ("admin", "director"):
        raise HTTPException(400, "CS is approved and locked")
    ALLOWED = {"title", "remarks", "vendors", "l1_vendor", "l1_amount",
               "selected_vendor", "selection_reason"}  # Note: `status` no longer editable directly
    updates = {k: v for k, v in body.items() if k in ALLOWED}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    old_snap = {k: cs.get(k) for k in updates.keys()}
    await db.comparative_statements.update_one({"cs_id": cs_id}, {"$set": updates})
    await audit("comparative_statement", cs_id, "edit", u,
                {"cs_number": cs.get("cs_number"),
                 "old_value": old_snap,
                 "new_value": updates,
                 "reason": body.get("reason") or ""})
    return await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})


@api.post("/comparative-statement/{cs_id}/approve")
async def approve_cs(cs_id: str, body: Dict[str, Any] = Body(default={}),
                     authorization: Optional[str] = Header(None)):
    """PM/GM/Director approves or rejects a Comparative Statement."""
    u = await get_current_user(authorization)
    if u.role not in CS_APPROVER_ROLES:
        raise HTTPException(403, "Only pm/gm/director can approve Comparative Statement")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id}, {"_id": 0, "file_base64": 0})
    if not cs: raise HTTPException(404, "CS not found")
    action = (body.get("action") or "approve").lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    current = cs.get("status") or "pending_approval"
    if current not in ("pending_approval", "rejected", "active"):
        raise HTTPException(400, f"Cannot {action}: CS is '{current}'")
    new_status = "approved" if action == "approve" else "rejected"
    hist = {
        "user_id": u.user_id, "user_name": u.name, "user_role": u.role,
        "action": action, "comment": body.get("comment") or "",
        "timestamp": now_utc().isoformat(),
    }
    await db.comparative_statements.update_one(
        {"cs_id": cs_id},
        {"$set": {"status": new_status},
         "$push": {"approval_history": hist}},
    )
    await audit("comparative_statement", cs_id, f"cs_{action}", u,
                {"cs_number": cs.get("cs_number"),
                 "record_number": cs.get("cs_number"),
                 "old_value": {"status": current},
                 "new_value": {"status": new_status},
                 "reason": body.get("comment") or ""})
    return await db.comparative_statements.find_one({"cs_id": cs_id},
                                                     {"_id": 0, "file_base64": 0})


@api.delete("/comparative-statement/{cs_id}")
async def delete_cs(cs_id: str, reason: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ("admin", "director"):
        raise HTTPException(403, "Only admin/director can delete CS")
    cs = await db.comparative_statements.find_one({"cs_id": cs_id}, {"_id": 0, "file_base64": 0})
    if not cs: raise HTTPException(404, "CS not found")
    await db.comparative_statements.update_one({"cs_id": cs_id},
                                                {"$set": {"deleted": True, "status": "cancelled"}})
    await audit("comparative_statement", cs_id, "delete", u,
                {"cs_number": cs.get("cs_number"),
                 "old_value": {"status": cs.get("status"), "deleted": False},
                 "new_value": {"status": "cancelled", "deleted": True},
                 "reason": reason or ""})
    return {"ok": True}


# ---------------------- LLM Co-pilot ----------------------
# Extracted to routers/llm.py in Phase 9C. Import is deferred to the bottom
# of this file (below), after every symbol it depends on is defined.


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

    # Phase 4: Migrate existing masters.category="material" records into the new
    # `materials` collection with MAT-#### UIDs, in creation-date order. Idempotent.
    legacy_mats = await db.masters.find(
        {"category": "material", "active": True}, {"_id": 0}
    ).sort("_id", 1).to_list(2000)
    for lm in legacy_mats:
        norm = _norm(lm.get("name", ""))
        if not norm:
            continue
        existing = await db.materials.find_one({"description_norm": norm}, {"_id": 0})
        if existing:
            continue
        n = await _next_seq("materials")
        wc = _word_count(lm.get("name", ""))
        doc = {
            "material_uid": _mat_uid(n),
            "description": lm["name"],
            "description_norm": norm,
            "category": "", "unit": "", "gst_rate": None,
            "item_code": "", "remarks": "Migrated from legacy master",
            "status": "approved" if wc <= MAT_WORD_LIMIT else "needs_correction",
            "created_by": "system", "created_by_name": "System Migration",
            "created_at": now_utc(), "updated_at": now_utc(),
            "approved_by": "system" if wc <= MAT_WORD_LIMIT else None,
            "approved_at": now_utc() if wc <= MAT_WORD_LIMIT else None,
            "legacy_item_id": lm.get("item_id"),
            "source": "migration",
        }
        await db.materials.insert_one(doc)

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
    # ---- Phase 4: Material / Variant masters ----
    await db.materials.create_index("material_uid", unique=True)
    await db.materials.create_index([("description_norm", 1)], unique=True, sparse=True)
    await db.variants.create_index("variant_uid", unique=True)
    await db.variants.create_index([("material_uid", 1), ("make_norm", 1), ("model_norm", 1)], unique=True)

@app.on_event("shutdown")
async def shutdown():
    client.close()

@api.get("/")
async def root():
    return {"app": "Vasu Infosec MRF & PO", "ok": True}

# ---------------------- Register extracted routers (Phase 9C) ----------------------
# Router-module imports MUST happen BEFORE app.include_router(api) so their
# @api.post/@api.get decorators are picked up when FastAPI snapshots the router.
from routers import llm as _llm_router  # noqa: E402,F401

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
