"""
Vasu Infosec — Material Requisition & Purchase Order System
Backend: FastAPI + MongoDB + Emergent Google Auth
"""
import os
import io
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
# Roles: Director/PM/GM/Purchase/Admin. Legacy roles auto-migrated.
ROLES = ["director", "pm", "gm", "purchase", "admin"]
LEGACY_ROLE_MAP = {
    "site_engineer": "pm",
    "project_manager": "pm",
    "billing": "purchase",
}
def _canon_role(r: str) -> str:
    return LEGACY_ROLE_MAP.get(r, r) if r in LEGACY_ROLE_MAP else r

MRF_APPROVERS = {"pm", "gm", "director", "admin"}
MRF_EDITORS = {"pm", "gm", "purchase", "director", "admin"}
SYSTEMS = ["Fire Alarm", "Fire Fighting", "Gas Suppression", "Water Mist",
           "CCTV", "Access Control", "Structured Cabling", "Electrical", "Other"]
MRF_STATUS = ["draft", "submitted", "pm_review", "approved", "rejected",
              "returned", "sent_to_purchase", "partially_ordered", "fully_ordered",
              "received", "closed"]
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
    role: str = "pm"
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
    client: Optional[str] = None
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
    category: str  # unit/system/brand/material
    active: bool = True

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
        role = existing.get("role", "pm")
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        # First user becomes admin
        count = await db.users.count_documents({})
        role = "admin" if count == 0 else "pm"
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
    # Purchase/billing/admin see all. Site engineer + PM see only assigned unless all=1 (admin only).
    if all and u.role == "admin":
        return docs
    if u.role == "pm":
        docs = [
            p for p in docs
            if u.user_id in (p.get("site_engineers") or [])
            or any(u.user_id in (s.get("site_engineers") or [])
                   for s in (p.get("sites") or []) if s.get("active", True))
        ]
    elif u.role == "pm":
        docs = [p for p in docs if u.user_id in (p.get("project_managers") or [])]
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
    await db.projects.insert_one(p.model_dump())
    await audit("project", p.project_id, "create", u, p.model_dump())
    return p

