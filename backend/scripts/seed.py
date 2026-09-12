"""Realistic development seed data (build doc section 45). Run with:

    python scripts/seed.py

Creates: 1 project, 5 locations, 15 tasks, 10 crew, multiple roles/skills/
certifications (including one deliberately EXPIRED certification), 8
equipment assets, availability + maintenance windows, task dependencies,
varied rates, multi-site travel, and one deliberately infeasible task
(requires a role nobody holds) for testing the infeasibility-explanation
path end to end.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, engine, Base
from app.models import (
    Client, Role, Skill, Certification, EquipmentCategory, User,
    Project, Location, Task, TaskDependency, TaskCrewRequirement, TaskEquipmentRequirement,
    CrewMember, CrewSkill, CrewCertification, CrewAvailability,
    Equipment, EquipmentAvailability, EquipmentMaintenance,
)
from app.security.auth import hash_password

Base.metadata.create_all(engine)
db = SessionLocal()

TODAY = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def day(offset_days: int, hour: int = 0) -> datetime:
    return TODAY + timedelta(days=offset_days, hours=hour)


def wipe_existing():
    for model in [
        TaskDependency, TaskCrewRequirement, TaskEquipmentRequirement, Task,
        CrewAvailability, CrewCertification, CrewSkill, CrewMember,
        EquipmentAvailability, EquipmentMaintenance, Equipment,
        Project, Location, Client, Role, Skill, Certification, EquipmentCategory, User,
    ]:
        db.query(model).delete()
    db.commit()


def main():
    wipe_existing()

    admin = User(email="admin@example.com", hashed_password=hash_password("admin123"), full_name="Ops Admin", role="admin")
    pm = User(email="pm@example.com", hashed_password=hash_password("pm123"), full_name="Project Manager", role="approver")
    db.add_all([admin, pm])

    client = Client(name="Acme Broadcasting")
    db.add(client)
    db.flush()

    roles = {name: Role(name=name) for name in ["Electrician", "Rigger", "Crane Operator", "Camera Operator", "Site Supervisor"]}
    db.add_all(roles.values())

    skills = {name: Skill(name=name) for name in ["Rigging", "High Voltage", "Live Broadcast", "Working at Height"]}
    db.add_all(skills.values())

    certs = {name: Certification(name=name) for name in ["Crane Operator License", "Working at Height Cert", "First Aid", "Electrical Safety"]}
    db.add_all(certs.values())

    categories = {name: EquipmentCategory(name=name) for name in ["Mobile Crane", "Generator", "Camera Rig", "Scaffold Tower"]}
    db.add_all(categories.values())
    db.flush()

    locations = [
        Location(name="Studio A", address="12 Broadcast Way", latitude=51.5074, longitude=-0.1278, site_type="site"),
        Location(name="Studio B", address="88 Media Rd", latitude=51.4700, longitude=-0.4543, site_type="site"),
        Location(name="Outdoor Site C", address="Green Park", latitude=51.5045, longitude=-0.1462, site_type="site"),
        Location(name="Central Depot", address="1 Depot Ln", latitude=51.5155, longitude=-0.0922, site_type="depot"),
        Location(name="Riverside Site D", address="Thames Path", latitude=51.5079, longitude=-0.0877, site_type="site"),
    ]
    db.add_all(locations)
    db.flush()
    loc_by_name = {l.name: l for l in locations}

    project = Project(
        code="BC-2026-01", name="Spring Broadcast Series", client_id=client.id,
        start_date=day(0).date(), end_date=day(6).date(), deadline=day(6, 20),
        priority=2, budget_total=45000, currency="USD", status="planning",
    )
    db.add(project)
    db.flush()

    crew_specs = [
        ("E001", "Alex Chen", "Electrician", "Studio A", 28, 42, ["High Voltage"], ["Electrical Safety"]),
        ("E002", "Priya Patel", "Electrician", "Studio A", 27, 40.5, ["High Voltage"], ["Electrical Safety"]),
        ("R001", "Sam Okafor", "Rigger", "Studio B", 24, 36, ["Rigging", "Working at Height"], ["Working at Height Cert"]),
        ("R002", "Jamie Wu", "Rigger", "Studio B", 24, 36, ["Rigging", "Working at Height"], ["Working at Height Cert"]),
        ("C001", "Morgan Fields", "Crane Operator", "Central Depot", 35, 52.5, ["Rigging"], ["Crane Operator License"]),
        ("CM001", "Jordan Lee", "Camera Operator", "Studio A", 26, 39, ["Live Broadcast"], []),
        ("CM002", "Taylor Brooks", "Camera Operator", "Studio B", 26, 39, ["Live Broadcast"], []),
        ("S001", "Riley Adams", "Site Supervisor", "Outdoor Site C", 30, 45, ["Working at Height"], ["First Aid", "Working at Height Cert"]),
        ("E003", "Casey Kim", "Electrician", "Riverside Site D", 27, 40.5, ["High Voltage"], ["Electrical Safety"]),
        ("C002", "Drew Nguyen", "Crane Operator", "Central Depot", 34, 51, [], ["Crane Operator License"]),
    ]

    crew_by_code = {}
    for code, name, role, home, rate, ot_rate, skill_names, cert_names in crew_specs:
        cm = CrewMember(
            employee_code=code, full_name=name, primary_role_id=roles[role].id,
            home_location_id=loc_by_name[home].id, standard_rate=rate, overtime_rate=ot_rate,
            max_hours_per_day=10, max_hours_per_week=48, min_rest_hours=11,
        )
        db.add(cm)
        db.flush()
        crew_by_code[code] = cm
        for sname in skill_names:
            db.add(CrewSkill(crew_member_id=cm.id, skill_id=skills[sname].id, proficiency=4))
        for cname in cert_names:
            db.add(CrewCertification(crew_member_id=cm.id, certification_id=certs[cname].id,
                                      issued_date=date(2024, 1, 1), expiry_date=date(2027, 1, 1)))
        db.add(CrewAvailability(crew_member_id=cm.id, starts_at=day(0), ends_at=day(7), availability_type="available"))

    # deliberately expired certification -- Drew's crane license expired last month
    expired_cert = db.query(CrewCertification).filter(
        CrewCertification.crew_member_id == crew_by_code["C002"].id
    ).first()
    expired_cert.expiry_date = (TODAY - timedelta(days=30)).date()

    # one crew member has a leave day mid-project (partial availability)
    db.add(CrewAvailability(crew_member_id=crew_by_code["R001"].id, starts_at=day(3), ends_at=day(4), availability_type="leave"))

    equipment_specs = [
        ("CR-01", "Mobile Crane 40T", "Mobile Crane", "Central Depot", 40, 1, ["Crane Operator License"], 850, 3.5),
        ("CR-02", "Mobile Crane 25T", "Mobile Crane", "Central Depot", 25, 1, ["Crane Operator License"], 650, 3.0),
        ("GEN-01", "Diesel Generator 60kVA", "Generator", "Studio A", 60, 0, [], 120, 1.0),
        ("GEN-02", "Diesel Generator 60kVA", "Generator", "Studio B", 60, 0, [], 120, 1.0),
        ("CAM-01", "Broadcast Camera Rig", "Camera Rig", "Studio A", None, 0, [], 90, 0.5),
        ("CAM-02", "Broadcast Camera Rig", "Camera Rig", "Studio B", None, 0, [], 90, 0.5),
        ("SC-01", "Scaffold Tower 8m", "Scaffold Tower", "Outdoor Site C", 8, 0, [], 60, 0.8),
        ("SC-02", "Scaffold Tower 12m", "Scaffold Tower", "Riverside Site D", 12, 0, [], 75, 0.8),
    ]
    equip_by_code = {}
    for code, name, cat, loc, capacity, ops_req, cert_names, daily_cost, transport_cost in equipment_specs:
        eq = Equipment(
            asset_code=code, name=name, category_id=categories[cat].id, current_location_id=loc_by_name[loc].id,
            capacity_value=capacity, capacity_unit="tonnes" if "Crane" in cat else None,
            operators_required=ops_req, required_operator_cert_ids=[certs[c].id for c in cert_names],
            daily_operating_cost=daily_cost, transport_cost_per_km=transport_cost, ownership="owned",
        )
        db.add(eq)
        db.flush()
        equip_by_code[code] = eq
        db.add(EquipmentAvailability(equipment_id=eq.id, starts_at=day(0), ends_at=day(7), availability_type="available"))

    # one crane goes into scheduled maintenance for a day mid-project
    db.add(EquipmentMaintenance(equipment_id=equip_by_code["CR-02"].id, starts_at=day(2, 6), ends_at=day(2, 18),
                                 maintenance_type="scheduled", blocks_usage=True))

    task_specs = [
        ("Rig lighting - Studio A", "Studio A", 0, 8, 12, "Electrician", 1, ["High Voltage"], []),
        ("Rig lighting - Studio B", "Studio B", 0, 8, 12, "Electrician", 1, ["High Voltage"], []),
        ("Set up scaffold - Site C", "Outdoor Site C", 0, 8, 14, "Rigger", 2, ["Working at Height"], []),
        ("Crane lift - steel truss", "Central Depot", 1, 8, 12, "Crane Operator", 1, [], []),
        ("Camera setup - Studio A", "Studio A", 1, 9, 12, "Camera Operator", 1, [], []),
        ("Camera setup - Studio B", "Studio B", 1, 9, 12, "Camera Operator", 1, [], []),
        ("Live broadcast take 1", "Studio A", 2, 14, 18, "Camera Operator", 1, ["Live Broadcast"], []),
        ("Live broadcast take 2", "Studio B", 2, 14, 18, "Camera Operator", 1, ["Live Broadcast"], []),
        ("Site supervision - Site C", "Outdoor Site C", 2, 8, 18, "Site Supervisor", 1, [], []),
        ("Riverside rig", "Riverside Site D", 3, 8, 13, "Electrician", 1, ["High Voltage"], []),
        ("Crane lift - stage roof", "Outdoor Site C", 3, 8, 13, "Crane Operator", 1, [], []),
        ("Teardown - Studio A", "Studio A", 5, 8, 14, "Electrician", 1, [], []),
        ("Teardown - Studio B", "Studio B", 5, 8, 14, "Electrician", 1, [], []),
        ("Final inspection", "Central Depot", 6, 9, 11, "Site Supervisor", 1, [], []),
        # deliberately infeasible: no crew holds this role at all
        ("Specialist pyrotechnics rig", "Outdoor Site C", 4, 8, 12, "Pyrotechnician", 1, [], []),
    ]

    tasks_by_name = {}
    for name, loc, day_offset, start_h, end_h, role_name, qty, skill_names, cert_names in task_specs:
        role = roles.get(role_name)
        if role is None:
            role = Role(name=role_name)
            db.add(role)
            db.flush()
            roles[role_name] = role
        t = Task(
            project_id=project.id, location_id=loc_by_name[loc].id, name=name,
            duration_minutes=(end_h - start_h) * 60,
            earliest_start=day(day_offset, start_h), latest_finish=day(day_offset, end_h),
            priority=2,
        )
        db.add(t)
        db.flush()
        tasks_by_name[name] = t
        db.add(TaskCrewRequirement(
            task_id=t.id, role_id=role.id, quantity=qty,
            required_skill_ids=[skills[s].id for s in skill_names],
            required_cert_ids=[certs[c].id for c in cert_names],
        ))

    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Crane lift - steel truss"].id, category_id=categories["Mobile Crane"].id, quantity=1, min_capacity=30))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Crane lift - stage roof"].id, category_id=categories["Mobile Crane"].id, quantity=1, min_capacity=20))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Set up scaffold - Site C"].id, category_id=categories["Scaffold Tower"].id, quantity=1))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Live broadcast take 1"].id, category_id=categories["Camera Rig"].id, quantity=1))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Live broadcast take 2"].id, category_id=categories["Camera Rig"].id, quantity=1))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Rig lighting - Studio A"].id, category_id=categories["Generator"].id, quantity=1))
    db.add(TaskEquipmentRequirement(task_id=tasks_by_name["Rig lighting - Studio B"].id, category_id=categories["Generator"].id, quantity=1))

    db.add(TaskDependency(predecessor_id=tasks_by_name["Rig lighting - Studio A"].id, successor_id=tasks_by_name["Camera setup - Studio A"].id, lag_minutes=30, dependency_type="FS"))
    db.add(TaskDependency(predecessor_id=tasks_by_name["Camera setup - Studio A"].id, successor_id=tasks_by_name["Live broadcast take 1"].id, lag_minutes=0, dependency_type="FS"))
    db.add(TaskDependency(predecessor_id=tasks_by_name["Rig lighting - Studio B"].id, successor_id=tasks_by_name["Camera setup - Studio B"].id, lag_minutes=30, dependency_type="FS"))
    db.add(TaskDependency(predecessor_id=tasks_by_name["Camera setup - Studio B"].id, successor_id=tasks_by_name["Live broadcast take 2"].id, lag_minutes=0, dependency_type="FS"))
    db.add(TaskDependency(predecessor_id=tasks_by_name["Set up scaffold - Site C"].id, successor_id=tasks_by_name["Crane lift - stage roof"].id, lag_minutes=60, dependency_type="FS"))

    db.commit()
    print(f"Seeded project {project.code} ({project.id}) with {len(task_specs)} tasks, {len(crew_specs)} crew, {len(equipment_specs)} equipment assets.")
    print("Login: admin@example.com / admin123  |  pm@example.com / pm123")
    print("Note: task 'Specialist pyrotechnics rig' is deliberately infeasible (no crew holds that role) -- use it to test the infeasibility-explanation path.")
    print("Note: crew member 'Drew Nguyen' has an EXPIRED crane certification -- use it to test certification-expiry handling.")


if __name__ == "__main__":
    main()
