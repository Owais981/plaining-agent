from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CrewMember, CrewAvailability, CrewCertification, CrewSkill
from app.schemas.crew import CrewMemberCreate, CrewMemberOut, CrewAvailabilityCreate, CrewCertificationCreate
from app.security.deps import require_role

router = APIRouter(prefix="/api/v1/crew", tags=["crew"])


@router.get("", response_model=list[CrewMemberOut])
def list_crew(available_from: str | None = None, skills: str | None = None, db: Session = Depends(get_db)):
    q = db.query(CrewMember).filter(CrewMember.is_active == True)  # noqa: E712
    return q.all()


@router.post("", response_model=CrewMemberOut, status_code=201)
def create_crew(body: CrewMemberCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    crew = CrewMember(**body.model_dump())
    db.add(crew)
    db.commit()
    db.refresh(crew)
    return crew


@router.get("/{crew_id}", response_model=CrewMemberOut)
def get_crew(crew_id: str, db: Session = Depends(get_db)):
    crew = db.get(CrewMember, crew_id)
    if crew is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Crew member not found"})
    return crew


@router.post("/{crew_id}/skills/{skill_id}", status_code=201)
def add_skill(crew_id: str, skill_id: str, proficiency: int = 3, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    db.add(CrewSkill(crew_member_id=crew_id, skill_id=skill_id, proficiency=proficiency))
    db.commit()
    return {"ok": True}


@router.post("/availability", status_code=201)
def add_availability(body: CrewAvailabilityCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    db.add(CrewAvailability(**body.model_dump()))
    db.commit()
    return {"ok": True}


@router.post("/certifications", status_code=201)
def add_certification(body: CrewCertificationCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    db.add(CrewCertification(**body.model_dump()))
    db.commit()
    return {"ok": True}
