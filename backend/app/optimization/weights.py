from pathlib import Path

import yaml

from app.optimization.problem import ObjectiveWeights

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "optimization_weights.yaml"


def load_default_weights(path: Path | None = None) -> tuple[ObjectiveWeights, dict]:
    path = path or _DEFAULT_CONFIG_PATH
    if not path.exists():
        return ObjectiveWeights(), {"max_time_seconds": 120, "num_workers": 8, "relative_gap_limit": 0.02}
    data = yaml.safe_load(path.read_text()) or {}
    weights = ObjectiveWeights(**data.get("weights", {}))
    solver_cfg = data.get("solver", {"max_time_seconds": 120, "num_workers": 8, "relative_gap_limit": 0.02})
    return weights, solver_cfg
