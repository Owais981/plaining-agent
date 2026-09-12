from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task, TaskDependency, TaskCrewRequirement, TaskEquipmentRequirement
from app.schemas.task import TaskCreate, TaskOut, DependencyCreate
from app.security.deps import require_role

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Task)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    return q.all()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    data = body.model_dump(exclude={"crew_requirements", "equipment_requirements"})
    task = Task(**data)
    db.add(task)
    db.flush()
    for req in body.crew_requirements:
        db.add(TaskCrewRequirement(task_id=task.id, **req.model_dump()))
    for req in body.equipment_requirements:
        db.add(TaskEquipmentRequirement(task_id=task.id, **req.model_dump()))
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Task not found"})
    return task


@router.post("/dependencies", status_code=201)
def create_dependency(body: DependencyCreate, db: Session = Depends(get_db), _user=Depends(require_role("editor"))):
    if body.dependency_type not in ("FS", "SS", "FF", "SF"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": "INVALID_DEPENDENCY_TYPE", "message": "Must be FS, SS, FF, or SF"})
    dep = TaskDependency(**body.model_dump())
    db.add(dep)
    db.commit()
    return {"ok": True}
