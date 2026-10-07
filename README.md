# ML Sentinel

**Machine Learning Monitoring & Drift Detection Platform**

ML Sentinel is a working web application for comparing reference and production
CSV datasets after a model is deployed. It profiles uploaded data, calculates
drift and classification performance when columns are available, records each
run, and generates alerts from the results. The dashboard reads these results
from the API; it does not contain hardcoded monitoring values.

## Overview

Register a model, upload a reference dataset, then upload production data. Run a
comparison to see feature distributions, schema changes, data quality, optional
prediction drift, and optional classification metrics. Inspect past runs and
resolve alerts through the dashboard or API.

## Problem Statement

A model can remain deployed while its inputs, predictions, and accuracy change.
Without monitoring, a team may discover the problem only after users are
affected. ML Sentinel turns batches of observed data into reviewable signals.

## Why ML Monitoring Matters

Reference data represents the baseline conditions used to assess a model;
production data represents observations arriving after deployment. A change
between them may signal new user behavior, upstream data errors, or model risk.
Statistical drift does not prove that the model is wrong, but it identifies
where investigation is warranted. Labels, when available, allow direct
performance measurement rather than inference from drift alone.

## Features

- Monitored model registration and version metadata
- Controlled CSV ingestion with size, shape, encoding, and filename validation
- Persistent dataset profiles and data quality reports
- Numeric KS and PSI, categorical chi-square or Fisher exact testing, and schema comparisons
- Optional prediction distribution and multiclass classification monitoring
- Persisted run history and derived alerts with resolution state
- Responsive dashboard driven by API responses
- Deterministic loan risk demo datasets

No model training, automated streaming ingestion, authentication, or external
notification service is included.

## Architecture

```text
Browser dashboard → FastAPI routes → monitoring services → SQLAlchemy → PostgreSQL
                        │                    │
                        │                    └─ SciPy / pandas calculations
                        └─ local CSV storage (swappable behind LocalStorage)
```

Alembic owns schema evolution. The API stores dataset metadata, bounded profile
snapshots, monitoring reports, and alerts in PostgreSQL. CSV bytes live in an
upload directory, never in database rows. `LocalStorage` is a small boundary
where object storage can be added later.

## Tech Stack

Python 3.12+, FastAPI, Pydantic Settings, pandas, NumPy, SciPy, SQLAlchemy 2,
Psycopg 3, PostgreSQL, Alembic, pytest, HTTPX, Docker, and Docker Compose. The
dashboard uses plain HTML, CSS, JavaScript, and SVG, served by FastAPI.

## Monitoring Workflow

1. Register a monitored model (`POST /models`).
2. Upload a `reference` CSV and one or more `production` CSVs for that model.
3. Review each saved dataset profile and quality report.
4. Run `POST /monitoring/drift` with reference and production dataset IDs.
   Optionally pass `prediction_column` and `target_column`.
5. Inspect the report, distribution chart, run history, and derived alerts.

The comparison rejects datasets from different models or with the wrong roles.
Each run is a saved snapshot; results come from the CSV contents at run time.

## Data Drift Detection

For continuous numeric features, ML Sentinel compares finite values with the
two-sample Kolmogorov–Smirnov test. Its statistic is the largest difference
between two empirical cumulative distributions. The default drift signal is
`p < 0.05`. This is a configurable heuristic and can produce false positives,
especially across many features or on discrete values.

Population Stability Index (PSI) compares proportions in bins derived from
reference quantiles. A small probability floor handles empty bins. The defaults
are `PSI < 0.10` little shift, `0.10–0.25` moderate shift, and `> 0.25`
significant shift. These are configurable monitoring conventions, not universal
scientific cutoffs. Constant reference columns use an explicit value-change
check; the system does not fabricate a KS p-value or PSI for them.

Categorical columns use a chi-square comparison when expected counts are
sufficient. Sparse two-category tables use Fisher's exact test. Sparse larger
tables return an insufficient-data reason instead of an unreliable p-value.
New categories are included in the comparison. Schema drift identifies missing
columns, new columns, and incompatible inferred types. Missing-rate changes are
reported separately. Statistical tests with too few valid rows return a clear
reason; NaN and infinite numeric values are excluded from numerical tests.

