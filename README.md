# Crew, Equipment & Travel Planning Agent

A conversational planning assistant for crew, equipment and travel scheduling, built on the
principle that **the LLM never invents or computes the schedule**. Claude handles conversation,
missing-data questions and explanations; a deterministic OR-Tools CP-SAT solver produces every
assignment; PostgreSQL is the source of truth for all resource data; and an independent
rules engine re-checks every plan for conflicts before it can be presented or approved.

```
USER → CLAUDE AGENT → TOOLS → VALIDATION → ROUTING → OR-TOOLS CP-SAT →
CONFLICT DETECTION → COST + RISK → PLAN → CLAUDE EXPLANATION → USER
```

## Architecture

| Layer | Responsibility | Technology |
|---|---|---|
| Conversation | Understand requests, ask for missing data, explain results | Claude (Anthropic API) + tool calling |
| Optimization | Assign crew/equipment, sequence tasks, respect hard constraints | Google OR-Tools CP-SAT + routing + conflict/cost/risk engines |
| Data | Source of truth for resources, availability, plans | PostgreSQL (+PostGIS) + Redis (route cache / job state) |

The agent (`backend/app/ai/agent.py`) never writes a schedule from its own reasoning -- every
tool call is executed by the backend (`backend/app/ai/tools.py`), validated with Pydantic, and
run against the real database and solver. See `backend/app/prompts/planning_agent_v1.py` for the
system prompt and its "never invent" rules.

## Repository layout

```
backend/app/
  models/        SQLAlchemy models (projects, locations, tasks, crew, equipment, plans...)
  optimization/  CP-SAT solver + the plain-Python SchedulingProblem it operates on
  routing/       RoutingProvider abstraction: Haversine (always works) / OSRM / Google
  conflicts/     Independent rules engine, re-checks plans from scratch
  costs/         Deterministic cost calculator
  risks/         Deterministic risk register
  ai/            AIProvider abstraction, Anthropic implementation, tool schemas, agent loop
  services/      Orchestrates solver+conflicts+costs+risks; change management; scenarios
  api/routes/    FastAPI routers
  jobs/          Celery task + in-process fallback for async solves
backend/tests/    Solver correctness, determinism, conflict/cost/risk, agent-tool, API smoke tests
backend/scripts/seed.py   Realistic seed data (including a deliberately infeasible task and an
                          expired certification, for testing those paths)
frontend/src/    React + TypeScript + Vite dashboard
```

## Running it

### Option A: Docker Compose (Postgres + Redis + backend + worker + frontend)

```
cp .env.example .env      # fill in ANTHROPIC_API_KEY etc. if you have them
docker compose up --build
```

Backend: http://localhost:8000/docs · Frontend: http://localhost:5173

### Option B: Local dev (SQLite, no Docker)

This is the fastest path to try the system and is what was used to build and test it.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/... on macOS/Linux
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python scripts/seed.py
.venv/Scripts/python -m uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in with a seeded login: `admin@example.com` / `admin123`
(or `pm@example.com` / `pm123`).

SQLite is used here for zero-setup local development; the models and Alembic migration are
written to run identically against PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`), which
additionally gets a generated PostGIS `geography` column + GIST spatial index (see the migration's
Postgres-only block).

### Running tests

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -q
```

41 tests: solver hard-constraint tests (one per C1-C12), a determinism test, conflict/cost/risk
engine tests, an end-to-end DB-backed integration test (including a regression test and one
deliberately infeasible scenario), agent tool-dispatch tests, routing tests, and FastAPI smoke
tests via `TestClient`.

Frontend:

```bash
cd frontend
npx tsc -b        # type check
npm run build     # production build
```

## Environment variables

See `.env.example`. Nothing is hardcoded: without `ANTHROPIC_API_KEY`, every REST endpoint still
works (CRUD, `/plans/optimize`, conflicts, costs, risks, approval) -- only
`/api/v1/conversations/*` returns `503 AI_NOT_CONFIGURED`. Without `OSRM_BASE_URL` or
`GOOGLE_MAPS_API_KEY`, routing falls back to a Haversine straight-line estimate, always tagged
`data_source=haversine_estimate` / `confidence=estimated` so the UI never presents it as measured.

## The optimization engine

`backend/app/optimization/solver.py` builds one CP-SAT model per solve request:

