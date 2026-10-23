"""All deletions in this module target freshly created, disposable test data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select, MetaData, UniqueConstraint
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import admin
from app.db.base import Base
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.domain import (Alert, Dataset, DatasetProfile, MonitoredModel,
                               MonitoringRun, PendingDatasetDeletion)
from app.services.demo import DEMO_DATASET_IDS, DEMO_MODEL_ID
from app.services.storage import LocalStorage, get_storage
from app.services.deletion import delete_dataset

ORIGIN = "http://localhost"
HEADERS = {"Origin": ORIGIN, "X-Admin-Action": admin.ACTION_HEADER}


@pytest.fixture
def credentials(monkeypatch):
    settings = get_settings()
    values = {"username": "test-" + secrets.token_hex(8), "password": secrets.token_urlsafe(32)}
    monkeypatch.setattr(settings, "DATASET_DELETION_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", SecretStr(values["username"]))
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", SecretStr(values["password"]))
    monkeypatch.setattr(settings, "ADMIN_ALLOWED_ORIGIN", ORIGIN)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    admin.admin_sessions.reset()
    yield values
    admin.admin_sessions.reset()


def sign_in(client, credentials, origin=ORIGIN):
    response = client.post("/admin/login", data=credentials, headers={"Origin": origin}, follow_redirects=False)
    assert response.status_code == 303
    return response


@pytest.fixture
def signed_in(client, credentials):
    sign_in(client, credentials)
    return client


def delete(client, dataset_id):
    return client.delete(f"/datasets/{dataset_id}", headers=HEADERS)


def counts(db):
    return tuple(db.scalar(select(func.count()).select_from(model)) for model in
                 (MonitoredModel, Dataset, DatasetProfile, MonitoringRun, Alert, PendingDatasetDeletion))


def test_disabled_by_default_even_with_action_headers(client, upload_dataset, db, storage):
    uploaded = upload_dataset().json()
    before = counts(db)
    assert client.get("/admin/session").json() == {"enabled": False, "authenticated": False}
    assert client.get("/admin/login").status_code == 404
    assert delete(client, uploaded["id"]).status_code == 404
    assert counts(db) == before
    assert storage.read(db.get(Dataset, uploaded["id"]).file_path)


@pytest.mark.parametrize("setting,value", [
    ("DATASET_DELETION_ENABLED", False), ("ADMIN_USERNAME", SecretStr("")),
    ("ADMIN_PASSWORD", SecretStr("")), ("ADMIN_PASSWORD", SecretStr("too-short")),
    ("ADMIN_PASSWORD", SecretStr(" " * 32)),
    ("ADMIN_ALLOWED_ORIGIN", ""), ("ADMIN_ALLOWED_ORIGIN", "https://example.com/path"),
    ("ADMIN_ALLOWED_ORIGIN", "https://example.com/"),
    ("ADMIN_ALLOWED_ORIGIN", "https://user:password@example.com"),
    ("ADMIN_ALLOWED_ORIGIN", "http://public.example"),
    ("ADMIN_ALLOWED_ORIGIN", "HTTPS://example.com"),
    ("ADMIN_ALLOWED_ORIGIN", "https://example.com:invalid"),
])
def test_incomplete_or_unsafe_configuration_fails_closed(client, credentials, monkeypatch, setting, value):
    monkeypatch.setattr(get_settings(), setting, value)
    assert client.get("/admin/session").json() == {"enabled": False, "authenticated": False}
    assert client.post("/admin/login", data=credentials, headers=HEADERS).status_code == 404
    assert delete(client, uuid4()).status_code == 404


def test_http_origin_forbidden_in_production(client, credentials, monkeypatch):
    monkeypatch.setattr(get_settings(), "APP_ENV", "production")
    assert not client.get("/admin/session").json()["enabled"]


def test_login_issues_secure_host_only_httponly_cookie(client, credentials, monkeypatch, caplog):
    origin = "https://ml-sentinel.example"
    monkeypatch.setattr(get_settings(), "ADMIN_ALLOWED_ORIGIN", origin)
    monkeypatch.setattr(get_settings(), "APP_ENV", "production")
    with TestClient(app, base_url=origin) as secure_client:
        page = secure_client.get("/admin/login")
        assert page.status_code == 200
        assert "<script" not in page.text
        assert "form-action 'self'" in page.headers["content-security-policy"]
        assert page.headers["referrer-policy"] == "same-origin"
        response = sign_in(secure_client, credentials, origin)
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" in cookie
        assert "Domain=" not in cookie and "Max-Age=900" in cookie
        status = secure_client.get("/admin/session")
        assert status.json() == {"enabled": True, "authenticated": True}
        assert status.headers["cache-control"] == "no-store"
        for secret in credentials.values():
            assert secret not in response.text + cookie + status.text + page.text + caplog.text
            assert secret not in secure_client.get("/assets/dashboard.js").text


def test_unauthenticated_and_forged_sessions_cannot_delete(client, credentials, upload_dataset, db, storage):
    uploaded = upload_dataset().json()
    before = counts(db)
    assert delete(client, uploaded["id"]).status_code == 401
    assert client.get(f"/datasets/{uploaded['id']}/deletion-preview").status_code == 401
    assert client.get("/admin/deletions").status_code == 401
    client.cookies.set(admin.COOKIE_NAME, secrets.token_urlsafe(32))
    assert delete(client, uploaded["id"]).status_code == 401
    assert counts(db) == before
    assert len(list(storage.root.glob("*.csv"))) == 1


@pytest.mark.parametrize("origin,action", [(None, admin.ACTION_HEADER), ("https://attacker.example", admin.ACTION_HEADER),
                                          ("null", admin.ACTION_HEADER), (ORIGIN, None), (ORIGIN, "wrong")])
def test_csrf_guards_are_server_enforced(signed_in, upload_dataset, db, origin, action):
    uploaded = upload_dataset().json()
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    if action is not None:
        headers["X-Admin-Action"] = action
    before = counts(db)
    assert signed_in.delete(f"/datasets/{uploaded['id']}", headers=headers).status_code == 403
    assert counts(db) == before


def test_login_csrf_and_failed_credentials_do_not_echo_secrets(client, credentials, caplog):
    assert client.post("/admin/login", data=credentials).status_code == 403
    assert client.post("/admin/login", data=credentials, headers={"Origin": "https://attacker.example"}).status_code == 403
    wrong = {**credentials, "password": secrets.token_urlsafe(32)}
    response = client.post("/admin/login", data=wrong, headers=HEADERS)
    assert response.status_code == 401
    assert all(secret not in response.text + caplog.text for secret in wrong.values())
    assert not client.get("/admin/session").json()["authenticated"]


def test_login_request_bounds_and_no_parameter_support(client, credentials):
    response = client.post("/admin/login", content=b"x" * 2049,
                           headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 413
    assert client.post("/admin/login?redirect=other", data=credentials, headers=HEADERS).status_code == 400
    assert client.post("/admin/login", json=credentials, headers=HEADERS).status_code == 400
    assert client.post("/admin/login", content="username=one&username=two&password=three",
                       headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}).status_code == 401


def test_login_throttling_has_bounded_memory_and_cooldown(client, credentials, monkeypatch):
    for _ in range(5):
        assert client.post("/admin/login", data={"username": "wrong", "password": "wrong"}, headers=HEADERS).status_code == 401
    response = client.post("/admin/login", data=credentials, headers=HEADERS)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert len(admin.admin_sessions.attempts) == 5
    now = admin.monotonic()
    monkeypatch.setattr(admin, "monotonic", lambda: now + 61)
    sign_in(client, credentials)


def test_logout_rejects_cross_origin_without_revoking_the_session(signed_in):
    assert signed_in.post("/admin/logout", headers={"Origin": "https://attacker.example",
                                                   "X-Admin-Action": admin.ACTION_HEADER}).status_code == 403
    assert signed_in.get("/admin/session").json()["authenticated"]


def test_session_memory_is_bounded_and_oldest_token_is_revoked(credentials):
    tokens = [admin.admin_sessions.create() for _ in range(10)]
    assert len(admin.admin_sessions.sessions) == 8
    assert not admin.admin_sessions.valid(tokens[0])
    assert admin.admin_sessions.valid(tokens[-1])


@pytest.mark.parametrize("revoke", ["logout", "expiry", "restart", "rotation", "disabled"])
def test_revocation_expiry_restart_rotation_and_disable(signed_in, credentials, upload_dataset, monkeypatch, revoke):
    uploaded = upload_dataset().json()
    token = signed_in.cookies.get(admin.COOKIE_NAME)
    if revoke == "logout":
        assert signed_in.post("/admin/logout", headers=HEADERS).status_code == 204
        signed_in.cookies.set(admin.COOKIE_NAME, token)
    elif revoke == "expiry":
        now = admin.monotonic()
        monkeypatch.setattr(admin, "monotonic", lambda: now + 901)
    elif revoke == "restart":
        admin.admin_sessions.reset()
    elif revoke == "rotation":
        monkeypatch.setattr(get_settings(), "ADMIN_PASSWORD", SecretStr(secrets.token_urlsafe(32)))
    else:
        monkeypatch.setattr(get_settings(), "DATASET_DELETION_ENABLED", False)
    assert delete(signed_in, uploaded["id"]).status_code == (404 if revoke == "disabled" else 401)


def test_unused_dataset_profile_quality_and_csv_are_removed(signed_in, upload_dataset, db, storage):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    preview = signed_in.get(f"/datasets/{uploaded['id']}/deletion-preview")
    assert preview.status_code == 200 and preview.json()["name"] == uploaded["name"]
    assert len(preview.json()["removes"]) == 3 and not preview.json()["cleanup_pending"]
    before = counts(db)
    assert before == (1, 1, 1, 0, 0, 0)
    assert delete(signed_in, uploaded["id"]).status_code == 204
    assert counts(db) == (1, 0, 0, 0, 0, 0)
    assert not storage._path(key).exists()
    assert signed_in.get(f"/datasets/{uploaded['id']}").status_code == 404
    assert signed_in.get(f"/datasets/{uploaded['id']}/profile").status_code == 404
    assert signed_in.get(f"/datasets/{uploaded['id']}/quality").status_code == 404
    assert delete(signed_in, uploaded["id"]).status_code == 404


def test_missing_csv_does_not_block_metadata_cleanup(signed_in, upload_dataset, db, storage):
    uploaded = upload_dataset().json()
    storage.delete(db.get(Dataset, uploaded["id"]).file_path)  # Disposable fixture CSV only.
    assert delete(signed_in, uploaded["id"]).status_code == 204
    assert counts(db) == (1, 0, 0, 0, 0, 0)


def test_duplicate_names_delete_only_selected_id(signed_in, upload_dataset, db, storage):
    first = upload_dataset(name="synthetic reference").json()
    second = upload_dataset(name="synthetic reference").json()
    survivor_key = db.get(Dataset, second["id"]).file_path
    content = storage.read(survivor_key)
    preview = signed_in.get(f"/datasets/{first['id']}/deletion-preview").json()
    assert preview["dataset_id"] == first["id"] and preview["name"] == second["name"]
    assert delete(signed_in, first["id"]).status_code == 204
    assert signed_in.get(f"/datasets/{second['id']}").status_code == 200
    assert storage.read(survivor_key) == content
    assert counts(db) == (1, 1, 1, 0, 0, 0)


def test_pending_cleanup_preserves_file_referenced_by_dataset(signed_in, upload_dataset, db, storage):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    original = storage.read(key)
    pending_id = str(uuid4())
    db.add(PendingDatasetDeletion(id=pending_id, dataset_name="Old record", file_path=key))
    db.commit()
    assert delete(signed_in, pending_id).status_code == 204
    assert storage.read(key) == original
    assert counts(db) == (1, 1, 1, 0, 0, 0)


def test_legacy_shared_file_is_removed_only_after_last_dataset(storage):
    # Disposable legacy schema without the current file_path uniqueness guard.
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    datasets = metadata.tables["datasets"]
    for constraint in list(datasets.constraints):
        if isinstance(constraint, UniqueConstraint):
            datasets.constraints.remove(constraint)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    metadata.create_all(engine)
    key = storage.save(b"synthetic\n1\n")
    try:
        with Session(engine, expire_on_commit=False) as db:
            model = MonitoredModel(name="Disposable shared-file fixture")
            db.add(model)
            db.flush()
            pair = [Dataset(model_id=model.id, name="Duplicate", dataset_type="reference",
                            file_name="shared.csv", file_path=key, row_count=1, column_count=1)
                    for _ in range(2)]
            db.add_all(pair)
            db.commit()
            first_id, second_id = [item.id for item in pair]
            delete_dataset(db, storage, first_id)
            assert storage.read(key) == b"synthetic\n1\n"
            assert db.get(Dataset, second_id) is not None
            delete_dataset(db, storage, second_id)
            assert not storage._path(key).exists()
    finally:
        engine.dispose()


def test_missing_legacy_profile_is_safe(signed_in, upload_dataset, db):
    uploaded = upload_dataset().json()
    db.delete(db.get(DatasetProfile, uploaded["id"]))
    db.commit()
    assert delete(signed_in, uploaded["id"]).status_code == 204
    assert counts(db) == (1, 0, 0, 0, 0, 0)


def test_demo_is_permanently_protected_even_if_not_seeded(signed_in, db):
    for dataset_id in DEMO_DATASET_IDS.values():
        assert delete(signed_in, dataset_id).status_code == 403
    assert counts(db) == (0, 0, 0, 0, 0, 0)


def test_demo_records_reports_and_alerts_are_unchanged(signed_in, db):
    data = signed_in.post("/demo/load").json()
    before = counts(db)
    reports = [signed_in.get(f"/monitoring/runs/{run_id}").json() for run_id in data["run_ids"].values()]
    alerts = signed_in.get("/alerts").json()
    for dataset_id in data["dataset_ids"].values():
        assert delete(signed_in, dataset_id).status_code == 403
        assert signed_in.get(f"/datasets/{dataset_id}/deletion-preview").status_code == 403
    assert counts(db) == before
    assert [signed_in.get(f"/monitoring/runs/{run_id}").json() for run_id in data["run_ids"].values()] == reports
    assert signed_in.get("/alerts").json() == alerts
    extra = Dataset(id=str(uuid4()), model_id=DEMO_MODEL_ID, name="Unexpected demo member",
                    dataset_type="production", file_name="extra.csv", file_path="extra.csv", row_count=1, column_count=1)
    db.add(extra)
    db.commit()
    assert delete(signed_in, extra.id).status_code == 403


def csv(start):
    return ("score\n" + "\n".join(str(i) for i in range(start, start + 100)) + "\n").encode()


@pytest.mark.parametrize("role", ["reference", "production"])
def test_both_dataset_roles_preserve_runs_reports_and_alerts(signed_in, upload_dataset, db, storage, role):
    ref = upload_dataset(csv(0), dataset_type="reference").json()
    prod = upload_dataset(csv(200), dataset_type="production").json()
    run = signed_in.post("/monitoring/drift", json={"reference_dataset_id": ref["id"],
                                                   "production_dataset_id": prod["id"]}).json()
    before = counts(db)
    alerts = signed_in.get("/alerts").json()
    target = ref if role == "reference" else prod
    key = db.get(Dataset, target["id"]).file_path
    content = storage.read(key)
    assert signed_in.get(f"/datasets/{target['id']}/deletion-preview").status_code == 409
    assert delete(signed_in, target["id"]).status_code == 409
    assert counts(db) == before and storage.read(key) == content
    assert signed_in.get(f"/monitoring/runs/{run['id']}").json() == run
    assert signed_in.get("/alerts").json() == alerts


def test_database_failure_keeps_csv_and_rolls_back_profiles(signed_in, upload_dataset, db, storage, monkeypatch, caplog):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    original = storage.read(key)
    with monkeypatch.context() as patch:
        def fail_commit():
            db.flush()
            raise SQLAlchemyError("private credential or SQL detail")
        patch.setattr(db, "commit", fail_commit)
        response = delete(signed_in, uploaded["id"])
    assert response.status_code == 503
    assert "private credential" not in response.text + caplog.text
    assert counts(db) == (1, 1, 1, 0, 0, 0) and storage.read(key) == original
    assert delete(signed_in, uploaded["id"]).status_code == 204


def test_foreign_key_conflict_returns_clear_error_without_removing_data(signed_in, upload_dataset, db, storage, monkeypatch):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    original = storage.read(key)
    with monkeypatch.context() as patch:
        def conflict():
            db.flush()
            raise IntegrityError("private SQL", {}, Exception("foreign key constraint"))
        patch.setattr(db, "commit", conflict)
        response = delete(signed_in, uploaded["id"])
    assert response.status_code == 409
    assert "still referenced" in response.json()["detail"]
    assert "private SQL" not in response.text
    assert counts(db) == (1, 1, 1, 0, 0, 0)
    assert storage.read(key) == original


def test_storage_failure_leaves_durable_retryable_cleanup(signed_in, upload_dataset, db, storage, monkeypatch, caplog):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    original = storage.read(key)
    with monkeypatch.context() as patch:
        def unavailable(_key):
            raise OSError("private filesystem location")
        patch.setattr(storage, "delete", unavailable)
        response = delete(signed_in, uploaded["id"])
    assert response.status_code == 503 and "cleanup is pending" in response.text
    assert "private filesystem" not in response.text + caplog.text
    assert counts(db) == (1, 0, 0, 0, 0, 1) and storage.read(key) == original
    pending = signed_in.get("/admin/deletions").json()
    assert pending == [{"dataset_id": uploaded["id"], "name": uploaded["name"]}]
    preview = signed_in.get(f"/datasets/{uploaded['id']}/deletion-preview").json()
    assert preview["cleanup_pending"] and len(preview["removes"]) == 1
    assert delete(signed_in, uploaded["id"]).status_code == 204
    assert counts(db) == (1, 0, 0, 0, 0, 0) and not storage._path(key).exists()


def test_cleanup_commit_failure_can_retry_after_file_is_gone(signed_in, upload_dataset, db, storage, monkeypatch):
    uploaded = upload_dataset().json()
    original_commit = db.commit
    commits = 0
    with monkeypatch.context() as patch:
        def fail_second_commit():
            nonlocal commits
            commits += 1
            if commits == 2:
                raise SQLAlchemyError("cleanup bookkeeping failed")
            original_commit()
        patch.setattr(db, "commit", fail_second_commit)
        assert delete(signed_in, uploaded["id"]).status_code == 503
    assert counts(db) == (1, 0, 0, 0, 0, 1)
    assert not list(storage.root.glob("*.csv"))
    assert delete(signed_in, uploaded["id"]).status_code == 204
    assert counts(db)[-1] == 0


def test_invalid_storage_path_leaves_metadata_untouched(signed_in, upload_dataset, db):
    uploaded = upload_dataset().json()
    dataset = db.get(Dataset, uploaded["id"])
    dataset.file_path = "../outside.csv"
    db.commit()
    assert delete(signed_in, uploaded["id"]).status_code == 503
    assert counts(db) == (1, 1, 1, 0, 0, 0)


def test_symlink_cannot_remove_a_different_dataset_file(signed_in, upload_dataset, db, storage):
    first = upload_dataset(name="Link fixture").json()
    second = upload_dataset(name="Protected target fixture").json()
    first_path = storage.root / db.get(Dataset, first["id"]).file_path
    second_path = storage.root / db.get(Dataset, second["id"]).file_path
    expected = second_path.read_bytes()
    first_path.unlink()  # Fresh disposable fixture file only.
    try:
        first_path.symlink_to(second_path)
    except OSError:
        pytest.skip("Symbolic links require platform support/Windows developer permissions")
    assert delete(signed_in, first["id"]).status_code == 503
    assert second_path.read_bytes() == expected
    assert counts(db) == (1, 2, 2, 0, 0, 0)


def test_symlink_guard_also_runs_on_file_cleanup(upload_dataset, db, storage, monkeypatch):
    uploaded = upload_dataset().json()
    key = db.get(Dataset, uploaded["id"]).file_path
    content = storage.read(key)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", lambda _self: True)
        with pytest.raises(ValueError):
            storage.delete(key)
    assert storage.read(key) == content


def test_deleting_unused_dataset_preserves_unrelated_history_and_demo(signed_in, upload_dataset, db):
    demo = signed_in.post("/demo/load").json()
    ref = upload_dataset(csv(0), dataset_type="reference").json()
    prod = upload_dataset(csv(200), dataset_type="production").json()
    run = signed_in.post("/monitoring/drift", json={"reference_dataset_id": ref["id"],
                                                   "production_dataset_id": prod["id"]}).json()
    extra = upload_dataset(name="Unused disposable batch").json()
    before = counts(db)
    alerts = signed_in.get("/alerts").json()
    assert delete(signed_in, extra["id"]).status_code == 204
    after = counts(db)
    assert after == (before[0], before[1] - 1, before[2] - 1, before[3], before[4], 0)
    assert signed_in.get("/alerts").json() == alerts
    assert signed_in.get(f"/monitoring/runs/{run['id']}").json() == run
    assert signed_in.post("/demo/load").json() == demo


def test_invalid_and_unknown_ids(signed_in):
    assert delete(signed_in, "not-a-uuid").status_code == 422
    assert delete(signed_in, uuid4()).status_code == 404


@pytest.fixture
def durable_api(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'deletion.sqlite').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 15})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    storage = LocalStorage(tmp_path / "uploads")
    def database():
        with Session(engine, expire_on_commit=False) as db:
            yield db
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, engine, storage
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def upload_pair(client):
    model = client.post("/models", json={"name": "Disposable deletion test"}).json()
    def upload(kind, start):
        return client.post(f"/models/{model['id']}/datasets", data={"name": kind, "dataset_type": kind},
                           files={"file": ("synthetic.csv", csv(start), "text/csv")}).json()
    return upload("reference", 0), upload("production", 200)


def test_concurrent_deletion_is_consistent(durable_api, credentials):
    client, engine, storage = durable_api
    sign_in(client, credentials)
    ref, _ = upload_pair(client)
    barrier = Barrier(2)
    def remove(_):
        barrier.wait(timeout=10)
        return delete(client, ref["id"]).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = list(workers.map(remove, range(2)))
    assert sorted(statuses) == [204, 404]
    with Session(engine) as db:
        assert counts(db) == (1, 1, 1, 0, 0, 0)
    assert len(list(storage.root.glob("*.csv"))) == 1


def test_cleanup_survives_connection_and_session_restart(durable_api, credentials, monkeypatch):
    client, engine, storage = durable_api
    sign_in(client, credentials)
    ref, _ = upload_pair(client)
    with monkeypatch.context() as patch:
        def fail(_):
            raise OSError("simulated file removal failure")
        patch.setattr(storage, "delete", fail)
        assert delete(client, ref["id"]).status_code == 503
    engine.dispose()
    admin.admin_sessions.reset()  # Simulated process restart revokes the cookie.
    assert delete(client, ref["id"]).status_code == 401
    sign_in(client, credentials)
    assert client.get("/admin/deletions").json() == [{"dataset_id": ref["id"], "name": ref["name"]}]
    assert delete(client, ref["id"]).status_code == 204
    with Session(engine) as db:
        assert counts(db) == (1, 1, 1, 0, 0, 0)


def test_comparison_racing_deletion_cannot_leave_orphaned_history(durable_api, credentials):
    client, engine, storage = durable_api
    sign_in(client, credentials)
    ref, prod = upload_pair(client)
    barrier = Barrier(2)
    def remove():
        barrier.wait(timeout=10)
        return delete(client, ref["id"]).status_code
    def monitor():
        barrier.wait(timeout=10)
        return client.post("/monitoring/drift", json={"reference_dataset_id": ref["id"],
                                                      "production_dataset_id": prod["id"]}).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        deleted = workers.submit(remove)
        monitored = workers.submit(monitor)
        delete_status, run_status = deleted.result(), monitored.result()
    assert delete_status in {204, 409}
    assert run_status in {201, 404, 409}
    with Session(engine) as db:
        if delete_status == 204:
            assert run_status in {404, 409}
            assert counts(db) == (1, 1, 1, 0, 0, 0)
        else:
            assert run_status == 201
            assert db.get(Dataset, ref["id"]) is not None
            assert db.scalar(select(func.count()).select_from(MonitoringRun)) == 1


def test_confirmation_markup_and_no_credentials_in_dashboard(client, credentials):
    response = client.get("/dashboard")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    page = response.text
    assert 'id="delete-dialog"' in page and 'id="delete-dataset-name"' in page
    assert 'id="delete-removals"' in page and 'id="delete-cancel"' in page
    assert 'id="delete-dataset-id"' in page
    assert "Are you sure you want to delete this dataset? This action cannot be undone." in page
    script = client.get("/assets/dashboard.js").text
    assert "ADMIN_PASSWORD" not in script and "localStorage" not in script
    assert "sessionStorage" not in script
    assert all(value not in page + script for value in credentials.values())


def test_migration_0006_preserves_existing_dataset_and_profile(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'upgrade.sqlite').as_posix()}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    storage = LocalStorage(tmp_path / "fixture-uploads")
    key = storage.save(b"synthetic\n1\n")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0005")
        with Session(engine) as db:
            model = MonitoredModel(name="Existing migration fixture")
            db.add(model)
            db.flush()
            dataset = Dataset(model_id=model.id, name="Existing fixture", dataset_type="reference",
                              file_path=key, file_name="synthetic.csv", row_count=1, column_count=1)
            db.add(dataset)
            db.flush()
            dataset_id = dataset.id
            db.add(DatasetProfile(dataset_id=dataset_id, report={"fixture": True}))
            db.commit()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(engine) as db:
            assert db.get(Dataset, dataset_id).name == "Existing fixture"
            assert db.get(DatasetProfile, dataset_id).report == {"fixture": True}
            assert counts(db) == (1, 1, 1, 0, 0, 0)
        assert storage.read(key) == b"synthetic\n1\n"
    finally:
        engine.dispose()
