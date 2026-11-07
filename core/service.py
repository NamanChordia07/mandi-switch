"""Mandi Core business operations. Every state change: DB write + audit event + bus event.

The FastAPI layer (app.py) stays thin and calls these functions. Agents never touch the DB directly.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from . import approvals, audit, compare, db
from .config import (ROOT, env, generated_dir, persona, resolve_date, scenario, scenario_date,
                     vendor_public)
from .events import bus
from .leverage import OutboundContext, Source, check_outbound
from .models import (ApprovalKind, ApprovalRow, AuditKind, Basis, Decision, FeedRow, InjectionVerdict,
                     LeverageClaim, Mechanism, OfferRow, OfferStatus, OrderRow, PurchaseOrderRow,
                     QuoteRow, Side, Spec, Verification, VendorRow, VendorStatus, now_iso)
from .money import fmt_inr, fmt_unit, indian_group, pct
from .negotiation import BuyerPolicy, buyer_next_move
from .po import GateFacts, gate_checks
from .states import OrderState, check_transition
from .traps import DEFAULT_FREIGHT_ESTIMATE_PAISE, QuoteFacts, evaluate


class CoreError(Exception):
    status = 400

    def __init__(self, message: str, *, status: int | None = None, details: Any = None):
        super().__init__(message)
        if status:
            self.status = status
        self.details = details


class NotFound(CoreError):
    status = 404


class Conflict(CoreError):
    status = 409


# Gate agents act for exactly one human each (enforced in Switch by "who can talk to your agent").
APPROVER_FOR_AGENT = {"purchase-desk": "meera", "po-issuer": "vikram"}


# ----------------------------------------------------------------------------- helpers
def _order(s: Session, order_id: str) -> OrderRow:
    o = s.get(OrderRow, order_id)
    if not o:
        raise NotFound(f"Order {order_id} not found.")
    return o


def _vendors(s: Session, order_id: str) -> dict[str, VendorRow]:
    return {v.vendor_id: v for v in s.exec(select(VendorRow).where(VendorRow.order_id == order_id))}


def _quotes(s: Session, order_id: str) -> list[QuoteRow]:
    return list(s.exec(select(QuoteRow).where(QuoteRow.order_id == order_id).order_by(QuoteRow.received_at)))


def _offers(s: Session, order_id: str, vendor_id: str | None = None) -> list[OfferRow]:
    q = select(OfferRow).where(OfferRow.order_id == order_id)
    if vendor_id:
        q = q.where(OfferRow.vendor_id == vendor_id)
    return list(s.exec(q.order_by(OfferRow.created_at)))


def _approvals(s: Session, order_id: str) -> list[ApprovalRow]:
    return list(s.exec(select(ApprovalRow).where(ApprovalRow.order_id == order_id).order_by(ApprovalRow.at)))


def _set_state(s: Session, o: OrderRow, target: OrderState, actor: str) -> None:
    prev = o.state
    check_transition(o.state, target)
    o.state = target.value
    times = dict(o.stage_times or {})
    times.setdefault(target.value, now_iso())
    o.stage_times = times
    s.add(o)
    audit.append(s, order_id=o.id, actor=actor, kind=AuditKind.STATE_CHANGED.value,
                 summary=f"Order moved {prev} → {target.value}.", data={"from": prev, "to": target.value})
    bus.publish("order.state", o.id, state=target.value, previous=prev)


def _audit(s: Session, order_id: str, actor: str, kind: AuditKind, summary: str, **data: Any) -> None:
    row = audit.append(s, order_id=order_id, actor=actor, kind=kind.value, summary=summary, data=data)
    bus.publish("audit", order_id, seq=row.seq, audit_kind=kind.value, actor=actor, summary=summary,
                hash=row.hash, data=data)


def _spec(o: OrderRow) -> Spec:
    return Spec(**o.spec)


def _needed_by(o: OrderRow) -> date:
    return date.fromisoformat(o.spec["needed_by"])


def _landed(unit_paise: int, basis: str, freight: Optional[int]) -> int:
    if basis == Basis.EX_WORKS.value:
        return unit_paise + (freight if freight is not None else DEFAULT_FREIGHT_ESTIMATE_PAISE)
    return unit_paise


def current_order_id() -> Optional[str]:
    with db.session() as s:
        o = s.exec(select(OrderRow).order_by(OrderRow.created_at.desc()).limit(1)).first()
        return o.id if o else None


# ----------------------------------------------------------------------------- order lifecycle
def create_order(*, raw_text: str, requester: str, actor: str, order_id: str | None = None,
                 switch_message_id: str | None = None) -> dict[str, Any]:
    sc = scenario()["order"]
    oid = order_id or sc["order_id"]
    with db.session() as s:
        if s.get(OrderRow, oid):
            raise Conflict(f"Order {oid} already exists. Reset the demo or use a new id.")
        o = OrderRow(id=oid, base_id=sc["order_id"], buyer=sc["buyer"], plant=sc["plant"],
                     requester_user=requester, raw_request=raw_text.strip(),
                     stage_times={"REQUEST": now_iso()})
        s.add(o)
        for vid, v in scenario()["vendors"].items():
            s.add(VendorRow(order_id=oid, vendor_id=vid, legal_name=v["legal_name"],
                            status=(VendorStatus.ACTIVE if v.get("has_room") else VendorStatus.NO_ROOM).value,
                            agent_name=v.get("agent"), negotiator=v.get("negotiator")))
        s.flush()
        _audit(s, oid, actor, AuditKind.REQUEST_POSTED,
               f"{persona(requester).get('name', requester)} posted a purchase request in the order room.",
               raw_text=raw_text.strip(), switch_message_id=switch_message_id)
        s.commit()
    bus.publish("order.created", oid)
    return order_view(oid)


def set_spec(order_id: str, spec: dict[str, Any], *, actor: str) -> dict[str, Any]:
    sp = Spec(**spec)
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.DRAFT.value:
            raise Conflict("The spec can only be drafted while the order is a DRAFT.")
        o.spec = sp.model_dump()
        o.spec_confirmed = False
        s.add(o)
        _audit(s, order_id, actor, AuditKind.SPEC_DRAFTED,
               f"Intake drafted the spec: {indian_group(sp.quantity)} {sp.uom} of {sp.part_name}, "
               f"needed by {sp.needed_by}.", spec=sp.model_dump())
        s.commit()
    bus.publish("order.spec", order_id, spec=sp.model_dump())
    return order_view(order_id)


def confirm_spec(order_id: str, *, by_user: str, actor: str, switch_message_id: str | None = None) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        if not o.spec:
            raise Conflict("There is no drafted spec to confirm.")
        if by_user != o.requester_user:
            raise CoreError(f"Only the requester ({o.requester_user}) can confirm the spec.", status=403)
        spec = dict(o.spec)
        spec["confirmed_by"] = by_user
        o.spec = spec
        o.spec_confirmed = True
        _set_state(s, o, OrderState.SPEC_CONFIRMED, actor)
        _audit(s, order_id, actor, AuditKind.SPEC_CONFIRMED,
               f"{persona(by_user).get('name', by_user)} confirmed the spec in Switch.",
               by=by_user, switch_message_id=switch_message_id)
        s.commit()
    return order_view(order_id)


def open_rfq(order_id: str, *, rooms: dict[str, str], actor: str) -> dict[str, Any]:
    """rooms: {"order": room_id, "deccan": room_id, ...} — real Switch room ids."""
    with db.session() as s:
        o = _order(s, order_id)
        merged = dict(o.rooms or {})
        merged.update(rooms)
        o.rooms = merged
        vendors = _vendors(s, order_id)
        for vid, rid in rooms.items():
            if vid in vendors:
                vendors[vid].room_id = rid
                s.add(vendors[vid])
        _set_state(s, o, OrderState.RFQ_OPEN, actor)
        sealed = [vendors[v].legal_name for v in rooms if v in vendors]
        _audit(s, order_id, actor, AuditKind.ROOMS_OPENED,
               f"Opened {len(sealed)} sealed vendor rooms in Switch: {', '.join(sealed)}.", rooms=rooms)
        s.commit()
    bus.publish("order.rooms", order_id, rooms=rooms)
    return order_view(order_id)


def register_rooms(order_id: str, rooms: dict[str, str]) -> None:
    """Record room ids without a state change (bootstrap / re-runs)."""
    with db.session() as s:
        o = _order(s, order_id)
        merged = dict(o.rooms or {})
        merged.update(rooms)
        o.rooms = merged
        s.add(o)
        vendors = _vendors(s, order_id)
        for vid, rid in rooms.items():
            if vid in vendors:
                vendors[vid].room_id = rid
                s.add(vendors[vid])
        s.commit()


# ----------------------------------------------------------------------------- quotes
def add_quote(order_id: str, *, vendor_id: str, filename: str, content: bytes, via: str,
              actor: str, switch_message_id: str | None = None) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        vendors = _vendors(s, order_id)
        if vendor_id not in vendors:
            raise NotFound(f"Unknown vendor {vendor_id}.")
        if o.state not in (OrderState.RFQ_OPEN.value, OrderState.QUOTES_RECEIVED.value):
            raise Conflict(f"Quotes are accepted only while the RFQ is open (order is {o.state}).")
        qid = f"Q-{vendor_id}-{uuid.uuid4().hex[:6]}"
        folder = generated_dir() / order_id / "quotes"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-") or "quote.pdf"
        path = folder / f"{qid}-{safe}"
        path.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        q = QuoteRow(id=qid, order_id=order_id, vendor_id=vendor_id, source_file=str(path.relative_to(ROOT)),
                     source_sha256=sha, received_via=via)
        s.add(q)
        _audit(s, order_id, actor, AuditKind.QUOTE_RECEIVED,
               f"Received {vendors[vendor_id].legal_name}'s quote ({safe}, via {via.replace('_', ' ')}).",
               quote_id=qid, vendor_id=vendor_id, sha256=sha, switch_message_id=switch_message_id)
        expected = set(vendors)
        got = {x.vendor_id for x in _quotes(s, order_id)} | {vendor_id}
        if o.state == OrderState.RFQ_OPEN.value and expected <= got:
            _set_state(s, o, OrderState.QUOTES_RECEIVED, actor)
        s.commit()
    bus.publish("quote.received", order_id, quote_id=qid, vendor_id=vendor_id)
    return {"quote_id": qid, "sha256": sha}


def parse_quote(order_id: str, quote_id: str, *, actor: str, use_llm: bool = True) -> dict[str, Any]:
    from . import parsing  # local import: heavy deps (pdfplumber, pymupdf, openai)

    with db.session() as s:
        o = _order(s, order_id)
        q = s.get(QuoteRow, quote_id)
        if not q or q.order_id != order_id:
            raise NotFound(f"Quote {quote_id} not found.")
        src = ROOT / q.source_file
        vendor_name = _vendors(s, order_id)[q.vendor_id].legal_name
    result = parsing.parse_quote_pdf(src, vendor_hint=vendor_name, use_llm=use_llm)
    with db.session() as s:
        o = _order(s, order_id)
        q = s.get(QuoteRow, quote_id)
        f = result.fields
        q.parsed = True
        q.quote_ref = f.get("quote_ref") or ""
        q.unit_price_paise = f.get("unit_price_paise")
        q.basis = f.get("basis")
        q.freight_paise_per_unit = f.get("freight_paise_per_unit")
        q.moq = f.get("moq")
        q.lead_time_days = f.get("lead_time_days")
        q.valid_until = f.get("valid_until")
        q.payment_terms_days = f.get("payment_terms_days")
        q.extraction_confidence = result.confidence
        q.extraction_method = result.method
        q.fields_missing = result.missing
        q.evidence = result.evidence
        q.injection_verdict = result.injection.verdict
        q.injection_confidence = result.injection.confidence
        q.injection_spans = result.injection.spans
        q.injection_detail = result.injection.detail
        facts = QuoteFacts(vendor_id=q.vendor_id, unit_price_paise=q.unit_price_paise, basis=q.basis,
                           freight_paise_per_unit=q.freight_paise_per_unit, moq=q.moq,
                           lead_time_days=q.lead_time_days,
                           valid_until=date.fromisoformat(q.valid_until) if q.valid_until else None,
                           payment_terms_days=q.payment_terms_days, injection_verdict=q.injection_verdict,
                           injection_spans=q.injection_spans, evidence=q.evidence)
        tr = evaluate(facts, quantity=o.spec["quantity"], needed_by=_needed_by(o), today=scenario_date())
        q.traps = [t.model_dump(mode="json") for t in tr.traps]
        q.comparable = tr.comparable
        q.landed_unit_paise = tr.landed_unit_paise
        q.landed_total_paise = tr.landed_total_paise
        s.add(q)
        vendors = _vendors(s, order_id)
        vname = vendors[q.vendor_id].legal_name
        _audit(s, order_id, actor, AuditKind.QUOTE_PARSED,
               f"Parsed {vname}'s quote: {fmt_unit(q.unit_price_paise) if q.unit_price_paise else '—'}/pc "
               f"{(q.basis or '').replace('_', '-').lower()}, MOQ {indian_group(q.moq) if q.moq else '—'}, "
               f"lead {q.lead_time_days or '—'} d (confidence {q.extraction_confidence:.0%}).",
               quote_id=q.id, vendor_id=q.vendor_id, method=q.extraction_method)
        for t in tr.traps:
            if t.code.value == "INJECTION":
                continue
            _audit(s, order_id, actor, AuditKind.TRAP_FOUND, f"{vname}: {t.message}",
                   vendor_id=q.vendor_id, code=t.code.value, severity=t.severity.value,
                   evidence=t.evidence.model_dump())
        if q.injection_verdict == InjectionVerdict.INJECTION.value:
            v = vendors[q.vendor_id]
            v.status = VendorStatus.DISQUALIFIED.value
            v.status_reason = "Prompt injection in quote document"
            s.add(v)
            _audit(s, order_id, actor, AuditKind.INJECTION_BLOCKED,
                   f"Blocked a prompt-injection attack hidden in {vname}'s quote "
                   f"(confidence {q.injection_confidence:.0%}).",
                   vendor_id=q.vendor_id, spans=q.injection_spans, detail=q.injection_detail)
            _audit(s, order_id, actor, AuditKind.VENDOR_DISQUALIFIED,
                   f"{vname} disqualified: its document tried to instruct our agents.", vendor_id=q.vendor_id)
            bus.publish("vendor.disqualified", order_id, vendor_id=q.vendor_id, reason=v.status_reason)
        s.commit()
        out = q.model_dump()
    bus.publish("quote.parsed", order_id, quote_id=quote_id, vendor_id=out["vendor_id"],
                verdict=out["injection_verdict"])
    return out


def comparison(order_id: str) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        quotes = [q.model_dump() for q in _quotes(s, order_id) if q.parsed]
        vendors = {k: v.model_dump() for k, v in _vendors(s, order_id).items()}
        return compare.build(quotes, vendors, quantity=o.spec.get("quantity", 0)) | {"order_id": order_id}


def publish_comparison(order_id: str, *, actor: str) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        quotes = _quotes(s, order_id)
        if not quotes or not all(q.parsed for q in quotes):
            raise Conflict("Every received quote must be parsed before the comparison is published.")
        if o.state == OrderState.RFQ_OPEN.value:
            _set_state(s, o, OrderState.QUOTES_RECEIVED, actor)
        _set_state(s, o, OrderState.COMPARED, actor)
        s.commit()
    cmp = comparison(order_id)
    with db.session() as s:
        best = cmp["rows"][0] if cmp["rows"] else None
        _audit(s, order_id, actor, AuditKind.COMPARISON_PUBLISHED,
               f"Published the quote comparison: best valid quote "
               f"{best['vendor'] + ' ' + fmt_unit(best['landed_unit_paise']) if best and best['rank'] else 'none'}; "
               f"{cmp['traps_caught']} trap(s) caught, {cmp['injections_blocked']} injection(s) blocked.",
               best_vendor_id=cmp["best_vendor_id"], best_landed_total_paise=cmp["best_landed_total_paise"])
        s.commit()
    bus.publish("comparison.published", order_id, comparison=cmp)
    return cmp


# ----------------------------------------------------------------------------- negotiation
def start_negotiation(order_id: str, *, actor: str) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        _set_state(s, o, OrderState.NEGOTIATING, actor)
        active = [v.legal_name for v in _vendors(s, order_id).values() if v.status == VendorStatus.ACTIVE.value]
        _audit(s, order_id, actor, AuditKind.NEGOTIATION_STARTED,
               f"Parallel negotiations started in {len(active)} sealed rooms: {', '.join(active)}.")
        s.commit()
    bus.publish("negotiation.started", order_id)
    return order_view(order_id)


def _sources(s: Session, o: OrderRow) -> list[Source]:
    """Every price the buyer genuinely holds: valid comparable quotes + each vendor's latest offer at our qty."""
    vendors = _vendors(s, o.id)
    out: list[Source] = []
    for q in _quotes(s, o.id):
        v = vendors[q.vendor_id]
        if q.parsed and q.comparable and v.status != VendorStatus.DISQUALIFIED.value and q.landed_unit_paise:
            out.append(Source(ref=q.id, vendor_id=q.vendor_id, landed_unit_paise=q.landed_unit_paise, kind="quote"))
    qty = o.spec.get("quantity", 0)
    for vid, v in vendors.items():
        if v.status == VendorStatus.DISQUALIFIED.value:
            continue
        offers = [x for x in _offers(s, o.id, vid) if x.side == Side.VENDOR.value and x.unit_price_paise
                  and x.quantity >= qty and x.status != OfferStatus.EXPIRED.value]
        if offers:
            last = offers[-1]
            out.append(Source(ref=last.id, vendor_id=vid, kind="offer",
                              landed_unit_paise=_landed(last.unit_price_paise, last.basis, _freight(s, o.id, vid))))
    return out


