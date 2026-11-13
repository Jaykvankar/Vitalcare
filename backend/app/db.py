from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _SessionLocal
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    _engine = create_engine(url, future=True, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def engine() -> Engine:
    assert _engine is not None, "init_engine() not called"
    return _engine


def SessionLocal() -> Session:  # noqa: N802
    assert _SessionLocal is not None, "init_engine() not called"
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_schema() -> None:
    from . import models  # noqa: F401  (register tables)

    eng = engine()
    Base.metadata.create_all(eng)
    _install_append_only_guards(eng)


def _install_append_only_guards(eng: Engine) -> None:
    """Database-level protection: audit rows can be inserted but never updated or deleted."""
    with eng.begin() as conn:
        if eng.dialect.name == "sqlite":
            for op in ("UPDATE", "DELETE"):
                conn.execute(text(
                    f"CREATE TRIGGER IF NOT EXISTS audit_no_{op.lower()} BEFORE {op} ON audit_log "
                    f"BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;"
                ))
        elif eng.dialect.name == "postgresql":
            conn.execute(text(
                "CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql;"
            ))
            conn.execute(text("DROP TRIGGER IF EXISTS audit_no_change ON audit_log"))
            conn.execute(text(
                "CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_log "
                "FOR EACH ROW EXECUTE FUNCTION audit_append_only();"
            ))