- **Hard constraints (never violated):** C1 crew qualification (role + skills + certifications,
  checked against the task's own date, not the planning date), C2 crew availability windows, C3 no
  crew double-booking, C4 equipment availability, C5 no equipment double-booking, C6 operator
  certification, C7 task dependencies (FS/SS/FF/SF with lag), C8 deadlines, C9 travel-time
  feasibility, C10 max working hours/day/week, C11 minimum rest between shifts, C12 crew quantity
  per task.
- **Soft objective:** weighted sum of labour, overtime, travel, equipment, accommodation,
  workload imbalance and makespan (`backend/config/optimization_weights.yaml`), selectable via
  `objective_profile` (`balanced`, `minimize_cost`, `minimize_travel`, `minimize_overtime`,
  `earliest_finish`).
- **Infeasibility:** never a bare error. The solver re-solves with CP-SAT's assumptions API and
  returns the specific blocking constraints plus generated relaxation suggestions
  (`InfeasibilityReport`), which the API returns as-is and the agent explains without inventing a
  different reason.
- **Determinism:** a fixed `random_seed` and fixed solver parameters mean the same inputs always
  produce the same canonical plan (tested in `test_solver_determinism.py`).

Documented simplifications (not hidden -- see the docstring at the top of `solver.py`): a task is
anchored to a single calendar day; "overtime" is minutes beyond an 8h/day standard threshold up to
the hard per-day cap; operator-certification is enforced at the task level rather than pinning a
specific operator to a specific unit; in-model travel *cost* uses a home-location distance proxy
(travel *feasibility*, C9, is exact and pairwise).

## Agent tools

`check_data_completeness`, `query_resources`, `optimize_schedule`, `detect_conflicts`,
`calculate_cost`, `run_what_if`, `apply_change`, `assess_risks` -- all implemented in
`backend/app/ai/tools.py`, all backed by real services, all validated with Pydantic before
execution.

## Known limitations

- **Infeasibility explanations are sufficient, not minimal.** CP-SAT's assumptions API returns *a*
  set of constraints whose removal would make the problem feasible, not necessarily the smallest
  such set. On a real project this can list more constraints than strictly necessary; the true
  cause is always included, but a human still needs to skim the list.
- **Celery dispatch is present but only exercised via the in-process fallback in this build.**
  `backend/app/jobs/celery_app.py` and `solve_schedule_task` are real, runnable Celery code (used
  by `docker-compose.yml`'s `worker` service), but this environment had no Docker daemon available
  to run and test an actual multi-process Celery deployment end-to-end. The in-process fallback
  (`run_job_inprocess`, used automatically when `CELERY_ENABLED=false` or no broker is reachable)
  was exercised and tested directly.
- **The in-process job store is a single-process, in-memory dict.** Fine for local dev or a single
  backend replica; a multi-replica deployment should poll job status from Celery's result backend
  instead (noted in `jobs/tasks.py`).
- **The "Map view" from the spec is not a Mapbox map.** No Mapbox token was available in this
  environment; the Travel tab presents the same information (routes, distance, measured/estimated
  labeling) as a table instead of a rendered map. Swapping in `mapbox-gl` against `MAPBOX_TOKEN`
  is a frontend-only change.
- **Shared-transport grouping** (`routing/shared_transport.py`) is implemented and unit-testable
  but not yet wired into the main plan-generation flow or exposed in the UI.
- **UI was verified via direct HTTP calls against the running backend and a Vite dev-server proxy
  check, plus `tsc`/`vite build`, not by driving a real browser** -- no headless-browser tool was
  available in this environment. The backend's actual behavior (auth, RBAC, CRUD, optimize →
  schedule → conflicts → costs → risks → approve) was verified end-to-end over real HTTP, including
  against the realistic seeded project.
- **Seed data intentionally includes two adversarial cases**: a task requiring a role no one holds
  (`Specialist pyrotechnics rig` -- exercises the infeasibility-explanation path) and a crew
  member whose crane certification expired last month (`Drew Nguyen` -- exercises certification
  expiry checked against the task date, not the planning date). Running `/plans/optimize` on the
  full seeded project is *expected* to return `INFEASIBLE`; pass an explicit `task_ids` list
  excluding the pyrotechnics task to see a feasible plan.
- **Adversarial "does the agent hallucinate" testing requires a live Anthropic API key** and was
  not run against the real model in this environment (no key configured here). What *is* tested
  without a key is the harness itself: tool-argument validation, the tool-call loop mechanics, and
  its iteration-limit safeguard (`tests/test_agent_tools.py`).
