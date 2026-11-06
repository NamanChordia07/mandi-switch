"""Domain model: SQLModel tables (persisted in SQLite) + Pydantic shapes used by the API.

Money is always integer paise. Timestamps are ISO-8601 strings in UTC (with 'Z'),
which keeps SQLite simple and the audit hash stable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field as PField
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ----------------------------------------------------------------------------- enums
class Basis(str, Enum):
    DELIVERED = "DELIVERED"
    EX_WORKS = "EX_WORKS"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISQUALIFIED = "DISQUALIFIED"
    NO_ROOM = "NO_ROOM"
    CLOSED = "CLOSED"  # negotiation finished without award (still a valid bidder)


class TrapCode(str, Enum):
    HIDDEN_MOQ = "HIDDEN_MOQ"
    EXPIRED = "EXPIRED"
    LATE_DELIVERY = "LATE_DELIVERY"
    FREIGHT_EXCLUDED = "FREIGHT_EXCLUDED"
    MISSING_FIELD = "MISSING_FIELD"
    INJECTION = "INJECTION"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"


class InjectionVerdict(str, Enum):
    CLEAN = "CLEAN"
    SUSPICIOUS = "SUSPICIOUS"
    INJECTION = "INJECTION"


class Side(str, Enum):
    BUYER = "BUYER"
    VENDOR = "VENDOR"


class OfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"
    EXPIRED = "EXPIRED"


class Verification(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    NA = "N/A"


class ApprovalKind(str, Enum):
    PURCHASE_HEAD_ENDORSEMENT = "PURCHASE_HEAD_ENDORSEMENT"
    FINANCE_RELEASE = "FINANCE_RELEASE"
    VENDOR_BELOW_LINE = "VENDOR_BELOW_LINE"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class Mechanism(str, Enum):
    SWITCH_PERMISSION = "SWITCH_PERMISSION"            # Switch permission request on an owned gate agent
    SWITCH_MESSAGE_FALLBACK = "SWITCH_MESSAGE_FALLBACK"  # reply in a Switch room, sender id verified
    AUTO_TIER = "AUTO_TIER"                            # below the auto-approve threshold


# ----------------------------------------------------------------------------- value objects
class Spec(BaseModel):
    part_name: str
    part_spec: str
    drawing_ref: str = ""
    quantity: int
    uom: str = "pieces"
    needed_by: str  # ISO date
    delivery_terms: str = ""
    currency: str = "INR"
    assumptions: list[str] = PField(default_factory=list)
    confirmed_by: Optional[str] = None


class Evidence(BaseModel):
    page: Optional[int] = None
    snippet: str = ""


class Trap(BaseModel):
    code: TrapCode
    severity: Severity
    message: str
    evidence: Evidence = PField(default_factory=Evidence)


class LeverageClaim(BaseModel):
    type: str = "competing_offer"
    unit_price_paise: int
    basis: Basis = Basis.DELIVERED
    source_vendor: Optional[str] = None      # what the LLM *said*; never trusted
    source_offer_id: Optional[str] = None    # filled by Core when verified (internal only)
    verified: bool = False
    reason: str = ""


# ----------------------------------------------------------------------------- tables
class OrderRow(SQLModel, table=True):
    __tablename__ = "orders"
    id: str = Field(primary_key=True)
    base_id: str = ""                 # SM-PR-2026-0147 (id may carry a run suffix, e.g. -r3)
    buyer: str = ""
    plant: str = ""
    requester_user: str = ""
    created_at: str = Field(default_factory=now_iso)
    raw_request: str = ""
    spec: dict = Field(default_factory=dict, sa_column=Column(JSON))
    spec_confirmed: bool = False
    state: str = "DRAFT"
    tier: Optional[str] = None
    awarded_vendor_id: Optional[str] = None
    awarded_offer_id: Optional[str] = None
    po_id: Optional[str] = None
    rooms: dict = Field(default_factory=dict, sa_column=Column(JSON))       # {"order": room_id, "deccan": ...}
    stage_times: dict = Field(default_factory=dict, sa_column=Column(JSON))  # state -> first time reached
    notes: list = Field(default_factory=list, sa_column=Column(JSON))


class VendorRow(SQLModel, table=True):
    __tablename__ = "vendors"
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: str = Field(index=True)
    vendor_id: str
    legal_name: str
    status: str = VendorStatus.ACTIVE.value
    room_id: Optional[str] = None
    agent_name: Optional[str] = None
    negotiator: Optional[str] = None
    status_reason: str = ""


class QuoteRow(SQLModel, table=True):
    __tablename__ = "quotes"
    id: str = Field(primary_key=True)
    order_id: str = Field(index=True)
    vendor_id: str
    source_file: str
    source_sha256: str = ""
    received_at: str = Field(default_factory=now_iso)
    received_via: str = ""            # "switch_attachment" | "vendor_upload" | "email_import"
    parsed: bool = False
    quote_ref: str = ""
    unit_price_paise: Optional[int] = None
    basis: Optional[str] = None
    freight_paise_per_unit: Optional[int] = None
    moq: Optional[int] = None
    lead_time_days: Optional[int] = None
    valid_until: Optional[str] = None
    payment_terms_days: Optional[int] = None
    extraction_confidence: float = 0.0
    extraction_method: str = ""
    fields_missing: list = Field(default_factory=list, sa_column=Column(JSON))
    evidence: dict = Field(default_factory=dict, sa_column=Column(JSON))       # field -> {page, snippet}
    injection_verdict: str = InjectionVerdict.CLEAN.value
    injection_confidence: float = 0.0
    injection_spans: list = Field(default_factory=list, sa_column=Column(JSON))
    injection_detail: dict = Field(default_factory=dict, sa_column=Column(JSON))
    traps: list = Field(default_factory=list, sa_column=Column(JSON))
    comparable: bool = False
    landed_unit_paise: Optional[int] = None
    landed_total_paise: Optional[int] = None


class OfferRow(SQLModel, table=True):
    """Negotiation ledger. Append-only: rows are never deleted; status may move forward."""
    __tablename__ = "offers"
    id: str = Field(primary_key=True)
    order_id: str = Field(index=True)
    vendor_id: str
    round: int
    side: str
    unit_price_paise: Optional[int] = None
    basis: str = Basis.DELIVERED.value
    quantity: int = 0
    conditions: str = ""
    status: str = OfferStatus.PROPOSED.value
    is_final: bool = False
    claims: list = Field(default_factory=list, sa_column=Column(JSON))
    verification: str = Verification.NA.value
    message_text: str = ""
    created_at: str = Field(default_factory=now_iso)
    switch_message_id: Optional[str] = None
    redteam: bool = False


class ApprovalRow(SQLModel, table=True):
    __tablename__ = "approvals"
    id: str = Field(primary_key=True)
    order_id: str = Field(index=True)
    kind: str
    decision: str
    decided_by_user: str
    mechanism: str
    agent_name: str = ""
    vendor_id: Optional[str] = None
    unit_price_paise: Optional[int] = None
    switch_ref: Optional[str] = None
    note: str = ""
    at: str = Field(default_factory=now_iso)


class PurchaseOrderRow(SQLModel, table=True):
    __tablename__ = "purchase_orders"
    id: str = Field(primary_key=True)
    order_id: str = Field(index=True, unique=True)
    vendor_id: str
    unit_price_paise: int
    quantity: int
    total_paise: int
    terms: dict = Field(default_factory=dict, sa_column=Column(JSON))
    approvals: list = Field(default_factory=list, sa_column=Column(JSON))
    pdf_path: str = ""
    sha256: str = ""
    audit_hash: str = ""
    issued_at: str = Field(default_factory=now_iso)
    issued_by_agent: str = ""


class AuditRow(SQLModel, table=True):
    """Append-only, hash-chained audit log (tamper-evident)."""
    __tablename__ = "audit"
    seq: Optional[int] = Field(default=None, primary_key=True)
    at: str = Field(default_factory=now_iso)
    order_id: str = Field(index=True)
    actor: str
    kind: str
    summary: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    prev_hash: str = ""
    hash: str = ""


class FeedRow(SQLModel, table=True):
    """Switch room traffic captured by the auditor agent from its live Switch event stream."""
    __tablename__ = "switch_feed"
    id: Optional[int] = Field(default=None, primary_key=True)
    at: str = Field(default_factory=now_iso)
    event: str = "message"            # message | command | room_join
    room_id: str = ""
    room_key: str = ""                # order | deccan | ganesh | apex | ""
    sequence: Optional[int] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    sender: str = ""
    sender_name: str = ""
    sender_kind: str = "unknown"      # human | agent | switch | unknown
    body: str = ""
    addressed: bool = False
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))


# ----------------------------------------------------------------------------- API shapes
class AuditKind(str, Enum):
    REQUEST_POSTED = "REQUEST_POSTED"
    SPEC_DRAFTED = "SPEC_DRAFTED"
    SPEC_CONFIRMED = "SPEC_CONFIRMED"
    ROOMS_OPENED = "ROOMS_OPENED"
    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    QUOTE_PARSED = "QUOTE_PARSED"
    TRAP_FOUND = "TRAP_FOUND"
    INJECTION_BLOCKED = "INJECTION_BLOCKED"
    VENDOR_DISQUALIFIED = "VENDOR_DISQUALIFIED"
    COMPARISON_PUBLISHED = "COMPARISON_PUBLISHED"
    NEGOTIATION_STARTED = "NEGOTIATION_STARTED"
    OFFER_SENT = "OFFER_SENT"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    LEVERAGE_VERIFIED = "LEVERAGE_VERIFIED"
    LEVERAGE_BLOCKED = "LEVERAGE_BLOCKED"
    VENDOR_APPROVAL_REQUESTED = "VENDOR_APPROVAL_REQUESTED"
    VENDOR_APPROVAL_DECIDED = "VENDOR_APPROVAL_DECIDED"
    NEGOTIATION_CLOSED = "NEGOTIATION_CLOSED"
    AWARDED = "AWARDED"
    ENDORSEMENT_REQUESTED = "ENDORSEMENT_REQUESTED"
    ENDORSED = "ENDORSED"
    ENDORSEMENT_DECLINED = "ENDORSEMENT_DECLINED"
    PO_REQUESTED = "PO_REQUESTED"
    PO_REFUSED_BY_RULE = "PO_REFUSED_BY_RULE"
    PO_DECLINED = "PO_DECLINED"
    PO_ISSUED = "PO_ISSUED"
    DOC_SAVED_TO_ROOM = "DOC_SAVED_TO_ROOM"
    OUTCOME_POSTED = "OUTCOME_POSTED"
    REDTEAM_TRIGGERED = "REDTEAM_TRIGGERED"
    SWITCH_APPROVAL_OBSERVED = "SWITCH_APPROVAL_OBSERVED"
    STATE_CHANGED = "STATE_CHANGED"
    DEMO_RESET = "DEMO_RESET"


def row_dict(row: SQLModel) -> dict[str, Any]:
    return row.model_dump()