def _freight(s: Session, order_id: str, vendor_id: str) -> Optional[int]:
    for q in _quotes(s, order_id):
        if q.vendor_id == vendor_id:
            return q.freight_paise_per_unit
    return None


def negotiation_state(order_id: str, vendor_id: str) -> dict[str, Any]:
    """Everything a negotiator needs to decide (and Core's recommended next move)."""
    with db.session() as s:
        o = _order(s, order_id)
        vendors = _vendors(s, order_id)
        if vendor_id not in vendors:
            raise NotFound(f"Unknown vendor {vendor_id}.")
        v = vendors[vendor_id]
        qty = o.spec["quantity"]
        quote = next((q for q in _quotes(s, order_id) if q.vendor_id == vendor_id), None)
        offers = _offers(s, order_id, vendor_id)
        vendor_offers = [x for x in offers if x.side == Side.VENDOR.value and x.unit_price_paise]
        buyer_offers = [x for x in offers if x.side == Side.BUYER.value and x.verification == Verification.APPROVED.value]
        freight = quote.freight_paise_per_unit if quote else None
        if vendor_offers:
            last = vendor_offers[-1]
            vendor_offer = _landed(last.unit_price_paise, last.basis, freight) if last.quantity >= qty else None
            vendor_final = last.is_final
            last_vendor_offer_id = last.id
        elif quote and quote.comparable:
            vendor_offer, vendor_final, last_vendor_offer_id = quote.landed_unit_paise, False, quote.id
        else:
            vendor_offer, vendor_final, last_vendor_offer_id = None, False, None
        sources = _sources(s, o)
        competing = [x for x in sources if x.vendor_id != vendor_id]
        competing_paise = min((x.landed_unit_paise for x in competing), default=None)
        valid_quotes = [x.landed_unit_paise for x in sources if x.kind == "quote"]
        best_valid_quote = min(valid_quotes) if valid_quotes else None
        prev_ask = next((x.unit_price_paise for x in reversed(buyer_offers) if x.unit_price_paise), None)
        round_no = len(buyer_offers) + 1
        pol = scenario().get("negotiation", {})
        policy = BuyerPolicy(max_rounds=pol.get("max_rounds", 4),
                             target_discount=pol.get("target_discount_vs_best_quote", 0.08),
                             undercut_competing_paise=pol.get("undercut_competing_by_paise", 50),
                             opening_below_target_paise=pol.get("opening_below_target_paise", 120),
                             concession_per_round_paise=pol.get("concession_per_round_paise", 40))
        accepted = any(x.status == OfferStatus.ACCEPTED.value for x in vendor_offers)
        concluded = accepted or v.status in (VendorStatus.DISQUALIFIED.value, VendorStatus.CLOSED.value)
        move = None
        if not concluded and v.status == VendorStatus.ACTIVE.value:
            move = buyer_next_move(round_no=round_no, vendor_offer_paise=vendor_offer, vendor_is_final=vendor_final,
                                   vendor_quote_comparable=bool(quote and quote.comparable),
                                   best_valid_quote_paise=best_valid_quote, competing_paise=competing_paise,
                                   previous_ask_paise=prev_ask, p=policy).__dict__
        return {
            "order_id": order_id, "vendor_id": vendor_id, "vendor_name": v.legal_name,
            "vendor_status": v.status, "room_id": v.room_id, "quantity": qty, "round": round_no,
            "vendor_offer_paise": vendor_offer, "vendor_offer_id": last_vendor_offer_id,
            "vendor_is_final": vendor_final, "previous_ask_paise": prev_ask,
            "competing_paise": competing_paise, "best_valid_quote_paise": best_valid_quote,
            "quote": quote.model_dump() if quote else None, "concluded": concluded, "accepted": accepted,
            "has_competing_offer": any(x.kind == "offer" for x in competing),
            "move": move, "needed_by": o.spec.get("needed_by"), "delivery": o.spec.get("delivery_terms"),
            "order_state": o.state,
        }


