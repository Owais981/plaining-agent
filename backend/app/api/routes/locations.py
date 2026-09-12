from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Location
from app.schemas.location import LocationCreate, LocationOut
from app.security.deps import require_role

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get("", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db)):
    return db.query(Location).all()


@router.post("", response_model=LocationOut, status_code=201)
def create_location(body: LocationCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    loc = Location(**body.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.get("/{location_id}", response_model=LocationOut)
def get_location(location_id: str, db: Session = Depends(get_db)):
    loc = db.get(Location, location_id)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Location not found"})
    return loc
