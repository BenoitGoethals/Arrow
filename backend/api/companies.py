from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import CompanyIn, CompanyOut
from backend.auth.jwt_auth import require_role
from backend.storage.database import get_db
from backend.storage.models import Company

router = APIRouter(prefix="/companies", tags=["hierarchy"])


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)) -> list[Company]:
    return db.query(Company).all()


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CompanyIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> Company:
    company = Company(name=payload.name)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_role("ADMIN")),
) -> None:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(company)
    db.commit()