@api.put("/projects/{project_id}")
async def update_project(project_id: str, body: dict,
                         authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    updates: Dict[str, Any] = {}
    for k in ("code", "name", "site", "client"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "system_categories" in body and isinstance(body["system_categories"], list):
        updates["system_categories"] = [str(x) for x in body["system_categories"]]
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    r = await db.projects.update_one({"project_id": project_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "update", u, updates)
    return await db.projects.find_one({"project_id": project_id}, {"_id": 0})

@api.delete("/projects/{project_id}")
async def deactivate_project(project_id: str,
                             authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    r = await db.projects.update_one({"project_id": project_id},
                                     {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Project not found")
    await audit("project", project_id, "deactivate", u)
    return {"ok": True}

@api.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, body: dict,
                        authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ["admin", "purchase"]:
        raise HTTPException(403, "Not allowed")
    updates: Dict[str, Any] = {}
    for k in ("name", "address", "gstin", "contact", "email"):
        if k in body:
            updates[k] = str(body[k] or "").strip()
    if "active" in body:
        updates["active"] = bool(body["active"])
    if not updates:
        raise HTTPException(400, "Nothing to update")
    r = await db.vendors.update_one({"vendor_id": vendor_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Vendor not found")
    await audit("vendor", vendor_id, "update", u, updates)
    return await db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})

@api.delete("/vendors/{vendor_id}")
async def deactivate_vendor(vendor_id: str,
                            authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ["admin", "purchase"]:
        raise HTTPException(403, "Not allowed")
    r = await db.vendors.update_one({"vendor_id": vendor_id},
                                    {"$set": {"active": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "Vendor not found")
    await audit("vendor", vendor_id, "deactivate", u)
    return {"ok": True}

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
    if u.role not in ["admin", "purchase"]:
        raise HTTPException(403, "Not allowed")
    await db.vendors.insert_one(v.model_dump())
    await audit("vendor", v.vendor_id, "create", u, v.model_dump())
    return v

@api.get("/masters")
async def list_masters(authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    items = await db.masters.find({"active": True}, {"_id": 0}).to_list(1000)
    grouped: Dict[str, List] = {"unit": [], "brand": [], "system": [], "material": []}
    for it in items:
        grouped.setdefault(it["category"], []).append(it)
    grouped["system"] = grouped.get("system") or [{"name": s} for s in SYSTEMS]
    return grouped

@api.post("/masters")
async def add_master(m: MasterItem, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role != "admin":
        raise HTTPException(403, "Only admin")
    await db.masters.insert_one(m.model_dump())
    await audit("master", m.item_id, "create", u, m.model_dump())
    return m

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
    if u.role in ["pm", "pm"]:
        p = await db.projects.find_one({"project_id": body.project_id}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Project not found")
        if u.role == "pm":
            in_project = u.user_id in (p.get("site_engineers") or [])
            in_any_site = any(u.user_id in (s.get("site_engineers") or [])
                              for s in (p.get("sites") or []) if s.get("active", True))
            if not (in_project or in_any_site):
                raise HTTPException(403, "You are not assigned to this project")
        else:
            if u.user_id not in (p.get("project_managers") or []):
                raise HTTPException(403, "You are not assigned to this project")
    items = []
    for i in body.items:
        d = i.model_dump()
        if d.get("qty_approved") is None:
            d["qty_approved"] = i.qty_requested
        items.append(MRFItem(**d))
    mrf = MRF(
        mrf_number=await next_mrf_number(),
        project_id=body.project_id,
        site=body.site,
        required_by=body.required_by,
        requesting_person=body.requesting_person,
        system_category=body.system_category,
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
    # Site engineers only see their own; PMs only see MRFs from their assigned projects
    if u.role == "pm":
        q["created_by"] = u.user_id
    elif u.role == "pm":
        prjs = await db.projects.find(
            {"project_managers": u.user_id}, {"_id": 0, "project_id": 1}
        ).to_list(500)
        q["project_id"] = {"$in": [p["project_id"] for p in prjs]}
    docs = await db.mrfs.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs

async def _check_mrf_access(u: UserOut, mrf: dict):
    """Raise 403 if user cannot see this MRF."""
    if u.role in ("admin", "purchase", "purchase"):
        return
    if u.role == "pm":
        if mrf.get("created_by") == u.user_id:
            return
        p = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0})
        if p and (u.user_id in (p.get("site_engineers") or []) or
                  any(u.user_id in (s.get("site_engineers") or [])
                      for s in (p.get("sites") or []) if s.get("active", True))):
            return
        raise HTTPException(403, "Not allowed")
    if u.role == "pm":
        p = await db.projects.find_one({"project_id": mrf["project_id"]}, {"_id": 0})
        if p and u.user_id in (p.get("project_managers") or []):
            return
        raise HTTPException(403, "Not allowed")
    raise HTTPException(403, "Not allowed")

async def _check_po_access(u: UserOut, po: dict):
    if u.role in ("admin", "purchase", "purchase"):
        return
    if u.role == "pm":
        p = await db.projects.find_one({"project_id": po.get("project_id")}, {"_id": 0})
        if p and u.user_id in (p.get("project_managers") or []):
            return
    if u.role == "pm":
        for mid in po.get("mrf_refs") or []:
            m = await db.mrfs.find_one({"mrf_id": mid}, {"_id": 0, "created_by": 1})
            if m and m.get("created_by") == u.user_id:
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
    if d["status"] not in ["draft", "returned"]:
        raise HTTPException(400, "Cannot submit from current status")
    await db.mrfs.update_one(
        {"mrf_id": mrf_id},
        {"$set": {"status": "pm_review", "updated_at": now_utc()}}
    )
    await audit("mrf", mrf_id, "submit", u)
    # Notify PMs
    pms = await db.users.find({"role": "pm"}, {"_id": 0, "user_id": 1}).to_list(50)
    await notify([p["user_id"] for p in pms], "MRF pending review",
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
    if u.role not in ["pm", "admin"]:
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

# ---------------------- Purchase Orders ----------------------
@api.post("/po")
async def create_po(body: POCreate, authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    if u.role not in ["purchase", "admin"]:
        raise HTTPException(403, "Only purchase/admin")

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
        created_by=u.user_id,
    )
    po_doc = po.model_dump()
    # items -> as dict
    po_doc["items"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in body.items]
    await db.pos.insert_one(po_doc)

    # Update MRF item qty_ordered and MRF status
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

    await audit("po", po.po_id, "create", u, {"po_number": po.po_number, "total": total})
    po_doc.pop("_id", None)
    return po_doc

@api.get("/po")
async def list_pos(project_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    q: Dict[str, Any] = {"deleted": False}
    if project_id:
        q["project_id"] = project_id
    docs = await db.pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    if u.role in ("admin", "purchase", "purchase"):
        return docs
    if u.role == "pm":
        prjs = await db.projects.find({"project_managers": u.user_id},
                                      {"_id": 0, "project_id": 1}).to_list(500)
        allowed = {p["project_id"] for p in prjs}
        return [p for p in docs if p.get("project_id") in allowed]
    if u.role == "pm":
        # Only POs whose mrf_refs include an MRF created by this user
        my = await db.mrfs.find({"created_by": u.user_id},
                                {"_id": 0, "mrf_id": 1}).to_list(2000)
        my_ids = {m["mrf_id"] for m in my}
        return [p for p in docs if my_ids.intersection(p.get("mrf_refs") or [])]
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
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin can record receipt")
    po = await db.pos.find_one({"po_id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO not found")

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
    if u.role not in ("purchase", "admin", "purchase"):
        raise HTTPException(403, "Only billing/purchase/admin")
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
    if u.role not in ["purchase", "admin"]:
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

# ---------------------- PDF ----------------------
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

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#002FA7'))
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)
    story = []
    story.append(Paragraph("VASU INFOSEC", title_style))
    story.append(Paragraph("PURCHASE ORDER", styles['Heading2']))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>PO Number:</b> {po['po_number']}   <b>Date:</b> {po['date'].strftime('%d-%b-%Y')}", small))
    story.append(Paragraph(f"<b>MRF Ref:</b> {', '.join(po_mrf_nums)}", small))
    story.append(Spacer(1, 6))
    vendor_info = f"<b>Vendor:</b> {vendor.get('name','')}<br/>{vendor.get('address','')}<br/>GSTIN: {vendor.get('gstin','')}<br/>Contact: {vendor.get('contact','')}"
    story.append(Paragraph(vendor_info, small))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Project:</b> {project.get('name','')} ({project.get('code','')})<br/><b>Delivery:</b> {po['delivery_site']}", small))
    story.append(Spacer(1, 8))

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
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Freight:</b> {po.get('freight',0)}  <b>Other:</b> {po.get('other_charges',0)}  <b>Grand Total:</b> {po.get('total',0)}", small))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Delivery:</b> {po.get('delivery_schedule','')}", small))
    story.append(Paragraph(f"<b>Payment:</b> {po.get('payment_terms','')}", small))
    story.append(Paragraph(f"<b>Warranty:</b> {po.get('warranty_terms','')}", small))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"Authorised Signatory: {po.get('authorised_signatory','')}", small))
    doc.build(story)
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
    headers = ["MRF#", "Date", "Project", "Site", "Requester", "System", "Status", "Item", "Qty", "Approved", "Billing"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    for m in mrfs:
        for it in m["items"]:
            ws.append([_safe_cell(m["mrf_number"]),
                       m["date"].strftime("%Y-%m-%d") if isinstance(m["date"], datetime) else str(m["date"]),
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
    ws.append(["PO#", "Date", "Vendor", "Project", "MRF Refs", "Total", "Status"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="002FA7")
    for p in pos:
        ws.append([_safe_cell(p["po_number"]),
                   p["date"].strftime("%Y-%m-%d") if isinstance(p["date"], datetime) else str(p["date"]),
                   _safe_cell(p.get("vendor_id", "")), _safe_cell(p.get("project_id", "")),
                   _safe_cell(", ".join(p.get("mrf_refs", []))),
                   p.get("total", 0), _safe_cell(p.get("status", ""))])
    return _excel_response(wb, "po_export.xlsx")

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
    if u.role not in ("purchase", "director", "admin"):
        raise HTTPException(403, "Only purchase/billing/admin")
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
    title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#002FA7'))
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)
    story = [
        Paragraph("VASU INFOSEC", title_style),
        Paragraph("GOODS RECEIVED NOTE", styles['Heading2']),
        Spacer(1, 6),
        Paragraph(f"<b>GRN Number:</b> {grn['grn_number']}   <b>Date:</b> "
                  f"{grn['date'].strftime('%d-%b-%Y %H:%M') if isinstance(grn['date'], datetime) else str(grn['date'])}", small),
        Paragraph(f"<b>PO Ref:</b> {grn.get('po_number','')}    <b>MRF Ref:</b> {', '.join(grn_mrf_nums)}", small),
        Spacer(1, 6),
        Paragraph(f"<b>Vendor:</b> {vendor.get('name','')} | GSTIN: {vendor.get('gstin','')}", small),
        Paragraph(f"<b>Project:</b> {project.get('name','')} ({project.get('code','')})", small),
        Paragraph(f"<b>Received by:</b> {grn.get('received_by_name','')}", small),
        Spacer(1, 8),
    ]
    data = [["#", "Description", "Unit", "Qty Received"]]
    for idx, it in enumerate(grn.get("items", []), 1):
        data.append([str(idx), (it.get("description") or "")[:60], it.get("unit", ""), str(it.get("qty", ""))])
    tbl = Table(data, colWidths=[25, 320, 60, 80])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#002FA7')),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
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
    doc.build(story)
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
    if u.role not in ["admin", "pm", "pm"]:
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
    title_style = ParagraphStyle('t', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#002FA7'))
    small = ParagraphStyle('s', parent=styles['Normal'], fontSize=9)
    story = [
        Paragraph("VASU INFOSEC", title_style),
        Paragraph("VENDOR INVOICE", styles['Heading2']),
        Spacer(1, 6),
        Paragraph(f"<b>Invoice #:</b> {inv['invoice_number']}    <b>Date:</b> {inv['invoice_date']}", small),
        Paragraph(f"<b>Vendor Ref:</b> {inv.get('vendor_invoice_number') or '—'}    <b>PO:</b> {inv['po_number']}", small),
        Paragraph(f"<b>MRF Refs:</b> {', '.join(mrf_nums) or '—'}", small),
        Spacer(1, 8),
        Paragraph(f"<b>Vendor:</b> {vendor.get('name','')} | GSTIN: {vendor.get('gstin','')} | {vendor.get('address','')}", small),
        Paragraph(f"<b>Project:</b> {project.get('name','')} ({project.get('code','')})", small),
        Spacer(1, 8),
    ]
    data = [["#", "Description", "Unit", "Qty", "Rate", "Disc", "GST%", "Total"]]
    for idx, it in enumerate(inv["items"], 1):
        data.append([str(idx), (it["description"] or "")[:40], it.get("unit", ""),
                     str(it["qty"]), f"{it['rate']}", f"{it.get('discount', 0)}",
                     f"{it.get('gst', 0)}", f"{it.get('line_total', 0):.2f}"])
    tbl = Table(data, colWidths=[20, 180, 40, 40, 50, 40, 40, 60])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#002FA7')),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Subtotal:</b> {inv['subtotal']}  <b>GST:</b> {inv['gst_total']}  "
        f"<b>Freight:</b> {inv.get('freight', 0)}  <b>Other:</b> {inv.get('other_charges', 0)}  "
        f"<b>Grand Total:</b> {inv['total']}", small))
    if inv.get("remarks"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Remarks:</b> {inv['remarks']}", small))
    story += [
        Spacer(1, 30),
        Paragraph("Recorded by: " + inv.get("created_by_name", ""), small),
    ]
    doc.build(story)
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
    # Users
    demo_users = [
        {"email": "director@vasu.dev", "name": "Vishal (Director)", "role": "director"},
        {"email": "pm@vasu.dev", "name": "Priya (PM)", "role": "pm"},
        {"email": "gm@vasu.dev", "name": "Girish (GM)", "role": "gm"},
        {"email": "purchase@vasu.dev", "name": "Kumar (Purchase)", "role": "purchase"},
        {"email": "admin@vasu.dev", "name": "Master Admin", "role": "admin"},
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
            await db.users.update_one({"email": u["email"]}, {"$set": {"role": u["role"]}})

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

    # Seed team: assign seeded PM (site engineer role removed) to all seeded projects (idempotent)
    pm_user = await db.users.find_one({"email": "pm@vasu.dev"}, {"_id": 0, "user_id": 1})
    if pm_user:
        await db.projects.update_many(
            {"code": {"$in": [p["code"] for p in projects]}},
            {"$addToSet": {
                "site_engineers": pm_user["user_id"],
                "project_managers": pm_user["user_id"],
            }},
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
