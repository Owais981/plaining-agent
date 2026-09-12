from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Location
from app.routing.base import Coordinate
from app.routing.service import RoutingService

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])


class MatrixRequest(BaseModel):
    location_ids: list[str]
    departure_time: datetime | None = None


@router.post("/matrix")
async def build_matrix(body: MatrixRequest, db: Session = Depends(get_db)):
    locations = db.query(Location).filter(Location.id.in_(body.location_ids)).all()
    if len(locations) != len(set(body.location_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "One or more locations not found"})
    coords = [Coordinate(l.id, l.latitude, l.longitude) for l in locations]
    service = RoutingService()
    matrix = await service.build_matrix(coords, body.departure_time)
    return [
        {
            "from_location_id": fid, "to_location_id": tid,
            "distance_km": r.distance_km, "duration_minutes": r.duration_minutes, "cost": r.cost,
            "data_source": r.data_source, "confidence": r.confidence, "retrieved_at": r.retrieved_at.isoformat(),
        }
        for (fid, tid), r in matrix.items()
    ]
