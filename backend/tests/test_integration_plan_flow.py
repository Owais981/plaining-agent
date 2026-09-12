"""End-to-end test through the real stack: SQLAlchemy models -> SQLite ->
build_problem_from_db -> CP-SAT solver -> conflict/cost/risk engines ->
approval gate. No mocking of the solver or the database (build doc section
62: never fake solver output)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Project, Location, Task, TaskCrewRequirement, TaskEquipmentRequirement, Role, CrewMember,
    CrewAvailability, User, EquipmentCategory, Equipment, EquipmentAvailability,
)
from app.services import plan_service


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_minimal_project(db):
    role = Role(id="role-electrician", name="Electrician")
    db.add(role)
    loc = Location(id="loc-a", name="Site A", latitude=51.5, longitude=-0.1)
    db.add(loc)
    user = User(id="user-1", email="pm@example.com", hashed_password="x", role="admin")
    db.add(user)
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    project = Project(id="proj-1", code="P1", name="Test Project", start_date=start.date(), end_date=(start + timedelta(days=2)).date())
    db.add(project)
    crew = CrewMember(id="crew-1", employee_code="E1", full_name="Alex", primary_role_id="role-electrician",
                       home_location_id="loc-a", standard_rate=25, overtime_rate=37.5)
    db.add(crew)
    db.add(CrewAvailability(crew_member_id="crew-1", starts_at=start, ends_at=start + timedelta(days=2), availability_type="available"))
    task = Task(id="task-1", project_id="proj-1", location_id="loc-a", name="Wire the panel",
                duration_minutes=120, earliest_start=start + timedelta(hours=8), latest_finish=start + timedelta(hours=18))
    db.add(task)
    db.add(TaskCrewRequirement(task_id="task-1", role_id="role-electrician", quantity=1))
    db.commit()
    return project


def test_full_optimize_conflict_cost_risk_and_approval_flow(db_session):
    _seed_minimal_project(db_session)

    completeness = asyncio.run(plan_service.check_data_completeness(db_session, "proj-1"))
    assert completeness["complete"] is True

    result = asyncio.run(plan_service.run_optimize(db_session, "proj-1", None))
    assert result["status"] in ("OPTIMAL", "FEASIBLE")
    plan_id = result["plan_id"]

    conflicts = asyncio.run(plan_service.detect_conflicts_for_plan(db_session, plan_id))
    assert all(c["severity"] != "critical" for c in conflicts)

    cost = asyncio.run(plan_service.calculate_cost_for_plan(db_session, plan_id))
    assert cost["total"] > 0

    risks = asyncio.run(plan_service.assess_risks_for_plan(db_session, plan_id))
    assert isinstance(risks, list)

    approved = plan_service.approve_plan(db_session, plan_id, "user-1")
    assert approved["status"] == "approved"


def test_approval_blocked_when_critical_conflict_exists(db_session):
    """Rule 4 (build doc section 51): no critical conflict means no approval."""
    from app.models import Plan, PlanConflict

    project = _seed_minimal_project(db_session)
    plan = Plan(id="plan-x", project_id=project.id, version=1, status="draft", solver_status="FEASIBLE", input_snapshot={"project_id": project.id})
    db_session.add(plan)
    db_session.add(PlanConflict(plan_id="plan-x", severity="critical", conflict_type="crew_double_booking",
                                 description="test conflict", suggested_fix="fix it"))
    db_session.commit()

    with pytest.raises(ValueError, match="critical"):
        plan_service.approve_plan(db_session, "plan-x", "user-1")


def test_shared_equipment_across_multiple_crew_is_not_a_false_conflict(db_session):
    """Regression test: a task needing 2 crew + 1 shared equipment unit
    persists as 2 PlanAssignment rows (one per crew member), both carrying
    the same equipment_id. Rebuilding the problem from those rows must NOT
    interpret that as the equipment being double-booked against itself."""
    project = _seed_minimal_project(db_session)
    category = EquipmentCategory(id="cat-scaffold", name="Scaffold Tower")
    db_session.add(category)
    equip = Equipment(id="eq-1", asset_code="SC-1", name="Scaffold", category_id="cat-scaffold", daily_operating_cost=50)
    db_session.add(equip)
    start = db_session.get(Task, "task-1").earliest_start
    db_session.add(EquipmentAvailability(equipment_id="eq-1", starts_at=start - timedelta(hours=8), ends_at=start + timedelta(days=2), availability_type="available"))
    db_session.query(TaskCrewRequirement).filter(TaskCrewRequirement.task_id == "task-1").update({"quantity": 2})

    # add a second electrician so quantity=2 is satisfiable
    crew2 = CrewMember(id="crew-2", employee_code="E2", full_name="Sam", primary_role_id="role-electrician",
                        home_location_id="loc-a", standard_rate=25, overtime_rate=37.5)
    db_session.add(crew2)
    db_session.add(CrewAvailability(crew_member_id="crew-2", starts_at=start - timedelta(hours=8), ends_at=start + timedelta(days=2), availability_type="available"))
    db_session.add(TaskEquipmentRequirement(task_id="task-1", category_id="cat-scaffold", quantity=1))
    db_session.commit()

    result = asyncio.run(plan_service.run_optimize(db_session, project.id, None))
    assert result["status"] in ("OPTIMAL", "FEASIBLE")
    conflicts = asyncio.run(plan_service.detect_conflicts_for_plan(db_session, result["plan_id"]))
    assert not any(c["conflict_type"] == "equipment_double_alloc" for c in conflicts)


def test_infeasible_project_produces_blocking_constraints(db_session):
    """No crew at all for the required role -> INFEASIBLE with an
    explanation, never a crash and never a fabricated schedule."""
    role = Role(id="role-crane", name="Crane Operator")
    db_session.add(role)
    loc = Location(id="loc-a", name="Site A", latitude=51.5, longitude=-0.1)
    db_session.add(loc)
    start = datetime.now(timezone.utc) + timedelta(days=1)
    project = Project(id="proj-2", code="P2", name="Infeasible Project", start_date=start.date(), end_date=(start + timedelta(days=1)).date())
    db_session.add(project)
    task = Task(id="task-x", project_id="proj-2", location_id="loc-a", name="Lift beam", duration_minutes=60,
                earliest_start=start, latest_finish=start + timedelta(hours=8))
    db_session.add(task)
    db_session.add(TaskCrewRequirement(task_id="task-x", role_id="role-crane", quantity=1))
    db_session.commit()

    result = asyncio.run(plan_service.run_optimize(db_session, "proj-2", None))
    assert result["status"] == "INFEASIBLE"
    assert result["blocking_constraints"]
    assert result["suggestions"]
