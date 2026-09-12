"""The CP-SAT scheduling model. This is the ONLY place assignments are
decided -- the LLM layer never constructs a schedule (build doc section 5).

Design simplifications, called out explicitly rather than hidden:
  * A task is anchored to one calendar day (day = earliest_start // 1440).
    Tasks spanning midnight are not supported in this version.
  * "Overtime" is minutes worked beyond an 8h/day standard threshold, up to
    the hard `max_hours_per_day` ceiling (C10). Both are configurable only
    through the crew record's max_hours_per_day; the 8h standard threshold
    is a constant (STANDARD_DAY_MINUTES) documented in code and README.
  * Operator-certification (C6) is enforced at the task level: if equipment
    requiring certified operators is used on a task, enough certified crew
    must be present on that same task. It does not pin a specific crew
    member to a specific unit of equipment.
  * In-model travel *cost* uses a home-location distance proxy rather than
    full pairwise route-sequencing cost (which would need task-order
    variables per crew). Travel *feasibility* (C9) IS exact and pairwise.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.optimization.problem import SchedulingProblem, TaskDef, CrewDef, EquipmentDef

STANDARD_DAY_MINUTES = 8 * 60
ACCOMMODATION_DISTANCE_KM = 120.0
ACCOMMODATION_NIGHTLY_COST = 90.0


@dataclass
class SolveResult:
    status: str  # OPTIMAL, FEASIBLE, INFEASIBLE, TIMEOUT
    objective_value: float | None = None
    task_schedule: dict[str, tuple[int, int]] | None = None       # task_id -> (start, end) minutes
    crew_assignments: dict[str, list[str]] | None = None          # task_id -> [crew_id, ...]
    equipment_assignments: dict[str, list[str]] | None = None     # task_id -> [equipment_id, ...]
    overtime_minutes: dict[str, int] | None = None                # crew_id -> total overtime minutes
    solve_seconds: float = 0.0
    blocking_constraints: list[str] | None = None
    best_bound: float | None = None


class InfeasibilityReport:
    def __init__(self, blocking_constraints: list[str]):
        self.blocking_constraints = blocking_constraints

    def suggestions(self) -> list[str]:
        out = []
        for label in self.blocking_constraints:
            if "qualification" in label or "cert" in label:
                out.append(f"Relax or resource the requirement behind: {label} (add a qualified crew member, or extend the certification).")
            elif "availability" in label:
                out.append(f"Extend the availability window referenced by: {label}, or move the task to a day when more crew/equipment are free.")
            elif "deadline" in label:
                out.append(f"Move the deadline referenced by {label} later, or reduce scope so fewer tasks compete for the same window.")
            elif "travel" in label:
                out.append(f"Assign a crew member already near the site for: {label}, or add slack time between the two tasks.")
            else:
                out.append(f"Review the constraint: {label}.")
        return out


def _day_index(offset_minutes: int) -> int:
    return offset_minutes // 1440


def _is_crew_qualified(crew: CrewDef, req_skill_ids, req_cert_ids, role_id: str, at_offset: int) -> bool:
    if crew.role_id != role_id:
        return False
    if not set(req_skill_ids).issubset(crew.skill_ids):
        return False
    for cert_id in req_cert_ids:
        if not crew.is_cert_valid(cert_id, at_offset):
            return False
    return True


def _windows_cover_fully(windows: tuple[tuple[int, int], ...], earliest: int, latest: int) -> bool:
    """True if [earliest, latest] task window has at least one availability
    window that could contain it. Used only for pre-filtering candidate
    crew/equipment before variable creation -- the real fit is enforced by
    the no-overlap-with-unavailable-gaps constraint below."""
    return any(w[0] <= earliest and w[1] >= earliest for w in windows) or any(
        w[0] < latest and w[1] > earliest for w in windows
    )


def _unavailable_gaps(windows: tuple[tuple[int, int], ...], horizon: int) -> list[tuple[int, int]]:
    """Complement of the given available windows within [0, horizon]."""
    if not windows:
        return [(0, horizon)]
    ordered = sorted(windows)
    gaps = []
    cursor = 0
    for start, end in ordered:
        start = max(0, start)
        end = min(horizon, end)
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < horizon:
        gaps.append((cursor, horizon))
    return [g for g in gaps if g[1] > g[0]]


class ScheduleModel:
    def __init__(self, problem: SchedulingProblem):
        self.problem = problem
        self.model = cp_model.CpModel()
        self.horizon = problem.horizon_minutes

        self.task_intervals: dict[str, tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntervalVar]] = {}

        # keyed by (task_id, req_index, crew_id) / (task_id, req_index, equip_id)
        self.crew_assign: dict[tuple[str, int, str], cp_model.IntVar] = {}
        self.equip_assign: dict[tuple[str, int, str], cp_model.IntVar] = {}

        # derived "is this crew/equipment working on this task at all" indicators
        self.crew_busy: dict[tuple[str, str], cp_model.IntVar] = {}
        self.equip_busy: dict[tuple[str, str], cp_model.IntVar] = {}

        self.assumption_labels: dict[int, str] = {}
        self._assumption_vars: list[cp_model.IntVar] = []

    # ------------------------------------------------------------------
    def build(self, with_assumptions: bool = False) -> cp_model.CpModel:
        self._create_task_intervals()
        self._create_assignment_vars()
        self._link_busy_indicators()
        self._c1_c12_crew_requirement_quantity_and_qualification(with_assumptions)
        self._c2_c3_crew_availability_and_overlap(with_assumptions)
        self._equipment_requirement_quantity()
        self._c4_c5_equipment_availability_and_overlap(with_assumptions)
        self._c6_operator_certification(with_assumptions)
        self._c7_task_dependencies(with_assumptions)
        self._c8_deadlines(with_assumptions)
        self._c9_travel_feasibility(with_assumptions)
        overtime_vars = self._c10_working_hours(with_assumptions)
        self._c11_minimum_rest(with_assumptions)
        self._apply_locked_assignments()
        self._build_objective(overtime_vars)
        return self.model

    # ---------- interval variables ----------
    def _create_task_intervals(self):
        for task in self.problem.tasks:
            earliest = max(0, task.earliest_start)
            latest = min(self.horizon, task.latest_finish)
            latest = max(latest, earliest + task.duration_minutes)
            start = self.model.NewIntVar(earliest, latest - task.duration_minutes, f"start_{task.id}")
            end = self.model.NewIntVar(earliest + task.duration_minutes, latest, f"end_{task.id}")
            interval = self.model.NewIntervalVar(start, task.duration_minutes, end, f"interval_{task.id}")
            self.task_intervals[task.id] = (start, end, interval)

    # ---------- assignment variables (pre-filtered: C1 qualification / capacity) ----------
    def _create_assignment_vars(self):
        for task in self.problem.tasks:
            start, end, _ = self.task_intervals[task.id]
            for req_idx, req in enumerate(task.crew_requirements):
                for crew in self.problem.crew:
                    if not _is_crew_qualified(crew, req.required_skill_ids, req.required_cert_ids, req.role_id, task.latest_finish):
                        continue
                    if not _windows_cover_fully(crew.availability_windows, task.earliest_start, task.latest_finish):
                        continue
                    self.crew_assign[(task.id, req_idx, crew.id)] = self.model.NewBoolVar(
                        f"ca_{task.id}_{req_idx}_{crew.id}")
            for req_idx, req in enumerate(task.equipment_requirements):
                for equip in self.problem.equipment:
                    if equip.category_id != req.category_id:
                        continue
                    if req.min_capacity is not None and (equip.capacity_value or 0) < req.min_capacity:
                        continue
                    if not _windows_cover_fully(equip.availability_windows, task.earliest_start, task.latest_finish):
                        continue
                    self.equip_assign[(task.id, req_idx, equip.id)] = self.model.NewBoolVar(
                        f"ea_{task.id}_{req_idx}_{equip.id}")

    def _link_busy_indicators(self):
        for task in self.problem.tasks:
            crew_ids = {cid for (tid, _, cid) in self.crew_assign if tid == task.id}
            for cid in crew_ids:
                vars_ = [v for (tid, _, c), v in self.crew_assign.items() if tid == task.id and c == cid]
                busy = self.model.NewBoolVar(f"cb_{task.id}_{cid}")
                self.model.Add(sum(vars_) <= 1)
                self.model.Add(busy == sum(vars_))
                self.crew_busy[(task.id, cid)] = busy

            equip_ids = {eid for (tid, _, eid) in self.equip_assign if tid == task.id}
            for eid in equip_ids:
                vars_ = [v for (tid, _, e), v in self.equip_assign.items() if tid == task.id and e == eid]
                busy = self.model.NewBoolVar(f"eb_{task.id}_{eid}")
                self.model.Add(sum(vars_) <= 1)
                self.model.Add(busy == sum(vars_))
                self.equip_busy[(task.id, eid)] = busy

    # ---------- C1 (qualification, enforced via pre-filter) + C12 (quantity) ----------
    def _c1_c12_crew_requirement_quantity_and_qualification(self, with_assumptions):
        for task in self.problem.tasks:
            for req_idx, req in enumerate(task.crew_requirements):
                vars_ = [v for (tid, ri, _), v in self.crew_assign.items() if tid == task.id and ri == req_idx]
                label = f"crew_requirement[{task.id}][{req_idx}] role={req.role_id} qty={req.quantity} (qualified candidates={len(vars_)})"
                self._add_equality_or_assumption(sum(vars_) if vars_ else 0, req.quantity, label, with_assumptions)

    def _equipment_requirement_quantity(self):
        for task in self.problem.tasks:
            for req_idx, req in enumerate(task.equipment_requirements):
                vars_ = [v for (tid, ri, _), v in self.equip_assign.items() if tid == task.id and ri == req_idx]
                if vars_:
                    self.model.Add(sum(vars_) == req.quantity)
                elif req.quantity > 0:
                    self.model.Add(0 == req.quantity)  # forces infeasible: no candidate equipment at all

    def _add_equality_or_assumption(self, expr, value, label, with_assumptions):
        if with_assumptions:
            a = self.model.NewBoolVar(f"assume_{label}")
            self.model.Add(expr == value).OnlyEnforceIf(a)
            self._assumption_vars.append(a)
            self.assumption_labels[id(a)] = label
        else:
            self.model.Add(expr == value)

    # ---------- C2 (availability) + C3 (no overlap) ----------
    def _c2_c3_crew_availability_and_overlap(self, with_assumptions):
        for crew in self.problem.crew:
            intervals = []
            for task in self.problem.tasks:
                key = (task.id, crew.id)
                if key not in self.crew_busy:
                    continue
                start, end, _ = self.task_intervals[task.id]
                opt = self.model.NewOptionalIntervalVar(
                    start, task.duration_minutes, end, self.crew_busy[key], f"opt_c_{crew.id}_{task.id}")
                intervals.append(opt)
            for gap_start, gap_end in _unavailable_gaps(crew.availability_windows, self.horizon):
                intervals.append(self.model.NewIntervalVar(gap_start, gap_end - gap_start, gap_end, f"gap_c_{crew.id}_{gap_start}"))
            if intervals:
                self.model.AddNoOverlap(intervals)

    # ---------- C4 (availability + maintenance) + C5 (no overlap) ----------
    def _c4_c5_equipment_availability_and_overlap(self, with_assumptions):
        for equip in self.problem.equipment:
            intervals = []
            for task in self.problem.tasks:
                key = (task.id, equip.id)
                if key not in self.equip_busy:
                    continue
                start, end, _ = self.task_intervals[task.id]
                opt = self.model.NewOptionalIntervalVar(
                    start, task.duration_minutes, end, self.equip_busy[key], f"opt_e_{equip.id}_{task.id}")
                intervals.append(opt)
            blocked_windows = list(equip.availability_windows)
            gaps = _unavailable_gaps(tuple(blocked_windows), self.horizon) if blocked_windows else [(0, self.horizon)]
            for gap_start, gap_end in gaps:
                intervals.append(self.model.NewIntervalVar(gap_start, gap_end - gap_start, gap_end, f"gap_e_{equip.id}_{gap_start}"))
            for m_start, m_end in equip.maintenance_windows:
                s = max(0, m_start)
                e = min(self.horizon, m_end)
                if e > s:
                    intervals.append(self.model.NewIntervalVar(s, e - s, e, f"maint_{equip.id}_{s}"))
            if intervals:
                self.model.AddNoOverlap(intervals)

    # ---------- C6: operator certification ----------
    def _c6_operator_certification(self, with_assumptions):
        for task in self.problem.tasks:
            for req_idx, req in enumerate(task.equipment_requirements):
                for equip in self.problem.equipment:
                    key = (task.id, req_idx, equip.id)
                    if key not in self.equip_assign or not equip.required_operator_cert_ids:
                        continue
                    qualified_crew_busy = [
                        self.crew_busy[(task.id, c.id)]
                        for c in self.problem.crew
                        if (task.id, c.id) in self.crew_busy
                        and all(c.is_cert_valid(cert, task.latest_finish) for cert in equip.required_operator_cert_ids)
                    ]
                    label = f"operator_cert[{task.id}][{equip.id}] certs={equip.required_operator_cert_ids}"
                    lhs = sum(qualified_crew_busy) if qualified_crew_busy else 0
                    if with_assumptions:
                        a = self.model.NewBoolVar(f"assume_{label}")
                        self.model.Add(lhs >= equip.operators_required * self.equip_assign[key]).OnlyEnforceIf(a)
                        self._assumption_vars.append(a)
                        self.assumption_labels[id(a)] = label
                    else:
                        self.model.Add(lhs >= equip.operators_required * self.equip_assign[key])

    # ---------- C7: dependencies ----------
    def _c7_task_dependencies(self, with_assumptions):
        for dep in self.problem.dependencies:
            if dep.predecessor_id not in self.task_intervals or dep.successor_id not in self.task_intervals:
                continue
            ps, pe, _ = self.task_intervals[dep.predecessor_id]
            ss, se, _ = self.task_intervals[dep.successor_id]
            label = f"dependency[{dep.predecessor_id}->{dep.successor_id}]({dep.dependency_type})"
            if dep.dependency_type == "FS":
                expr = (ss - pe >= dep.lag_minutes)
            elif dep.dependency_type == "SS":
                expr = (ss - ps >= dep.lag_minutes)
            elif dep.dependency_type == "FF":
                expr = (se - pe >= dep.lag_minutes)
            else:  # SF
                expr = (se - ps >= dep.lag_minutes)
            if with_assumptions:
                a = self.model.NewBoolVar(f"assume_{label}")
                self.model.Add(expr).OnlyEnforceIf(a)
                self._assumption_vars.append(a)
                self.assumption_labels[id(a)] = label
            else:
                self.model.Add(expr)

    # ---------- C8: deadlines (window already enforced at interval creation; project-level cap here) ----------
    def _c8_deadlines(self, with_assumptions):
        if self.problem.locked_assignments.get("__project_deadline__") is not None:
            deadline = self.problem.locked_assignments["__project_deadline__"]
            for task in self.problem.tasks:
                _, end, _ = self.task_intervals[task.id]
                self.model.Add(end <= deadline)

    # ---------- C9: travel feasibility ----------
    def _c9_travel_feasibility(self, with_assumptions):
        tasks_by_loc_diff = [
            (a, b) for a, b in itertools.combinations(self.problem.tasks, 2) if a.location_id != b.location_id
        ]
        for crew in self.problem.crew:
            for a, b in tasks_by_loc_diff:
                key_a, key_b = (a.id, crew.id), (b.id, crew.id)
                if key_a not in self.crew_busy or key_b not in self.crew_busy:
                    continue
                try:
                    leg_ab = self.problem.travel_matrix.get(a.location_id, b.location_id)
                    leg_ba = self.problem.travel_matrix.get(b.location_id, a.location_id)
                except KeyError:
                    continue
                start_a, end_a, _ = self.task_intervals[a.id]
                start_b, end_b, _ = self.task_intervals[b.id]

                both = self.model.NewBoolVar(f"both_{crew.id}_{a.id}_{b.id}")
                self.model.AddMultiplicationEquality(both, [self.crew_busy[key_a], self.crew_busy[key_b]])

                order = self.model.NewBoolVar(f"order_{crew.id}_{a.id}_{b.id}")
                # a-before-b branch
                self.model.Add(start_b >= end_a + leg_ab.duration_minutes).OnlyEnforceIf([both, order])
                # b-before-a branch
                self.model.Add(start_a >= end_b + leg_ba.duration_minutes).OnlyEnforceIf([both, order.Not()])

    # ---------- C10: working hour caps + overtime tracking ----------
    def _c10_working_hours(self, with_assumptions):
        overtime_vars: dict[str, cp_model.IntVar] = {}
        days = range(0, (self.horizon // 1440) + 1)
        for crew in self.problem.crew:
            week_terms = []
            for day in days:
                day_tasks = [t for t in self.problem.tasks if _day_index(t.earliest_start) == day and (t.id, crew.id) in self.crew_busy]
                if not day_tasks:
                    continue
                minutes_today = sum(self.crew_busy[(t.id, crew.id)] * t.duration_minutes for t in day_tasks)
                cap = crew.max_hours_per_day * 60
                worked = self.model.NewIntVar(0, cap, f"worked_{crew.id}_{day}")
                self.model.Add(worked == minutes_today)
                over = self.model.NewIntVar(0, max(cap - STANDARD_DAY_MINUTES, 0), f"ot_{crew.id}_{day}")
                excess = self.model.NewIntVar(-cap, cap, f"excess_{crew.id}_{day}")
                self.model.Add(excess == worked - STANDARD_DAY_MINUTES)
                self.model.AddMaxEquality(over, [excess, 0])
                overtime_vars[f"{crew.id}_{day}"] = over
                week_terms.append(minutes_today)
            if week_terms:
                self.model.Add(sum(week_terms) <= crew.max_hours_per_week * 60)
        self._per_crew_overtime = overtime_vars
        return overtime_vars

    # ---------- C11: minimum rest between shifts on different days ----------
    def _c11_minimum_rest(self, with_assumptions):
        for crew in self.problem.crew:
            rest_minutes = crew.min_rest_hours * 60
            crew_tasks = [t for t in self.problem.tasks if (t.id, crew.id) in self.crew_busy]
            for a, b in itertools.combinations(crew_tasks, 2):
                if _day_index(a.earliest_start) == _day_index(b.earliest_start):
                    continue
                if abs(a.earliest_start - b.earliest_start) > 2 * 1440:
                    continue  # not plausibly consecutive: skip for tractability
                key_a, key_b = (a.id, crew.id), (b.id, crew.id)
                both = self.model.NewBoolVar(f"restboth_{crew.id}_{a.id}_{b.id}")
                self.model.AddMultiplicationEquality(both, [self.crew_busy[key_a], self.crew_busy[key_b]])
                order = self.model.NewBoolVar(f"restorder_{crew.id}_{a.id}_{b.id}")
                start_a, end_a, _ = self.task_intervals[a.id]
                start_b, end_b, _ = self.task_intervals[b.id]
                self.model.Add(start_b >= end_a + rest_minutes).OnlyEnforceIf([both, order])
                self.model.Add(start_a >= end_b + rest_minutes).OnlyEnforceIf([both, order.Not()])

    # ---------- locked assignments (warm-start / change management) ----------
    def _apply_locked_assignments(self):
        for task_id, lock in self.problem.locked_assignments.items():
            if task_id.startswith("__"):
                continue
            crew_id = lock.get("crew_member_id")
            equip_id = lock.get("equipment_id")
            if crew_id:
                for (tid, ri, cid), var in self.crew_assign.items():
                    if tid == task_id:
                        self.model.Add(var == 1) if cid == crew_id else None
            if equip_id:
                for (tid, ri, eid), var in self.equip_assign.items():
                    if tid == task_id:
                        self.model.Add(var == 1) if eid == equip_id else None

    # ---------- objective ----------
    def _build_objective(self, overtime_vars: dict[str, cp_model.IntVar]):
        W = self.problem.weights

        labour_cost = sum(
            int(round(crew.standard_rate_per_hour / 60 * task.duration_minutes)) * self.crew_busy[(task.id, crew.id)]
            for task in self.problem.tasks for crew in self.problem.crew
            if (task.id, crew.id) in self.crew_busy
        )

        overtime_cost = sum(
            int(round(self._rate_for(crew_id_from_key(key), self.problem) / 60)) * var
            for key, var in overtime_vars.items()
        )

        equipment_cost = sum(
            int(round(equip.daily_operating_cost)) * self.equip_busy[(task.id, equip.id)]
            for task in self.problem.tasks for equip in self.problem.equipment
            if (task.id, equip.id) in self.equip_busy
        )

        travel_cost = sum(
            int(round(self._home_distance_km(crew, task) * 2.0)) * self.crew_busy[(task.id, crew.id)]
            for task in self.problem.tasks for crew in self.problem.crew
            if (task.id, crew.id) in self.crew_busy
        )

        accommodation_cost = sum(
            int(ACCOMMODATION_NIGHTLY_COST) * self.crew_busy[(task.id, crew.id)]
            for task in self.problem.tasks for crew in self.problem.crew
            if (task.id, crew.id) in self.crew_busy and self._home_distance_km(crew, task) > ACCOMMODATION_DISTANCE_KM
        )

        workloads = []
        for crew in self.problem.crew:
            terms = [self.crew_busy[(t.id, crew.id)] * t.duration_minutes for t in self.problem.tasks if (t.id, crew.id) in self.crew_busy]
            wl = self.model.NewIntVar(0, self.horizon, f"wl_{crew.id}")
            self.model.Add(wl == sum(terms)) if terms else self.model.Add(wl == 0)
            workloads.append(wl)
        imbalance = 0
        if workloads:
            max_load = self.model.NewIntVar(0, self.horizon, "max_load")
            min_load = self.model.NewIntVar(0, self.horizon, "min_load")
            self.model.AddMaxEquality(max_load, workloads)
            self.model.AddMinEquality(min_load, workloads)
            imbalance = max_load - min_load

        ends = [end for _, end, _ in self.task_intervals.values()]
        makespan = self.model.NewIntVar(0, self.horizon, "makespan")
        if ends:
            self.model.AddMaxEquality(makespan, ends)

        self.model.Minimize(
            int(W.labour * 100) * labour_cost
            + int(W.overtime * 100) * overtime_cost
            + int(W.travel * 100) * travel_cost
            + int(W.equipment * 100) * equipment_cost
            + int(W.accommodation * 100) * accommodation_cost
            + int(W.imbalance * 100) * imbalance
            + int(W.makespan * 100) * makespan
        )

    def _rate_for(self, crew_id: str, problem: SchedulingProblem) -> float:
        for c in problem.crew:
            if c.id == crew_id:
                return c.overtime_rate_per_hour
        return 0.0

    def _home_distance_km(self, crew: CrewDef, task: TaskDef) -> float:
        if crew.home_location_id == task.location_id:
            return 0.0
        try:
            return self.problem.travel_matrix.get(crew.home_location_id, task.location_id).distance_km
        except KeyError:
            return 0.0


def crew_id_from_key(key: str) -> str:
    return key.rsplit("_", 1)[0]


def solve_with_explanation(problem: SchedulingProblem) -> tuple[SolveResult | None, InfeasibilityReport | None]:
    builder = ScheduleModel(problem)
    model = builder.build(with_assumptions=False)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = problem.max_solve_seconds
    solver.parameters.num_search_workers = problem.num_workers
    solver.parameters.relative_gap_limit = problem.relative_gap
    solver.parameters.random_seed = problem.random_seed

    import time
    t0 = time.monotonic()
    status = solver.Solve(model)
    elapsed = time.monotonic() - t0

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _extract_result(solver, builder, status, elapsed), None

    if status == cp_model.INFEASIBLE:
        assumption_builder = ScheduleModel(problem)
        assumption_model = assumption_builder.build(with_assumptions=True)
        assumption_solver = cp_model.CpSolver()
        assumption_solver.parameters.max_time_in_seconds = min(problem.max_solve_seconds, 30)
        assumption_model.AddAssumptions(assumption_builder._assumption_vars)
        a_status = assumption_solver.Solve(assumption_model)
        if a_status == cp_model.INFEASIBLE:
            blocking_indices = set(assumption_solver.SufficientAssumptionsForInfeasibility())
            index_to_var = {v.Index(): v for v in assumption_builder._assumption_vars}
            labels = [
                assumption_builder.assumption_labels.get(id(index_to_var[i]), f"assumption #{i}")
                for i in blocking_indices if i in index_to_var
            ] or ["Unable to isolate the exact blocking constraint automatically; check crew/equipment coverage for the busiest day."]
        else:
            labels = ["Unable to isolate the exact blocking constraint automatically; check crew/equipment coverage for the busiest day."]
        return SolveResult(status="INFEASIBLE", solve_seconds=elapsed, blocking_constraints=labels), InfeasibilityReport(labels)

    return SolveResult(status="TIMEOUT", solve_seconds=elapsed, best_bound=solver.BestObjectiveBound()), None


def _extract_result(solver: cp_model.CpSolver, builder: ScheduleModel, status, elapsed: float) -> SolveResult:
    task_schedule = {}
    for task_id, (start, end, _) in builder.task_intervals.items():
        task_schedule[task_id] = (solver.Value(start), solver.Value(end))

    crew_assignments: dict[str, list[str]] = {}
    for (task_id, cid), var in builder.crew_busy.items():
        if solver.Value(var):
            crew_assignments.setdefault(task_id, []).append(cid)

    equipment_assignments: dict[str, list[str]] = {}
    for (task_id, eid), var in builder.equip_busy.items():
        if solver.Value(var):
            equipment_assignments.setdefault(task_id, []).append(eid)

    overtime_minutes: dict[str, int] = {}
    for key, var in builder._per_crew_overtime.items():
        crew_id = key.rsplit("_", 1)[0]
        overtime_minutes[crew_id] = overtime_minutes.get(crew_id, 0) + solver.Value(var)

    status_name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    return SolveResult(
        status=status_name,
        objective_value=solver.ObjectiveValue(),
        task_schedule=task_schedule,
        crew_assignments=crew_assignments,
        equipment_assignments=equipment_assignments,
        overtime_minutes=overtime_minutes,
        solve_seconds=elapsed,
    )
