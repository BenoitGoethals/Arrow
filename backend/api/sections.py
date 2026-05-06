from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import SectionIn, SectionOut
from backend.auth.jwt_auth import require_role
from backend.storage.database import get_db
from backend.storage.models import Section

router = APIRouter(prefix="/sections", tags=["hierarchy"])


@router.get("", response_model=list[SectionOut])
def list_sections(db: Session = Depends(get_db)) -> list[Section]:
    return db.query(Section).all()


@router.post("", response_model=SectionOut, status_code=status.HTTP_201_CREATED)
def create_section(
    payload: SectionIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> Section:
    s = Section(name=payload.name, platoon_id=payload.platoon_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    section_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> None:
    s = db.get(Section, section_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(s)
    db.commit()
