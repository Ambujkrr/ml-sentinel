# Render deployment preparation

ML Sentinel has been verified locally with Docker and PostgreSQL, but has **not
been deployed to Render**. The intended setup is one Docker web service plus a
Render PostgreSQL database. Use the manual setup below; a `render.yaml`
Blueprint would hide the important free-versus-paid storage choice.

## Choose storage before deploying

The application stores uploaded CSVs in `UPLOAD_DIR` and only their metadata in
PostgreSQL. A **paid Render web service with a persistent disk** mounted at
`/app/data/uploads` is required if uploaded datasets must remain usable after a
restart or redeploy. Set `UPLOAD_DIR` to that same absolute path. The Docker
image creates the directory for its non-root application user; after attaching
the disk, verify a synthetic upload succeeds before relying on it.

A **Free web service cannot attach a persistent disk**. Its uploads may
disappear when the service restarts or redeploys, while PostgreSQL metadata
remains; a later comparison of those datasets will return HTTP 409 because the
CSV file is unavailable. Use the Free plan only for a disposable demo, not as
a persistent monitoring installation. Render's Free PostgreSQL databases also
currently expire after 30 days and do not have managed backups. Check current
plan terms before choosing a service. A persistent disk permits only one web
service instance and disables zero-downtime deploys.

The dashboard's **Load Demo Data** feature is an exception to the upload-file
limitation: it initializes a single protected synthetic model from the CSVs
bundled in the Docker image, then serves saved profiles, comparisons, and alerts
from PostgreSQL. It writes no CSVs to the upload directory, and repeated loads
or comparison clicks do not add records. No additional environment variables,
disk, migration, or paid service is needed. Ordinary user uploads still depend
on local CSV files, and database expiry still removes the demo's saved state.

## Manual Render setup, when deployment is authorized

1. Create a Render PostgreSQL database. Put it in the same region as the future
   web service. Choose a database plan appropriate to the intended lifetime;
   a Free database is temporary. Keep the **internal** connection URL secret.
2. Create a Web Service connected to the
   [ML Sentinel GitHub repository](https://github.com/Ambujkrr/ml-sentinel),
   select the `main` branch and **Docker** runtime, and use the
   repository-root `Dockerfile`.
   Do not use `docker-compose.yml` as the Render service definition.
3. Set the web service environment variables:

   | Key | Value |
   | --- | --- |
   | `DATABASE_URL` | Render PostgreSQL's internal connection URL (secret) |
   | `APP_ENV` | `production` |
   | `UPLOAD_DIR` | `/app/data/uploads` |

   `APP_NAME` is optional. Render supplies `PORT`; do not copy the local
   `.env.example` database URL, password, or Compose hostname `db` into Render.
   Configuration accepts Render's `postgresql://` URL and selects Psycopg 3;
   Alembic and the application read the same `DATABASE_URL`.
4. For durable uploads, select a paid web-service plan and attach a persistent
   disk at **exactly** `/app/data/uploads` before uploading data. If using the
   Free plan, do not attach a disk or claim that uploads persist.
5. Set the HTTP health-check path to `/health`. It returns 200 only when the
   application can execute a database query, and 503 if the database is
   unavailable. Leave the Docker build and start commands at their defaults.
6. When ready to deploy, inspect the build and service logs. The Dockerfile's
   command runs `alembic upgrade head` before Uvicorn starts, then binds to
   `0.0.0.0` on `${PORT:-8000}`. This works on plans without Render's paid
   pre-deploy command and keeps the migration strategy in one place. Run only
   one service instance for this version; future schema changes must consider
   compatibility with an instance still running an older version.
7. After deployment, confirm `/`, `/health`, and `/dashboard` respond, inspect
   logs for migration or database errors, and upload only the tracked synthetic
   demo CSVs. Verify profile, monitoring run, and alert views. With a disk,
   restart the service and confirm the uploaded CSVs remain usable.

## Security and operational limits

The dashboard and APIs have **no authentication or per-user isolation**. A
public URL therefore exposes model data and allows anyone to submit bounded
CSV uploads and monitoring requests. Use only synthetic, non-sensitive data;
add access control before accepting private or real production datasets. CSV
uploads are limited to 10 MB, 100,000 rows, and 200 columns by default. The
application uses server-generated storage keys, rejects path traversal, and
returns generic errors for unexpected failures. Request logs do not include
uploaded CSV contents. No cloud-storage credentials or paid object-storage
service are required.

No Render resources were created as part of this preparation. See Render's
[Docker guide](https://render.com/docs/docker), [web-service and port guide](https://render.com/docs/web-services),
[health-check guide](https://render.com/docs/health-checks),
[persistent-disk guide](https://render.com/docs/disks), and
[Free-plan limitations](https://render.com/docs/free) for current platform
details.
