"""Append-only, hash-chained audit log.

Each event stores the previous event's hash and its own hash:
    hash = sha256(prev_hash | seq | at | order_id | actor | kind | summary | canonical_json(data))
Changing, deleting or reordering any past event breaks every hash after it, so
`verify_chain` can prove the log is intact. (Tamper-EVIDENT, not tamper-proof.)
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from sqlmodel import Session, select

from .models import AuditRow, now_iso

GENESIS = "0" * 64


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, seq: int, at: str, order_id: str, actor: str, kind: str,
                 summary: str, data: dict) -> str:
    material = "|".join([prev_hash, str(seq), at, order_id, actor, kind, summary, canonical(data)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def last_event(s: Session) -> AuditRow | None:
    return s.exec(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)).first()


def append(s: Session, *, order_id: str, actor: str, kind: str, summary: str,
           data: dict | None = None) -> AuditRow:
    """Append one event. Caller must hold the DB write lock (db.session() does)."""
    data = data or {}
    prev = last_event(s)
    prev_hash = prev.hash if prev else GENESIS
    seq = (prev.seq if prev else 0) + 1
    at = now_iso()
    row = AuditRow(seq=seq, at=at, order_id=order_id, actor=actor, kind=kind, summary=summary,
                   data=data, prev_hash=prev_hash)
    row.hash = compute_hash(prev_hash, seq, at, order_id, actor, kind, summary, data)
    s.add(row)
    s.flush()
    return row


def verify_chain(rows: Iterable[AuditRow]) -> dict[str, Any]:
    """Verify an ordered list of events (whole log). Returns {ok, checked, broken_at, reason}."""
    prev_hash = GENESIS
    expected_seq = None
    checked = 0
    for r in rows:
        if expected_seq is not None and r.seq != expected_seq:
            return {"ok": False, "checked": checked, "broken_at": r.seq, "reason": "sequence gap (event removed?)"}
        if r.prev_hash != prev_hash:
            return {"ok": False, "checked": checked, "broken_at": r.seq, "reason": "prev_hash mismatch"}
        h = compute_hash(r.prev_hash, r.seq, r.at, r.order_id, r.actor, r.kind, r.summary, r.data or {})
        if h != r.hash:
            return {"ok": False, "checked": checked, "broken_at": r.seq, "reason": "content changed"}
        prev_hash = r.hash
        expected_seq = r.seq + 1
        checked += 1
    return {"ok": True, "checked": checked, "broken_at": None, "reason": "", "head": prev_hash}


def all_events(s: Session) -> list[AuditRow]:
    return list(s.exec(select(AuditRow).order_by(AuditRow.seq)))
