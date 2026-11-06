"""SQLite persistence (SQLModel). One engine per process; tests point it at a temp file."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (registers tables)
from .config import data_dir

_engine = None
_lock = threading.RLock()  # serialises writes so the audit hash chain stays linear


def default_db_path() -> Path:
    return data_dir() / "mandi.db"


def configure(db_path: str | Path | None = None, *, fresh: bool = False):
    """(Re)create the engine. fresh=True drops all tables first (demo reset / tests)."""
    global _engine
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(_engine, "connect")
    def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    if fresh:
        SQLModel.metadata.drop_all(_engine)
    SQLModel.metadata.create_all(_engine)
    return _engine


def engine():
    if _engine is None:
        configure()
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    with _lock:
        with Session(engine(), expire_on_commit=False) as s:
            yield s


def write_lock() -> threading.RLock:
    return _lock