def _outbound_context(s: Session, o: OrderRow, vendor_id: str, ask_paise: Optional[int]) -> OutboundContext:
    vendors = _vendors(s, o.id)
    own = {x.unit_price_paise for x in _offers(s, o.id, vendor_id) if x.unit_price_paise}
    q = next((q for q in _quotes(s, o.id) if q.vendor_id == vendor_id), None)
    if q:
        own |= {p for p in (q.unit_price_paise, q.landed_unit_paise, q.freight_paise_per_unit) if p}
    if ask_paise:
        own.add(ask_paise)
    forbidden: list[str] = []
    for vid, v in vendors.items():
        if vid == vendor_id:
            continue
        pub = vendor_public(vid)
        forbidden += [v.legal_name, pub.get("short", ""), *(x for x in (v.agent_name, v.negotiator) if x)]
        oq = next((x for x in _quotes(s, o.id) if x.vendor_id == vid), None)
        if oq and oq.quote_ref:
            forbidden.append(oq.quote_ref)
    forbidden = [f for f in forbidden if f and len(f) >= 4]
    tol = scenario().get("negotiation", {}).get("price_tolerance_paise", 1)
    return OutboundContext(target_vendor_id=vendor_id, quantity=o.spec["quantity"], sources=_sources(s, o),
                           own_prices_paise=own, forbidden_terms=forbidden, tolerance_paise=tol)


