from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import CompanyIn, PlatoonIn, PlatoonOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage.database import get_db
from backend.storage.models import Operator, Platoon

router = APIRouter(prefix="/platoons", tags=["hierarchy"])


@router.get("", response_model=list[PlatoonOut])
def list_platoons(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Platoon]:
    return db.query(Platoon).all()


@router.post("", response_model=PlatoonOut, status_code=status.HTTP_201_CREATED)
def create_platoon(
    payload: PlatoonIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> Platoon:
    p = Platoon(name=payload.name, company_id=payload.company_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{platoon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platoon(
    platoon_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> None:
    p = db.get(Platoon, platoon_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(p)
    db.commit()


@router.patch("/{platoon_id}", response_model=PlatoonOut)
def update_platoon(
    platoon_id: int,
    payload: CompanyIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> Platoon:
    plt = db.get(Platoon, platoon_id)
    if not plt:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    plt.name = payload.name
    db.commit()
    db.refresh(plt)
    return plt