Thresholds are in `app/core/config.py` and can be overridden by environment
variables. The thresholds used are saved with each run.

## Data Quality Monitoring

Each upload creates a persisted profile: inferred column type, missing count
and percentage, unique count, numeric summary statistics, and at most ten top
categories. Quality checks report missing values, duplicates, constant columns,
predominantly numeric columns with inconsistent strings, infinite numeric
values, and numerical outliers.

Outliers use the 1.5 × interquartile range rule with at least four finite
observations. When the IQR is zero, differing values are flagged. Results that
cannot be computed are `null` with a reason. Quality severity defaults to
critical for at least 20% missing values, 20% duplicate rows, 10% outliers, or
any infinite numeric values; other findings are warnings. These are review
thresholds, not automatic declarations that data is unusable.

## Model Performance Monitoring

Specify `prediction_column` to compare prediction distributions. Specify
`target_column` as well to calculate classification accuracy and macro-averaged
precision, recall, and F1 from rows containing both values. Binary and
multiclass labels are supported. Macro averaging gives each class equal weight.
The reference and production F1 scores use a shared class set, and a drop of
at least 0.10 raises a performance warning by default. Missing labels or
continuous/high-cardinality labels produce an unavailable result; metrics are
never invented. Regression metrics are future work.

## Alert System

Monitoring runs create alerts from actual schema changes, feature drift,
prediction drift, performance degradation, and production data quality.
Alerts have type, severity, message, model, run, timestamp, and optional
resolution time. `GET /alerts` supports model and unresolved filters;
`PATCH /alerts/{id}/resolve` marks an alert resolved. No email or paid service
is required.

## Dashboard

Open `/dashboard` to register models, upload datasets, run comparisons, inspect
profiles and quality findings, review status and history, compare numeric or
categorical distributions, view performance metrics, and resolve alerts. Charts
use saved monitoring reports from the API. The page has no sample values baked
into its markup and requires no separate frontend build process.

## Demo

The tracked `demo/` folder contains three synthetic loan risk datasets with
240 rows each: `reference.csv`, `production_normal.csv`, and
`production_drifted.csv`. They include age, income, credit score, loan amount,
employment years, debt ratio, employment segment, prediction, and actual label.
The normal file rearranges the reference rows, so its feature distributions are
unchanged. The drifted file lowers income and credit scores, raises loan amounts
and debt ratios, introduces a gig-worker segment, includes missing credit scores,
and has poorer predictions. Generate them again with:

```powershell
python scripts/generate_demo_data.py
```

Interview walkthrough:

1. Open `/dashboard`, register `Loan default risk`, version `demo-1`.
2. Upload `demo/reference.csv` as **reference**.
3. Upload `demo/production_normal.csv` as **production**.
4. Run monitoring, setting prediction column `prediction` and actual column
   `actual`. Show the unchanged feature distributions and saved run.
5. Upload `demo/production_drifted.csv` as **production** and run the same
   comparison. Show shifted numeric features, the new category, data quality
   findings, lower measured F1, and alerts.
6. Open the earlier run from history to compare it with the later result.

## API Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/`, `/health` | Application and health status |
| GET | `/dashboard` | Monitoring console |
| POST, GET | `/models` | Register and list models |
| GET | `/models/{model_id}` | Model details |
| POST, GET | `/models/{model_id}/datasets` | Upload and list model datasets |
| GET | `/datasets/{dataset_id}` | Dataset metadata |
| GET | `/datasets/{dataset_id}/profile` | Persisted column profile |
| GET | `/datasets/{dataset_id}/quality` | Persisted quality report |
| POST | `/monitoring/drift` | Calculate and save a comparison |
| GET | `/monitoring/runs`, `/monitoring/runs/{id}` | History and run details |
| GET | `/alerts` | Alerts, filterable by model and unresolved state |
| PATCH | `/alerts/{id}/resolve` | Resolve an alert |

Open `/docs` for request/response schemas and interactive API documentation.

## Database Design

`monitored_models` has many `datasets` and `monitoring_runs`. Each dataset has
one `dataset_profiles` row containing the bounded JSON profile and quality
snapshot. A run references a reference dataset and a production dataset,
records its status and JSON report, and has zero or more `alerts`.
Migration files `0001` through `0005` create and evolve these tables. Normal
startup uses `alembic upgrade head`, not `Base.metadata.create_all()`.

