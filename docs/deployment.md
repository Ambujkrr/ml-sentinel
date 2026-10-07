# Deployment preparation

ML Sentinel can run as one Docker web service backed by PostgreSQL. Deployment
has not been performed from this repository.

## Render walkthrough

1. Create a PostgreSQL database in Render. Keep its connection string secret.
2. Create a Docker web service from this independent repository when you are
   ready to publish it. Set its health check path to `/health`.
3. Set `DATABASE_URL` to the database's private connection string, `APP_ENV` to
   `production`, and `UPLOAD_DIR` to `/app/data/uploads`. A plain
   `postgresql://` URL is normalized to the Psycopg 3 driver by configuration.
4. Attach a persistent disk at `/app/data/uploads` **before accepting uploads**.
   Render's filesystem otherwise loses uploaded files after restarts or deploys.
   A disk is available only to one service instance; future horizontal scaling
   would require replacing `LocalStorage` with object storage.
5. The Docker start command runs `alembic upgrade head` and then starts Uvicorn.
   It reads the platform's `PORT` variable, falling back to 8000 locally.
   Check `/health` and `/dashboard` after the deployment.

The current dashboard and APIs have **no authentication**. Use only synthetic or
non-sensitive datasets in a public demonstration and add access control before
using private production data. Local paths must remain under `UPLOAD_DIR`.

Migrations can also be run explicitly:

```bash
alembic upgrade head
```

Start command without Docker:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

See the [Render Docker guide](https://render.com/docs/docker) and
[persistent disk guide](https://render.com/docs/disks) for current platform
details and plan availability.