def outbound(order_id: str, vendor_id: str, *, message_text: str, action: str, ask_paise: Optional[int],
             claims: list[dict[str, Any]], actor: str, redteam: bool = False) -> dict[str, Any]:
    """Verify a buyer message BEFORE it is posted to the vendor's Switch room."""
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.NEGOTIATING.value:
            raise Conflict(f"Negotiation is not open (order is {o.state}).")
        ctx = _outbound_context(s, o, vendor_id, ask_paise)
        parsed_claims = [LeverageClaim(**c) for c in claims]
        verdict = check_outbound(message_text, parsed_claims, ctx)
        vendor_name = _vendors(s, order_id)[vendor_id].legal_name
        buyer_rounds = len([x for x in _offers(s, order_id, vendor_id) if x.side == Side.BUYER.value
                            and x.verification == Verification.APPROVED.value])
        offer = OfferRow(id=f"O-{uuid.uuid4().hex[:8]}", order_id=order_id, vendor_id=vendor_id,
                         round=buyer_rounds + 1, side=Side.BUYER.value, unit_price_paise=ask_paise,
                         basis=Basis.DELIVERED.value, quantity=o.spec["quantity"], conditions=action,
                         claims=[c.model_dump(mode="json") for c in verdict.claims],
                         verification=(Verification.APPROVED if verdict.approved else Verification.BLOCKED).value,
                         message_text=message_text, redteam=redteam)
        s.add(offer)
        if verdict.approved:
            for c in verdict.claims:
                _audit(s, order_id, actor, AuditKind.LEVERAGE_VERIFIED,
                       f"Verified leverage for {vendor_name}: a competing offer at {fmt_unit(c.unit_price_paise)} "
                       f"exists in the ledger (cited anonymously).", vendor_id=vendor_id,
                       unit_price_paise=c.unit_price_paise)
            if action == "accept":
                last = next((x for x in reversed(_offers(s, order_id, vendor_id)) if x.side == Side.VENDOR.value
                             and x.unit_price_paise), None)
                if last is None:
                    raise Conflict("There is no vendor offer to accept.")
                last.status = OfferStatus.ACCEPTED.value
                s.add(last)
                _audit(s, order_id, actor, AuditKind.OFFER_ACCEPTED,
                       f"Accepted {vendor_name}'s offer of {fmt_unit(last.unit_price_paise)}/pc in principle "
                       f"(subject to award and approvals).", vendor_id=vendor_id, offer_id=last.id,
                       unit_price_paise=last.unit_price_paise)
            elif action == "walk_away":
                v = _vendors(s, order_id)[vendor_id]
                v.status = VendorStatus.CLOSED.value
                v.status_reason = "Final offer did not beat a verified alternative"
                s.add(v)
            else:
                _audit(s, order_id, actor, AuditKind.OFFER_SENT,
                       f"Sent {vendor_name} a {'counter at ' + fmt_unit(ask_paise) if ask_paise else 'request'} "
                       f"(round {offer.round}).", vendor_id=vendor_id, unit_price_paise=ask_paise,
                       round=offer.round)
        else:
            _audit(s, order_id, actor, AuditKind.LEVERAGE_BLOCKED,
                   f"Blocked a message to {vendor_name} before it reached Switch"
                   f"{' (red-team test)' if redteam else ''}: {verdict.reasons[0]}",
                   vendor_id=vendor_id, reasons=verdict.reasons, redteam=redteam, message_text=message_text)
        s.commit()
        out = verdict.as_dict() | {"offer_id": offer.id, "round": offer.round}
    bus.publish("negotiation.outbound", order_id, vendor_id=vendor_id, approved=out["approved"],
                reasons=out["reasons"], ask_paise=ask_paise, action=action, redteam=redteam,
                message_text=message_text)
    if out["approved"] and action in ("accept", "walk_away"):
        _maybe_close(order_id, actor)
    return out


def attach_switch_message(order_id: str, offer_id: str, switch_message_id: str) -> None:
    with db.session() as s:
        x = s.get(OfferRow, offer_id)
        if x and x.order_id == order_id:
            x.switch_message_id = switch_message_id
            s.add(x)
            s.commit()


