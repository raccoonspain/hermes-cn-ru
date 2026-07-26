import pytest

from hermes_web import auth, storage
from hermes_web.seed_users import seed_user


def test_seed_user_creates_user_with_hashed_password(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    seed_user(conn, "dem", "secret123", "owner", "Дмитрий")

    row = storage.get_user(conn, "dem")
    assert row["role"] == "owner"
    assert row["display_name"] == "Дмитрий"
    assert row["password_hash"] != "secret123"
    assert auth.verify_password("secret123", row["password_hash"]) is True


def test_seed_user_duplicate_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    seed_user(conn, "dem", "secret123", "owner", "Дмитрий")
    with pytest.raises(Exception):
        seed_user(conn, "dem", "other", "owner", "Дмитрий 2")
