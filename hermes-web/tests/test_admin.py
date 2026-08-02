import pytest

from hermes_web import admin_metrics, auth, quickchat, storage
from hermes_web.app import create_app


@pytest.fixture
def app_and_conn(tmp_path):
    db_path = str(tmp_path / "hermes-web.db")
    conn = storage.get_connection(db_path)
    storage.create_user(conn, "dem", auth.hash_password("secret123"), "owner", "Дмитрий")
    storage.create_user(conn, "rost", auth.hash_password("secret456"), "participant", "Ростислав")
    conn.close()

    config = quickchat.Config(
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    app = create_app(db_path=db_path, quickchat_config=config, cookie_secure=False, static_dir=str(static_dir))
    return app


async def _login(client, username, password):
    resp = await client.post("/login", json={"username": username, "password": password})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_overview_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.get("/api/admin/overview")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_overview_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_overview_returns_metrics_for_owner(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 200
    body = await resp.json()
    assert isinstance(body["cpu_percent"], (int, float))
    assert set(body["ram"]) == {"used_bytes", "total_bytes"}
    assert set(body["disk"]) == {"used_bytes", "total_bytes", "path"}
    assert body["active_sessions"] >= 1
    assert body["active_users"] >= 1


@pytest.mark.asyncio
async def test_overview_degrades_gracefully_when_cpu_metric_raises(aiohttp_client, app_and_conn, monkeypatch):
    async def boom(*args, **kwargs):
        raise OSError("не удалось прочитать /proc/stat")

    monkeypatch.setattr(admin_metrics, "cpu_percent", boom)

    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 200
    body = await resp.json()
    assert body["cpu_percent"] is None
    assert "cpu" in body.get("errors", {})
    # Остальные метрики, не затронутые сбоем, всё равно приходят нормально.
    assert set(body["ram"]) == {"used_bytes", "total_bytes"}
    assert set(body["disk"]) == {"used_bytes", "total_bytes", "path"}
    assert body["active_sessions"] >= 1


@pytest.mark.asyncio
async def test_overview_degrades_gracefully_when_all_metrics_raise(aiohttp_client, app_and_conn, monkeypatch):
    async def boom_cpu(*args, **kwargs):
        raise OSError("boom cpu")

    def boom_ram(*args, **kwargs):
        raise OSError("boom ram")

    def boom_disk(*args, **kwargs):
        raise OSError("boom disk")

    monkeypatch.setattr(admin_metrics, "cpu_percent", boom_cpu)
    monkeypatch.setattr(admin_metrics, "ram_usage", boom_ram)
    monkeypatch.setattr(admin_metrics, "disk_usage", boom_disk)

    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 200
    body = await resp.json()
    assert body["cpu_percent"] is None
    assert body["ram"] is None
    assert body["disk"] is None
    assert set(body["errors"]) == {"cpu", "ram", "disk"}
    # Активные сессии не зависят от metrics-модуля — должны прийти как обычно.
    assert body["active_sessions"] >= 1


@pytest.mark.asyncio
async def test_list_users_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/users")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_list_users_returns_all_with_counts(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/users")
    assert resp.status == 200
    body = await resp.json()
    usernames = {u["username"] for u in body["users"]}
    assert usernames == {"dem", "rost"}
    dem = next(u for u in body["users"] if u["username"] == "dem")
    assert dem["display_name"] == "Дмитрий"
    assert dem["role"] == "owner"
    assert dem["project_count"] == 0
    assert dem["last_active"] is None


@pytest.mark.asyncio
async def test_create_user_success(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "gleb", "display_name": "Глеб", "role": "participant", "password": "newpass1",
    })
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "gleb")
    assert row["display_name"] == "Глеб"
    assert row["role"] == "participant"
    assert auth.verify_password("newpass1", row["password_hash"])


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_username(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "Bad Name!", "display_name": "X", "role": "participant", "password": "pass1234",
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_username(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "dem", "display_name": "X", "role": "participant", "password": "pass1234",
    })
    assert resp.status == 409


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "gleb", "display_name": "Глеб", "role": "admin", "password": "pass1234",
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_update_user_changes_name_and_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/rost", json={"display_name": "Ростислав Н.", "role": "owner"})
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "rost")
    assert row["display_name"] == "Ростислав Н."
    assert row["role"] == "owner"


@pytest.mark.asyncio
async def test_update_user_unknown_returns_404(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/nobody", json={"display_name": "X", "role": "participant"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_update_user_cannot_demote_self(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/dem", json={"display_name": "Дмитрий", "role": "participant"})
    assert resp.status == 400
    row = storage.get_user(app_and_conn["db"], "dem")
    assert row["role"] == "owner"


@pytest.mark.asyncio
async def test_reset_password_updates_hash(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/rost/reset-password", json={"password": "brandnew1"})
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "rost")
    assert auth.verify_password("brandnew1", row["password_hash"])
    assert not auth.verify_password("secret456", row["password_hash"])


@pytest.mark.asyncio
async def test_reset_password_unknown_user_404(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/nobody/reset-password", json={"password": "brandnew1"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_events_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/events")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_events_returns_newest_first(aiohttp_client, app_and_conn):
    storage.log_event(app_and_conn["db"], "dem", "login", "")
    storage.log_event(app_and_conn["db"], "dem", "project.create", "ALL/x")

    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/events")
    assert resp.status == 200
    body = await resp.json()
    verbs = [e["verb"] for e in body["events"]]
    assert verbs[0] == "login"  # логин ИЗ ЭТОГО ЖЕ теста (_login) залогировался последним
    assert "project.create" in verbs