def inbound(order_id: str, vendor_id: str, *, unit_price_paise: int, basis: str, quantity: int, is_final: bool,
            message_text: str, actor: str, switch_message_id: str | None = None,
            conditions: str = "") -> dict[str, Any]:
    """Register a vendor offer the buyer's negotiator read from the vendor's Switch message."""
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.NEGOTIATING.value:
            raise Conflict(f"Negotiation is not open (order is {o.state}).")
        prior = [x for x in _offers(s, order_id, vendor_id) if x.side == Side.VENDOR.value
                 and x.status == OfferStatus.PROPOSED.value]
        for p in prior:
            p.status = OfferStatus.COUNTERED.value
            s.add(p)
        rnd = len([x for x in _offers(s, order_id, vendor_id) if x.side == Side.VENDOR.value]) + 1
        offer = OfferRow(id=f"O-{uuid.uuid4().hex[:8]}", order_id=order_id, vendor_id=vendor_id, round=rnd,
                         side=Side.VENDOR.value, unit_price_paise=unit_price_paise, basis=basis,
                         quantity=quantity, is_final=is_final, message_text=message_text,
                         switch_message_id=switch_message_id, conditions=conditions)
        s.add(offer)
        vname = _vendors(s, order_id)[vendor_id].legal_name
        _audit(s, order_id, actor, AuditKind.OFFER_RECEIVED,
               f"{vname} offered {fmt_unit(unit_price_paise)}/pc {basis.replace('_', '-').lower()} for "
               f"{indian_group(quantity)} pcs{' (final offer)' if is_final else ''}.", vendor_id=vendor_id,
               unit_price_paise=unit_price_paise, basis=basis, quantity=quantity, is_final=is_final,
               switch_message_id=switch_message_id)
        s.commit()
        out = offer.model_dump()
    bus.publish("negotiation.inbound", order_id, vendor_id=vendor_id, unit_price_paise=unit_price_paise,
                is_final=is_final, basis=basis)
    return out


def vendor_approval(order_id: str, vendor_id: str, *, stage: str, unit_price_paise: int, actor: str,
                    decision: str | None = None, decided_by_user: str | None = None,
                    mechanism: str = Mechanism.SWITCH_MESSAGE_FALLBACK.value, switch_ref: str | None = None,
                    agent_name: str = "") -> dict[str, Any]:
    """stage = 'requested' | 'decided'. Vendor-side approvals are the vendor's own business; Core records
    them for the audit trail and the Control Room."""
    with db.session() as s:
        _order(s, order_id)
        vname = _vendors(s, order_id)[vendor_id].legal_name
        owner = vendor_public(vendor_id).get("contact_persona")
        if stage == "requested":
            _audit(s, order_id, actor, AuditKind.VENDOR_APPROVAL_REQUESTED,
                   f"{vname}'s agent asked its owner ({persona(owner).get('name', owner)}) in Switch for approval to go "
                   f"to {fmt_unit(unit_price_paise)}.", vendor_id=vendor_id, unit_price_paise=unit_price_paise,
                   mechanism=mechanism)
            s.commit()
            bus.publish("vendor.approval_requested", order_id, vendor_id=vendor_id,
                        unit_price_paise=unit_price_paise, owner=owner, mechanism=mechanism)
            return {"ok": True}
        if decision not in (Decision.APPROVED.value, Decision.DECLINED.value):
            raise CoreError("decision must be APPROVED or DECLINED")
        if decided_by_user != owner:
            raise CoreError(f"Only {owner} can decide for {vname}.", status=403)
        row = ApprovalRow(id=f"A-{uuid.uuid4().hex[:8]}", order_id=order_id,
                          kind=ApprovalKind.VENDOR_BELOW_LINE.value, decision=decision,
                          decided_by_user=decided_by_user, mechanism=mechanism, agent_name=agent_name,
                          vendor_id=vendor_id, unit_price_paise=unit_price_paise, switch_ref=switch_ref)
        s.add(row)
        _audit(s, order_id, actor, AuditKind.VENDOR_APPROVAL_DECIDED,
               f"{persona(owner).get('name', owner)} {decision.lower()} going to {fmt_unit(unit_price_paise)} "
               f"for {vname}.", vendor_id=vendor_id, decision=decision, mechanism=mechanism,
               switch_ref=switch_ref)
        s.commit()
    bus.publish("vendor.approval_decided", order_id, vendor_id=vendor_id, decision=decision,
                unit_price_paise=unit_price_paise, owner=owner, mechanism=mechanism)
    return {"ok": True, "approval_id": row.id}


def _maybe_close(order_id: str, actor: str) -> None:
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.NEGOTIATING.value:
            return
        vendors = _vendors(s, order_id)
        pending = []
        for vid, v in vendors.items():
            if v.status != VendorStatus.ACTIVE.value:
                continue
            accepted = any(x.status == OfferStatus.ACCEPTED.value for x in _offers(s, order_id, vid))
            if not accepted:
                pending.append(vid)
    if not pending:
        close_negotiation(order_id, actor=actor)


def close_negotiation(order_id: str, *, actor: str) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        if o.state == OrderState.NEGOTIATING.value:
            _set_state(s, o, OrderState.NEGOTIATION_CLOSED, actor)
        elif o.state != OrderState.NEGOTIATION_CLOSED.value:
            raise Conflict(f"Cannot close negotiation from {o.state}.")
        vendors = _vendors(s, order_id)
        accepted = []
        for x in _offers(s, order_id):
            if x.side == Side.VENDOR.value and x.status == OfferStatus.ACCEPTED.value \
                    and vendors[x.vendor_id].status != VendorStatus.DISQUALIFIED.value:
                accepted.append((_landed(x.unit_price_paise, x.basis, _freight(s, order_id, x.vendor_id)), x))
        _audit(s, order_id, actor, AuditKind.NEGOTIATION_CLOSED,
               f"Negotiations closed with {len(accepted)} acceptable offer(s).")
        if not accepted:
            s.commit()
            return order_view(order_id)
        accepted.sort(key=lambda t: t[0])
        landed, win = accepted[0]
        for _, other in accepted[1:]:
            other.status = OfferStatus.REJECTED.value
            s.add(other)
        total = win.unit_price_paise * win.quantity
        tier = approvals.tier_for(total)
        o.awarded_vendor_id = win.vendor_id
        o.awarded_offer_id = win.id
        o.tier = tier.name
        _set_state(s, o, OrderState.AWARDED, actor)
        cmp_best = compare.build([q.model_dump() for q in _quotes(s, order_id) if q.parsed],
                                 {k: v.model_dump() for k, v in vendors.items()}, quantity=win.quantity)
        baseline = cmp_best["best_landed_total_paise"]
        saved = (baseline - total) if baseline else 0
        _audit(s, order_id, actor, AuditKind.AWARDED,
               f"Provisional award: {vendors[win.vendor_id].legal_name} at {fmt_unit(win.unit_price_paise)} × "
               f"{indian_group(win.quantity)} = {fmt_inr(total)} (excl. GST). Approval tier: {tier.label}.",
               vendor_id=win.vendor_id, offer_id=win.id, total_paise=total, tier=tier.name,
               approvers=list(tier.approvers), saved_paise=saved)
        s.commit()
    bus.publish("order.awarded", order_id, vendor_id=win.vendor_id, total_paise=total, tier=tier.name)
    if not tier.approvers:
        _auto_issue(order_id)
    return order_view(order_id)


# ----------------------------------------------------------------------------- approvals (gate agents)
def request_endorsement(order_id: str, *, actor: str, switch_message_id: str | None = None) -> None:
    with db.session() as s:
        o = _order(s, order_id)
        _audit(s, order_id, actor, AuditKind.ENDORSEMENT_REQUESTED,
               f"Asked @purchase-desk to obtain Meera's endorsement for the award ({o.tier}).",
               switch_message_id=switch_message_id)
        s.commit()
    bus.publish("approval.requested", order_id, step="purchase_head")


