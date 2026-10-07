from pathlib import Path

import pandas as pd

from scripts.generate_demo_data import build_demo
from app.monitoring.drift import compare_datasets
from app.monitoring.performance import compare_performance
from app.monitoring.profiling import profile_dataset


def test_demo_is_deterministic_and_shows_meaningful_shift(tmp_path: Path):
    build_demo(tmp_path)
    first = {path.name: path.read_bytes() for path in tmp_path.glob("*.csv")}
    build_demo(tmp_path)
    assert first == {path.name: path.read_bytes() for path in tmp_path.glob("*.csv")}
    ref = pd.read_csv(tmp_path / "reference.csv")
    normal = pd.read_csv(tmp_path / "production_normal.csv")
    shifted = pd.read_csv(tmp_path / "production_drifted.csv")
    assert len(ref) == len(normal) == len(shifted) == 240
    assert compare_datasets(ref, normal)["drifted_feature_count"] == 0
    drift = compare_datasets(ref, shifted)
    assert drift["drifted_feature_count"] >= 3
    assert shifted["credit_score"].mean() < ref["credit_score"].mean()
    assert shifted["loan_amount"].mean() > ref["loan_amount"].mean()
    assert "gig-worker" in set(shifted["segment"])
    assert profile_dataset(shifted)["quality"]["issues"]
    perf = compare_performance(ref, shifted, "prediction", "actual")
    assert perf["status"] == "warning"
