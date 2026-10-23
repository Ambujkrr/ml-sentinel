# Administrator-only dataset deletion

This feature is disabled by default. No existing datasets are changed by its
migration, application startup, sign-in, or the deletion preview. It does not
authenticate the rest of the public demo application or establish upload ownership.
The administrator can delete eligible ordinary uploads from any model.

## Configure the existing Render service

Do this only after the code has been reviewed and deployment is authorized.
No plan upgrade, disk, external identity service, or new database is needed.

1. Open the existing **ml-sentinel** web service in Render, then **Environment**.
2. Keep the existing `DATABASE_URL`, `UPLOAD_DIR`, and `APP_ENV=production`.
3. Generate a random administrator password of at least 32 characters in a
   password manager (32 random bytes encoded as a URL-safe string is suitable).
   Do not use an ordinary short password, put it in Git, paste it into chat,
   pass it in a URL, or include it in logs. Save it securely for sign-in.
4. Add the following environment variables using Render's secret values:

   | Variable | Value |
   | --- | --- |
   | `ADMIN_USERNAME` | Your chosen non-empty administrator username, at most 80 characters |
   | `ADMIN_PASSWORD` | The random secret, 32–256 characters, no whitespace |
   | `ADMIN_ALLOWED_ORIGIN` | `https://ml-sentinel.onrender.com` (exactly, without a trailing slash) |
   | `DATASET_DELETION_ENABLED` | `true` |

5. Save the environment and deploy the approved version. Keep one Uvicorn
   worker and one service instance, as in the existing Dockerfile. The existing
   `alembic upgrade head` startup command applies revision `0006`, creating only
   the empty `pending_dataset_deletions` cleanup queue. Existing migrations and
   foreign-key relationships are unchanged; there is no cascading deletion.
6. Open `https://ml-sentinel.onrender.com/dashboard`, choose **Administrator
   sign-in**, and enter the username and password in the dedicated form.
   Sign-in redirects to the dashboard. Do not verify by deleting existing data;
   use a newly uploaded, disposable synthetic dataset only when deletion testing
   is explicitly authorized.
7. To disable deletion again, set `DATASET_DELETION_ENABLED=false` and redeploy.
   Missing/short credentials, an invalid origin, or HTTP in production also
   disable the feature. Rotating the password and redeploying revokes sessions.

For local testing only, use an exact loopback origin such as
`http://127.0.0.1:8766`, `APP_ENV=development`, and a disposable test database and
upload directory. Local HTTP origins are rejected in production.

## What deletion does

- Shared synthetic demo dataset IDs and every dataset belonging to the shared
  demo model are permanently rejected on the server, even for administrators.
- A dataset used as either the reference or production input of any saved run
  returns HTTP 409. Its metadata, profile, CSV, run reports, and alerts remain.
- The Actions column keeps View report available to everyone and shows Delete
  only to signed-in administrators for ordinary datasets. If Delete is missing,
  check `/admin/session`: `enabled: false` means configuration is incomplete or
  disabled; `authenticated: false` requires administrator sign-in.
- The confirmation dialog displays the dataset name, unique database ID, and every kind of data to
  be removed. Cancel, Escape, or a preview request alone changes nothing.
- An eligible deletion removes dataset metadata and its stored profile/quality
  report in one transaction. No model, monitoring run, report, or alert is deleted.
- The server checks relationships again during deletion. Row locks and existing
  database foreign keys guard races with monitoring. SQLite uses a write lock
  before checking usage and enables foreign-key enforcement.
- The CSV is removed only after the metadata transaction commits. A file already
  missing from Render's ephemeral filesystem is treated as successfully cleaned.
  Paths escaping the upload directory and symbolic links are rejected.
- Before file cleanup (including retries), surviving dataset references to that
  storage key are checked. A shared CSV is retained until its last dataset is
  deleted. Current uploads already enforce unique storage keys; this check also
  protects legacy shared paths. No schema changes are required for this fix.

## Failure recovery

Filesystem operations and database transactions cannot commit atomically.
Revision `0006` supplies a small durable cleanup queue to make that explicit:

1. Database failure before commit: the metadata/profile changes roll back, no
   file is removed, and the request returns HTTP 503.
2. File-removal failure after commit: the dataset is already absent from the
   dataset list, its CSV cleanup task remains in PostgreSQL, and HTTP 503
   explicitly reports that cleanup is pending. The administrator panel displays
   **Retry file cleanup** and provides a new confirmation before retrying.
3. Failure recording successful cleanup: the task remains; retry is safe even
   though the file is already gone.
4. Process restart: the queue survives in PostgreSQL. Sign in again and retry.
   No automatic startup deletion runs. Database expiry/deletion loses this
   queue along with other application records.

This avoids claiming that a partially completed deletion succeeded. Cleanup
tasks contain only the dataset ID/name and server-generated storage key; they
contain no credentials or CSV rows and are removed after cleanup completes.

## Authentication and operating limits

- Native HTML form submission sends credentials directly to the server; the
  dashboard JavaScript never reads, stores, embeds, or returns them. Configuration
  uses redacted secret types; request bodies and cookies are not logged.
- Successful sign-in issues a fresh, opaque 256-bit random session token in a
  host-only, HttpOnly, SameSite=Strict cookie, with Secure required in production.
  Only a hash of that token is kept server-side. Sessions expire after 15 minutes
  and are revoked by sign-out, a process restart, or credential rotation.
- The feature accepts at most five sign-in attempts per minute per process and
  retains at most eight sessions. A new session beyond that cap revokes the
  oldest. A public attacker can temporarily consume the sign-in budget; it does
  not affect public demo use. This is not a distributed anti-abuse service.
- All delete and logout requests require both an authenticated session and the
  exact configured Origin plus a custom action header. No cross-origin access
  is enabled. The sign-in POST also checks the configured Origin. Session status,
  sign-in pages, previews, and cleanup responses use `Cache-Control: no-store`.
- Sessions/rate limits are in memory for the current single-worker deployment.
  Multiple workers/instances need a shared session and throttling store first.
  Free-service restarts require signing in again; they never grant access.
- This adds no per-user ownership model, password recovery, MFA, or authorization
  for existing general model/upload/monitoring APIs. Those remain public as before.

The cookie and request-origin defenses follow the
[OWASP session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
and [CSRF prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## Implementation file inventory

- Configuration and authentication: `.env.example`, `app/core/config.py`,
  `app/core/admin.py`, `app/api/routes/admin.py`, `app/web/admin-login.html`.
- Deletion and database safety: `app/api/routes/datasets.py`,
  `app/api/routes/monitoring.py`, `app/services/deletion.py`,
  `app/services/storage.py`, `app/db/session.py`, `app/models/domain.py`,
  `app/models/__init__.py`, `alembic/versions/0006_dataset_deletion_cleanup.py`.
- Dashboard and response protections: `app/main.py`, `app/web/dashboard.html`,
  `app/web/dashboard.js`, `app/web/dashboard.css`.
- Tests: `tests/conftest.py`, `tests/test_dataset_deletion.py`.
- Documentation: `README.md`, `docs/deployment.md`,
  `docs/administrator-deletion.md`.