def endorse(order_id: str, *, caller_kind: str, agent_name: str = "purchase-desk", note: str = "") -> dict[str, Any]:
    """Runs only after Meera tapped Allow on the Switch permission request (the MCP tool executes then)."""
    if caller_kind != "mcp_purchase_desk":
        raise CoreError("Only the purchase-desk agent may endorse.", status=403)
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.AWARDED.value:
            raise Conflict(f"Nothing to endorse: order is {o.state}.")
        v = _vendors(s, order_id)[o.awarded_vendor_id]
        if v.status == VendorStatus.DISQUALIFIED.value:
            raise Conflict("The awarded vendor is disqualified.")
        approver = APPROVER_FOR_AGENT.get(agent_name, "meera")
        row = ApprovalRow(id=f"A-{uuid.uuid4().hex[:8]}", order_id=order_id,
                          kind=ApprovalKind.PURCHASE_HEAD_ENDORSEMENT.value, decision=Decision.APPROVED.value,
                          decided_by_user=approver, mechanism=Mechanism.SWITCH_PERMISSION.value,
                          agent_name=agent_name, note=note)
        s.add(row)
        _set_state(s, o, OrderState.ENDORSED_PURCHASE_HEAD, f"agent:{agent_name}")
        _audit(s, order_id, f"agent:{agent_name}", AuditKind.ENDORSED,
               f"{persona(approver).get('name')} (Purchase Head) endorsed the award by allowing "
               f"@{agent_name}'s Switch permission request.", approval_id=row.id, note=note,
               mechanism=row.mechanism)
        s.commit()
    bus.publish("approval.decided", order_id, step="purchase_head", decision="APPROVED", by=approver)
    return order_view(order_id)


def endorse_declined(order_id: str, *, caller_kind: str, agent_name: str = "purchase-desk", note: str = "") -> dict[str, Any]:
    if caller_kind not in ("mcp_purchase_desk", "agents", "director"):
        raise CoreError("Not allowed.", status=403)
    with db.session() as s:
        o = _order(s, order_id)
        if o.state != OrderState.AWARDED.value:
            raise Conflict(f"Nothing to decline: order is {o.state}.")
        approver = APPROVER_FOR_AGENT.get(agent_name, "meera")
        row = ApprovalRow(id=f"A-{uuid.uuid4().hex[:8]}", order_id=order_id,
                          kind=ApprovalKind.PURCHASE_HEAD_ENDORSEMENT.value, decision=Decision.DECLINED.value,
                          decided_by_user=approver, mechanism=Mechanism.SWITCH_PERMISSION.value,
                          agent_name=agent_name, note=note)
        s.add(row)
        o.awarded_vendor_id = None
        o.awarded_offer_id = None
        _set_state(s, o, OrderState.NEGOTIATION_CLOSED, f"agent:{agent_name}")
        _audit(s, order_id, f"agent:{agent_name}", AuditKind.ENDORSEMENT_DECLINED,
               f"{persona(approver).get('name')} declined the endorsement in Switch. Nobody can issue a PO.",
               note=note)
        s.commit()
    bus.publish("approval.decided", order_id, step="purchase_head", decision="DECLINED", by=approver)
    return order_view(order_id)


def po_declined(order_id: str, *, caller_kind: str, agent_name: str = "po-issuer", note: str = "") -> dict[str, Any]:
    with db.session() as s:
        _order(s, order_id)
        approver = APPROVER_FOR_AGENT.get(agent_name, "vikram")
        s.add(ApprovalRow(id=f"A-{uuid.uuid4().hex[:8]}", order_id=order_id, kind=ApprovalKind.FINANCE_RELEASE.value,
                          decision=Decision.DECLINED.value, decided_by_user=approver,
                          mechanism=Mechanism.SWITCH_PERMISSION.value, agent_name=agent_name, note=note))
        _audit(s, order_id, f"agent:{agent_name}", AuditKind.PO_DECLINED,
               f"{persona(approver).get('name')} declined the PO release in Switch. No PO was issued.", note=note)
        s.commit()
    bus.publish("approval.decided", order_id, step="finance", decision="DECLINED", by=approver)
    return order_view(order_id)


def _gate_facts(s: Session, o: OrderRow, caller_kind: str, requested_vendor_id: str | None) -> tuple[GateFacts, Optional[OfferRow]]:
    vendors = _vendors(s, o.id)
    offer = s.get(OfferRow, o.awarded_offer_id) if o.awarded_offer_id else None
    target_vendor = requested_vendor_id or o.awarded_vendor_id
    v = vendors.get(target_vendor) if target_vendor else None
    quote = next((q for q in _quotes(s, o.id) if q.vendor_id == target_vendor), None)
    tier = approvals.tier_by_name(o.tier) if o.tier else None
    endorsements = tuple(sorted({"purchase_head" for a in _approvals(s, o.id)
                                 if a.kind == ApprovalKind.PURCHASE_HEAD_ENDORSEMENT.value
                                 and a.decision == Decision.APPROVED.value}))
    total = offer.unit_price_paise * offer.quantity if offer and offer.unit_price_paise else None
    existing = s.exec(select(PurchaseOrderRow).where(PurchaseOrderRow.order_id == o.id)).first()
    facts = GateFacts(
        caller=caller_kind, order_state=o.state, tier_name=o.tier,
        tier_approvers=tier.approvers if tier else (), endorsements=endorsements,
        awarded_offer_status=offer.status if offer else None, awarded_vendor_id=o.awarded_vendor_id,
        requested_vendor_id=requested_vendor_id, vendor_status=v.status if v else None,
        quote_valid_until=date.fromisoformat(quote.valid_until) if quote and quote.valid_until else None,
        today=scenario_date(), unit_price_paise=offer.unit_price_paise if offer else None,
        quantity=offer.quantity if offer else None, total_paise=total,
        existing_po_id=existing.id if existing else None)
    return facts, offer


