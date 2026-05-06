from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import BattleIn, BattleOut
from backend.auth.jwt_auth import require_role
from backend.storage.database import get_db
from backend.storage.models import Battle

router = APIRouter(prefix="/battles", tags=["battles"])


@router.get("", response_model=list[BattleOut])
def list_battles(db: Session = Depends(get_db)) -> list[Battle]:
    return db.query(Battle).order_by(Battle.started_at.desc()).all()


@router.post("", response_model=BattleOut, status_code=status.HTTP_201_CREATED)
def create_battle(
    payload: BattleIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Battle:
    b = Battle(name=payload.name, description=payload.description)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@router.post("/{battle_id}/close", response_model=BattleOut)
def close_battle(
    battle_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Battle:
    b = db.get(Battle, battle_id)
    if not b:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    b.status = "CLOSED"
    b.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(b)
    return b
