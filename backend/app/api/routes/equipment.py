from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Equipment, EquipmentAvailability, EquipmentMaintenance
from app.schemas.equipment import EquipmentCreate, EquipmentOut, EquipmentAvailabilityCreate, EquipmentMaintenanceCreate
from app.security.deps import require_role

router = APIRouter(prefix="/api/v1/equipment", tags=["equipment"])


@router.get("", response_model=list[EquipmentOut])
def list_equipment(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Equipment).filter(Equipment.is_active == True)  # noqa: E712
    if category:
        q = q.filter(Equipment.category_id == category)
    return q.all()


@router.post("", response_model=EquipmentOut, status_code=201)
def create_equipment(body: EquipmentCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    equip = Equipment(**body.model_dump())
    db.add(equip)
    db.commit()
    db.refresh(equip)
    return equip


@router.get("/{equipment_id}", response_model=EquipmentOut)
def get_equipment(equipment_id: str, db: Session = Depends(get_db)):
    equip = db.get(Equipment, equipment_id)
    if equip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Equipment not found"})
    return equip


@router.post("/availability", status_code=201)
def add_availability(body: EquipmentAvailabilityCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    db.add(EquipmentAvailability(**body.model_dump()))
    db.commit()
    return {"ok": True}


@router.post("/maintenance", status_code=201)
def add_maintenance(body: EquipmentMaintenanceCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    db.add(EquipmentMaintenance(**body.model_dump()))
    db.commit()
    return {"ok": True}