## Local Setup

From the cloned repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` to replace the example password. For a Python process running on
your computer, set the host in `DATABASE_URL` to `localhost` instead of `db`.
Start PostgreSQL (for example with `docker compose up -d db`), then:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

The API is at `http://localhost:8000`, with the dashboard at
`http://localhost:8000/dashboard`. Uploaded files are saved under
`data/uploads/` by default and ignored by Git.

## Docker Setup

Copy `.env.example` to `.env`, choose a local development password, and make
sure `POSTGRES_PASSWORD` and the password in `DATABASE_URL` match. The example
URL uses the Compose hostname `db`.

```powershell
docker compose up --build
```

Compose waits for PostgreSQL's health check. The API applies Alembic migrations
before serving requests. Database and upload files live in Docker volumes.
Stop containers with `docker compose down`; do not add `-v` unless you intend
to remove those volumes. Docker must have a running Linux engine.

## Testing

The suite applies real Alembic migrations to disposable SQLite databases and
uses temporary upload directories. It does not need a production database or
internet access.

```powershell
python -m pytest -q -p no:cacheprovider
python -m compileall -q app alembic tests scripts
python -m pip check
docker compose --env-file .env.example config -q
```

SQLite is used for isolated automated tests. A real PostgreSQL migration and
container workflow were also verified in an isolated Docker Compose project.
See `docs/verification.md` for the exact results and remaining deployment
considerations.

## Deployment

Use a Docker web service plus PostgreSQL. Set `DATABASE_URL`, `APP_ENV`, and
`UPLOAD_DIR`. The container reads `PORT` when set and runs migrations before
starting Uvicorn. Attach durable storage at the upload path: many hosts,
including Render by default, use ephemeral filesystems. See
[`docs/deployment.md`](docs/deployment.md) for a Render checklist. No deployment
or GitHub push was performed here.

## Project Structure

```text
app/api/routes/       HTTP endpoints
app/core/             Environment settings
app/db/               SQLAlchemy base and sessions
app/models/           Database entities
app/schemas/          Request and response models
app/services/         CSV ingestion and file storage
app/monitoring/       Profiling, drift, performance, alert rules
app/web/              Dashboard HTML, CSS, JavaScript
alembic/versions/     Database migrations
demo/                 Generated synthetic CSVs
scripts/              Deterministic demo generator
tests/                Isolated automated tests
docs/                 Deployment and verification notes
```

## Limitations

- There is no authentication or per-user isolation. Use synthetic data in a
  public demo; add access control before accepting sensitive data.
- Local uploads require a persistent disk and are tied to one application
  instance. Object storage would be needed for scaling across instances.
- Monitoring runs are triggered manually; there is no streaming or scheduler.
- KS p-values and PSI thresholds are signals, not proof of business impact.
  Many simultaneous feature tests can produce false positives.
- Classification metrics require labels. Regression, delayed labels, and
  statistical confidence intervals are future improvements.
- CSV size is capped at 10 MB, 100,000 rows, and 200 columns by default.

## Future Improvements

Add authentication, object storage, regression metrics, scheduled batch
monitoring, delayed-label updates, configurable per-model thresholds, and
multiple-testing correction. These are not implemented yet.

## Interview Explanation

**Why FastAPI, PostgreSQL, and Docker?** FastAPI gives validated APIs and
interactive docs. PostgreSQL stores durable metadata and monitoring history.
Docker makes the API and database setup repeatable.

**How does drift detection work?** KS compares numeric empirical
distributions; PSI compares binned proportions; chi-square or Fisher exact
compares categorical counts. Missing or changed columns are schema drift.
Small or invalid samples produce a reason rather than a misleading result.

**How is model health different from data drift?** Drift can occur without a
measured loss of accuracy. When actual labels exist, ML Sentinel computes
classification metrics and compares production F1 with the reference F1.

**How could this scale?** Replace local upload storage with object storage,
move heavy comparisons to background workers, add access control, and trigger
runs from an ingestion pipeline. Those changes are outside this portfolio
implementation's current scope.
