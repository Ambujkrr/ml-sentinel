# Verification record

Commands are run from the independent `ML-Sentinel` project root using its `.venv`.
Automated tests apply Alembic migrations to disposable SQLite databases and do
not connect to any developer or production database.

## Stage gates

| Stage | Verification |
| --- | --- |
| 2: domain and ingestion | 33 tests passed; imports and compilation passed |
| 3: profiling and data quality | 62 tests passed; imports and compilation passed |
| 4: statistical drift and history | 71 tests passed; imports and compilation passed |
| 5: prediction and classification | 78 tests passed; imports and compilation passed |
| 6: result-based alerts | 80 tests passed; imports and compilation passed |
| 7: dashboard | 82 tests passed; Python imports/compilation and JavaScript syntax passed |
| 8: deterministic demo | 83 tests passed; imports and compilation passed |
| 9: request hardening | 85 tests passed; imports and compilation passed |
| 10: full workflow tests | 86 tests passed; dependency and JavaScript checks passed |
| 11: Docker preparation | Compose config valid, one Alembic head (`0005`); 86 tests passed |
| 12: deployment preparation | Compose config valid; 86 tests passed; dependency check passed |
| 13: documentation and final checks | 86 tests passed; imports, Python compilation, JavaScript syntax, Compose config, and `pip check` passed |

## Live local verification

An empty SQLite database was migrated from base to Alembic `0005 (head)`.
The local API and dashboard then ran against that database on port 8765, using
the ignored `.verification/` directory for its database and uploads.
`scripts/verify_live.py` completed the full HTTP workflow: register one model,
upload three demo datasets, profile all three, run normal and shifted
comparisons, retrieve their history and details, and list generated alerts.
The resulting database contained one model, three datasets, three profiles,
two monitoring runs, and seven alerts. The normal sample had zero drifted
features; the shifted sample had five. Its macro F1 fell by 0.467.

The rendered dashboard displayed those persisted counts and the shifted run's
feature-level results. Its browser console had no errors or warnings.

## Docker and PostgreSQL verification

Docker Desktop 4.92.0 with Engine 29.8.0 (`linux/amd64`) was reachable. The API
image built successfully. A separate
Compose project, `ml-sentinel-final-verification`, started with new PostgreSQL
and upload volumes and an ephemeral random local database password. The
PostgreSQL 17.11 container became healthy and the API container served requests.
No existing Compose project or database volume was changed.

The fresh PostgreSQL volume ran `initdb`; API startup applied `alembic upgrade
head`. `alembic current` and a direct query of PostgreSQL's `alembic_version`
table both reported `0005`. The public schema contained `alembic_version`,
`monitored_models`, `datasets`, `dataset_profiles`, `monitoring_runs`, and
`alerts`.

The existing `scripts/verify_live.py` workflow was run against the Docker API
on port 8000. All three synthetic demo files were uploaded, profiled, and
compared. Direct PostgreSQL queries found one model, three datasets, three
profiles, two runs, and seven alerts. The normal run had zero of seven drifted
features and no F1 drop. The shifted run had five of seven drifted features,
and macro F1 fell from 0.909 to 0.442 (drop 0.467). Prediction drift was
calculated with a chi-square test and was healthy in both runs. Alert types were
five `DATA_DRIFT`, one `DATA_QUALITY`, and one `PERFORMANCE_DEGRADATION`.

After restarting only the API container, its HTTP responses still showed one
model, two runs, seven alerts, and drift counts of zero and five; direct SQL
counts were unchanged. The rendered dashboard showed the persisted counts,
feature-level run details, and drifted dataset's quality report. Its browser
console had no errors or warnings. The complete test suite was rerun: 86
passed, with one dependency deprecation warning.

API logs contained no exceptions, database errors, or HTTP 500 responses.
PostgreSQL logs contained no errors. Its fresh `initdb` printed routine warnings
about unavailable locales and trust authentication for *local* connections.
No remote deployment was attempted. The isolated verification containers and
volumes were left running for inspection; their ephemeral password was not
written to the repository, so avoid recreating this verification project with
the example environment file. For a reproducible long-term Compose setup,
create an ignored `.env` with matching database credentials as described in
the README.