def issue_po(order_id: str, *, caller_kind: str, agent_name: str = "po-issuer",
             vendor_id: str | None = None, system: bool = False) -> dict[str, Any]:
    """Lock 3. Runs after Vikram allowed @po-issuer's Switch permission request, and still checks everything."""
    with db.session() as s:
        o = _order(s, order_id)
        facts, offer = _gate_facts(s, o, "mcp_po_issuer" if system else caller_kind, vendor_id)
        failed = gate_checks(facts)
        actor = "system:auto-tier" if system else f"agent:{agent_name}"
        _audit(s, order_id, actor, AuditKind.PO_REQUESTED,
               f"{'Auto-tier release' if system else '@' + agent_name + ' asked Mandi to issue the PO'}"
               f"{' for vendor ' + vendor_id if vendor_id else ''}.", vendor_id=vendor_id)
        if failed:
            _audit(s, order_id, actor, AuditKind.PO_REFUSED_BY_RULE,
                   f"Mandi's PO rules refused: {failed[0]}", failed=failed, caller=caller_kind)
            s.commit()
            bus.publish("po.refused", order_id, failed=failed)
            raise Conflict("Mandi refused to issue the PO.", details=failed)
        approver = None
        if not system:
            approver = APPROVER_FOR_AGENT.get(agent_name, "vikram")
            fin = ApprovalRow(id=f"A-{uuid.uuid4().hex[:8]}", order_id=order_id,
                              kind=ApprovalKind.FINANCE_RELEASE.value, decision=Decision.APPROVED.value,
                              decided_by_user=approver, mechanism=Mechanism.SWITCH_PERMISSION.value,
                              agent_name=agent_name)
            s.add(fin)
            if "finance" in facts.tier_approvers:
                _set_state(s, o, OrderState.ENDORSED_FINANCE, actor)
                _audit(s, order_id, actor, AuditKind.ENDORSED,
                       f"{persona(approver).get('name')} (Finance) released the order by allowing "
                       f"@{agent_name}'s Switch permission request.", approval_id=fin.id,
                       mechanism=fin.mechanism)
        s.flush()
        po_number = "PO-" + o.base_id.replace("SM-PR-", "SM-") if o.base_id else f"PO-{o.id}"
        if o.id != o.base_id and o.base_id:
            po_number += o.id[len(o.base_id):]
        vendors = _vendors(s, order_id)
        win = vendors[o.awarded_vendor_id]
        quote = next((q for q in _quotes(s, order_id) if q.vendor_id == win.vendor_id), None)
        total = offer.unit_price_paise * offer.quantity
        appr_rows = [a for a in _approvals(s, order_id) if a.decision == Decision.APPROVED.value
                     and a.kind in (ApprovalKind.PURCHASE_HEAD_ENDORSEMENT.value, ApprovalKind.FINANCE_RELEASE.value)]
        s.commit()
    # PO_ISSUED event first, so the PDF can carry the final audit hash.
    with db.session() as s:
        o = _order(s, order_id)
        sc = scenario()["order"]
        cmp = comparison(order_id)
        saved = (cmp["best_landed_total_paise"] or total) - total
        _set_state(s, o, OrderState.PO_ISSUED, actor)
        o.po_id = po_number
        s.add(o)
        _audit(s, order_id, actor, AuditKind.PO_ISSUED,
               f"Issued {po_number} to {win.legal_name}: {fmt_unit(offer.unit_price_paise)} × "
               f"{indian_group(offer.quantity)} = {fmt_inr(total)} (excl. GST).", po_id=po_number,
               vendor_id=win.vendor_id, total_paise=total, saved_paise=saved)
        head = audit.last_event(s)
        pdf_path = generated_dir() / order_id / f"{po_number}.pdf"
        from .pdf import render_po
        render_po(pdf_path, {
            "po_number": po_number, "date": scenario_date().strftime("%d %b %Y"), "order_id": order_id,
            "buyer": {"name": sc["buyer"], "address": sc["buyer_address"], "gstin": sc["buyer_gstin"],
                      "plant": sc["plant"]},
            "vendor": {"name": win.legal_name, "address": _vendor_address(win.vendor_id),
                       "gstin": _vendor_gstin(win.vendor_id),
                       "contact": persona(vendor_public(win.vendor_id).get("contact_persona") or "").get("name", "—")},
            "item": {"name": o.spec["part_name"], "spec": o.spec["part_spec"], "drawing": o.spec.get("drawing_ref", "")},
            "quantity": offer.quantity, "unit_paise": offer.unit_price_paise, "total_paise": total,
            "terms": {"delivery": o.spec.get("delivery_terms", ""), "lead_time_days": quote.lead_time_days if quote else "—",
                      "payment_terms_days": quote.payment_terms_days if quote else "—",
                      "needed_by": date.fromisoformat(o.spec["needed_by"]).strftime("%d %b %Y")},
            "approvals": [{"role": "Purchase Head" if a.kind == ApprovalKind.PURCHASE_HEAD_ENDORSEMENT.value else "Finance",
                           "name": persona(a.decided_by_user).get("name", a.decided_by_user),
                           "decision": "Approved",
                           "mechanism": "Switch permission request" if a.mechanism == Mechanism.SWITCH_PERMISSION.value
                           else a.mechanism.replace("_", " ").lower(),
                           "at": _ist(a.at)} for a in appr_rows]
                         or [{"role": "Auto-approve tier", "name": "—", "decision": "Approved",
                              "mechanism": "below threshold", "at": _ist(now_iso())}],
            "audit_hash": head.hash,
            "audit_url": f"{env('CORE_URL', 'http://127.0.0.1:8700')}/#audit",
        })
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        po = PurchaseOrderRow(id=po_number, order_id=order_id, vendor_id=win.vendor_id,
                              unit_price_paise=offer.unit_price_paise, quantity=offer.quantity, total_paise=total,
                              terms={"lead_time_days": quote.lead_time_days if quote else None,
                                     "payment_terms_days": quote.payment_terms_days if quote else None,
                                     "delivery": o.spec.get("delivery_terms")},
                              approvals=[a.id for a in appr_rows], pdf_path=str(pdf_path.relative_to(ROOT)),
                              sha256=sha, audit_hash=head.hash, issued_by_agent=actor)
        s.add(po)
        s.commit()
        out = po.model_dump()
    bus.publish("po.issued", order_id, po=out)
    return out


def _ist(iso: str) -> str:
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %H:%M IST")


def _auto_issue(order_id: str) -> None:
    try:
        issue_po(order_id, caller_kind="system", agent_name="auto-tier", system=True)
    except Conflict:
        pass


_VENDOR_ADDR = {
    "deccan": ("Gat No. 112, Bhosari Industrial Area, Pune 411026 (fictional)", "27AABCD0000D1Z2 (sample)"),
    "ganesh": ("Plot 7, SIPCOT Phase 1, Hosur 635126 (fictional)", "33AABCS0000G1Z8 (sample)"),
    "apex": ("Unit 4, Peenya 2nd Stage, Bengaluru 560058 (fictional)", "29AABCA0000P1Z1 (sample)"),
    "konkan": ("MIDC Lote Parshuram, Ratnagiri 415722 (fictional)", "27AABCK0000K1Z4 (sample)"),
}


def _vendor_address(vid: str) -> str:
    return _VENDOR_ADDR.get(vid, ("—", "—"))[0]


def _vendor_gstin(vid: str) -> str:
    return _VENDOR_ADDR.get(vid, ("—", "—"))[1]


def note_doc_saved(order_id: str, *, room_key: str, title: str, actor: str, document_id: str | None = None) -> None:
    with db.session() as s:
        _order(s, order_id)
        _audit(s, order_id, actor, AuditKind.DOC_SAVED_TO_ROOM,
               f"Saved “{title}” as a room document in the {room_key} room.", room_key=room_key, title=title,
               document_id=document_id)
        s.commit()


def note(order_id: str, *, kind: str, summary: str, actor: str, **data: Any) -> None:
    with db.session() as s:
        _order(s, order_id)
        _audit(s, order_id, actor, AuditKind(kind), summary, **data)
        s.commit()


