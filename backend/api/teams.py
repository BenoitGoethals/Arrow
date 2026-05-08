from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import TeamIn, TeamOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage.database import get_db
from backend.storage.models import Operator, Team

router = APIRouter(prefix="/teams", tags=["hierarchy"])


@router.get("", response_model=list[TeamOut])
def list_teams(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Team]:
    return db.query(Team).all()


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> Team:
    t = Team(name=payload.name, section_id=payload.section_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> None:
    t = db.get(Team, team_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(t)
    db.commit()
