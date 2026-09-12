"""Rule 8 (build doc section 51/13): same inputs + same solver configuration
must produce the same canonical plan. Non-determinism destroys user trust."""
from app.optimization.solver import solve_with_explanation


def _canonical(result):
    return (
        result.status,
        tuple(sorted(result.task_schedule.items())) if result.task_schedule else None,
        tuple(sorted((k, tuple(sorted(v))) for k, v in (result.crew_assignments or {}).items())),
    )


def test_same_inputs_produce_same_plan(single_site_problem):
    result_a, _ = solve_with_explanation(single_site_problem)
    result_b, _ = solve_with_explanation(single_site_problem)
    assert _canonical(result_a) == _canonical(result_b)
