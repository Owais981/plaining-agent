from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, Skill, Certification, EquipmentCategory, Client

router = APIRouter(prefix="/api/v1/reference", tags=["reference"])


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(Role).all()]


@router.get("/skills")
def list_skills(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(Skill).all()]


@router.get("/certifications")
def list_certifications(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(Certification).all()]


@router.get("/equipment-categories")
def list_equipment_categories(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(EquipmentCategory).all()]


@router.get("/clients")
def list_clients(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(Client).all()]
