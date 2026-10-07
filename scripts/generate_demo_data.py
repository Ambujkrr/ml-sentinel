"""Generate small, reproducible loan-risk CSVs for an interview walkthrough."""
from pathlib import Path

import numpy as np
import pandas as pd


def build_demo(output_dir: Path) -> None:
    rng = np.random.default_rng(20261007)
    rows = 240
    segments = rng.choice(["salaried", "self-employed", "contract"], rows,
                          p=[0.55, 0.30, 0.15])
    reference = pd.DataFrame({
        "age": rng.integers(23, 64, rows),
        "income": rng.uniform(35_000, 110_000, rows).round(2),
        "credit_score": rng.integers(570, 810, rows),
        "loan_amount": rng.uniform(8_000, 42_000, rows).round(2),
        "employment_years": rng.uniform(1, 18, rows).round(1),
        "debt_ratio": rng.uniform(0.15, 0.48, rows).round(3),
        "segment": segments,
    })
    risk = (reference["credit_score"].to_numpy() < 680).astype(int)
    risk |= (reference["debt_ratio"].to_numpy() > 0.39).astype(int)
    reference["actual"] = risk
    reference["prediction"] = np.where(rng.random(rows) < 0.08, 1 - risk, risk)
    normal = reference.sample(frac=1, random_state=100).reset_index(drop=True)

    drifted = reference.sample(frac=1, random_state=200).reset_index(drop=True).copy()
    drifted["income"] = (drifted["income"] * 0.72).round(2)
    drifted["credit_score"] = (drifted["credit_score"] - 85).clip(lower=300)
    drifted["loan_amount"] = (drifted["loan_amount"] * 1.45).round(2)
    drifted["debt_ratio"] = (drifted["debt_ratio"] + 0.13).clip(upper=0.95).round(3)
    drifted.loc[:69, "segment"] = "gig-worker"
    drifted.loc[::20, "credit_score"] = np.nan
    current_risk = ((drifted["credit_score"].fillna(620).to_numpy() < 680)
                    | (drifted["debt_ratio"].to_numpy() > 0.39)).astype(int)
    drifted["actual"] = current_risk
    drifted["prediction"] = np.where(rng.random(rows) < 0.38,
                                      1 - current_risk, current_risk)

    output_dir.mkdir(parents=True, exist_ok=True)
    reference.to_csv(output_dir / "reference.csv", index=False)
    normal.to_csv(output_dir / "production_normal.csv", index=False)
    drifted.to_csv(output_dir / "production_drifted.csv", index=False)


if __name__ == "__main__":
    build_demo(Path(__file__).resolve().parents[1] / "demo")
