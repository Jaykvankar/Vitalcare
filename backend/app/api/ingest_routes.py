from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..readings import ingest
from ..security import auth, server_keys
from ..security.hashing import b64e

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/server-key")
def server_key() -> dict:
    """Public values devices pin: the server's static DH public value (ffdhe3072)."""
    keys = server_keys.load_or_create()
    return {"group": "ffdhe3072", "dh_public": b64e(keys.dh_public_raw), "protocol": ingest.PROTOCOL_VERSION}


@router.post("")
def receive(pkt: ingest.Packet, request: Request, db: Session = Depends(get_db)) -> dict:
    auth.ingest_limiter.check(f"ingest:{pkt.device_id}:{auth.client_ip(request)}")
    try:
        return ingest.process(db, pkt)
    except ingest.IngestError as exc:
        raise HTTPException(exc.status, exc.message) from exc