# ----------------------------------------------------------------------------- views
def order_view(order_id: str, *, vendor_scope: str | None = None) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        vendors = _vendors(s, order_id)
        quotes = _quotes(s, order_id)
        offers = _offers(s, order_id)
        appr = _approvals(s, order_id)
        po = s.exec(select(PurchaseOrderRow).where(PurchaseOrderRow.order_id == order_id)).first()
        view = {
            "order": o.model_dump(),
            "vendors": [v.model_dump() for v in vendors.values()],
            "quotes": [q.model_dump() for q in quotes],
            "offers": [x.model_dump() for x in offers],
            "approvals": [a.model_dump() for a in appr],
            "po": po.model_dump() if po else None,
            "tier": approvals.tier_by_name(o.tier).__dict__ if o.tier else None,
        }
    if vendor_scope:  # sealed-bid: a vendor sees only its own rows, and nothing about awards/approvals
        view = {
            "order": {k: view["order"][k] for k in ("id", "buyer", "plant", "spec", "state")},
            "vendors": [v for v in view["vendors"] if v["vendor_id"] == vendor_scope],
            "quotes": [q for q in view["quotes"] if q["vendor_id"] == vendor_scope],
            "offers": [x for x in view["offers"] if x["vendor_id"] == vendor_scope],
            "approvals": [a for a in view["approvals"] if a.get("vendor_id") == vendor_scope],
            "po": None, "tier": None,
        }
    return view


def outcome(order_id: str) -> dict[str, Any]:
    with db.session() as s:
        o = _order(s, order_id)
        po = s.exec(select(PurchaseOrderRow).where(PurchaseOrderRow.order_id == order_id)).first()
        vendors = _vendors(s, order_id)
        appr = [a for a in _approvals(s, order_id) if a.decision == Decision.APPROVED.value
                and a.kind != ApprovalKind.VENDOR_BELOW_LINE.value]
        vendor_declines = [a for a in _approvals(s, order_id) if a.kind == ApprovalKind.VENDOR_BELOW_LINE.value]
        events = audit.all_events(s)
    cmp = comparison(order_id)
    out: dict[str, Any] = {"order_id": order_id, "state": o.state, "po": po.model_dump() if po else None}
    if po:
        baseline = cmp["best_landed_total_paise"] or po.total_paise
        saved = baseline - po.total_paise
        start = o.stage_times.get("REQUEST")
        end = o.stage_times.get("PO_ISSUED")
        secs = None
        if start and end:
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
            secs = int((datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds())
        out.update({
            "vendor": vendors[po.vendor_id].legal_name, "unit": fmt_unit(po.unit_price_paise),
            "quantity": po.quantity, "total": fmt_inr(po.total_paise), "total_paise": po.total_paise,
            "baseline_total_paise": baseline, "saved_paise": saved, "saved": fmt_inr(saved),
            "saved_pct": pct(saved, baseline), "lead_time_days": po.terms.get("lead_time_days"),
            "payment_terms_days": po.terms.get("payment_terms_days"),
            "traps": [r["vendor"] + ": " + t["code"] for r in cmp["rows"] for t in r["traps"]
                      if t["code"] in ("HIDDEN_MOQ", "EXPIRED", "LATE_DELIVERY", "FREIGHT_EXCLUDED")],
            "traps_caught": cmp["traps_caught"], "injections_blocked": cmp["injections_blocked"],
            "leverage_blocked": sum(1 for e in events if e.order_id == order_id and e.kind == "LEVERAGE_BLOCKED"),
            "approvals": [{"name": persona(a.decided_by_user).get("name"), "kind": a.kind, "mechanism": a.mechanism}
                          for a in appr],
            "vendor_decisions": [{"name": persona(a.decided_by_user).get("name"), "decision": a.decision,
                                  "unit": fmt_unit(a.unit_price_paise) if a.unit_price_paise else None}
                                 for a in vendor_declines],
            "elapsed_seconds": secs,
            "paper_process_days": scenario().get("baseline", {}).get("paper_process_days", "4-10"),
        })
    return out


def audit_view(order_id: str | None = None) -> dict[str, Any]:
    with db.session() as s:
        rows = audit.all_events(s)
    verdict = audit.verify_chain(rows)
    return {"verified": verdict, "events": [r.model_dump() for r in rows
                                            if order_id is None or r.order_id in (order_id, "*")]}


# ----------------------------------------------------------------------------- switch feed (from auditor)
def feed_add(items: list[dict[str, Any]]) -> int:
    n = 0
    with db.session() as s:
        for it in items:
            if it.get("message_id"):
                dup = s.exec(select(FeedRow).where(FeedRow.message_id == it["message_id"],
                                                   FeedRow.event == it.get("event", "message"))).first()
                if dup:
                    continue
            row = FeedRow(**{k: v for k, v in it.items() if k in FeedRow.model_fields and k != "id"})
            s.add(row)
            s.flush()
            n += 1
            bus.publish("switch.event", None, item=row.model_dump())
        s.commit()
    return n


def feed(limit: int = 300, room_key: str | None = None) -> list[dict[str, Any]]:
    with db.session() as s:
        q = select(FeedRow)
        if room_key:
            q = q.where(FeedRow.room_key == room_key)
        rows = list(s.exec(q.order_by(FeedRow.id.desc()).limit(limit)))
    return [r.model_dump() for r in reversed(rows)]


def reset(*, actor: str) -> None:
    db.configure(fresh=True)
    bus.clear()
    with db.session() as s:
        audit.append(s, order_id="*", actor=actor, kind=AuditKind.DEMO_RESET.value,
                     summary="Demo reset: fresh Mandi Core database.", data={})
        s.commit()
    bus.publish("demo.reset", None)


# ----------------------------------------------------------------------------- MOCK exports
def exports_enabled() -> bool:
    return env("MANDI_EXPORTS", "1").strip() != "0"


def comparative_statement(order_id: str) -> dict[str, Any]:
    from . import exports
    return exports.comparative_statement(order_view(order_id), comparison(order_id))


def po_export(order_id: str) -> dict[str, Any]:
    from . import exports
    view = order_view(order_id)
    if not view["po"]:
        raise NotFound("No PO issued yet.")
    issued = view["po"]["issued_at"][:10]
    return exports.po_export(view, scenario().get("po_export", {}), document_date=date.fromisoformat(issued))


def write_exports(order_id: str) -> dict[str, str]:
    """Write the MOCK exports next to the PO PDF. Returns {kind: path relative to ROOT}."""
    import json as _json

    from . import exports
    if not exports_enabled():
        raise CoreError("Exports are switched off (MANDI_EXPORTS=0).", status=404)
    folder = generated_dir() / order_id
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    st = folder / "comparative-statement-MOCK.csv"
    st.write_text(exports.statement_csv(comparative_statement(order_id)), encoding="utf-8")
    out["comparative_statement_csv"] = str(st.relative_to(ROOT))
    view = order_view(order_id)
    if view["po"]:
        exp = po_export(order_id)
        pj = folder / f"{view['po']['id']}-sap-style-MOCK.json"
        pj.write_text(_json.dumps(exp, indent=2, ensure_ascii=False), encoding="utf-8")
        pc = folder / f"{view['po']['id']}-sap-style-MOCK.csv"
        pc.write_text(exports.po_csv(exp), encoding="utf-8")
        out["po_json"] = str(pj.relative_to(ROOT))
        out["po_csv"] = str(pc.relative_to(ROOT))
    return out
