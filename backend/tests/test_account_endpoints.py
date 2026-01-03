import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.src.app.main import app
from backend.src.db.models import ApiKey, UsageEvent
from backend.src.services import auth as auth_module
from backend.src.services.auth import hash_api_key


def _client():
    return TestClient(app)


def _auth_header(plaintext: str) -> dict[str, str]:
    return {"X-API-Key": plaintext}


@pytest.mark.asyncio
async def test_account_list_create_deactivate_rotate(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    root_plain = "lc_root_account_1234567890"
    child_plain = "lc_child_account_1234567890"
    other_plain = "lc_other_account_1234567890"

    root = ApiKey(key_hash=hash_api_key(root_plain), name="root", is_active=True)
    child = ApiKey(key_hash=hash_api_key(child_plain), name="child", is_active=True, account_id=root.id)
    other = ApiKey(key_hash=hash_api_key(other_plain), name="other", is_active=True)
    session.add(root)
    session.add(child)
    session.add(other)
    await session.commit()

    with _client() as c:
        r = c.get("/api/account/api-keys", headers=_auth_header(root_plain))
        assert r.status_code == 200
        keys = r.json()
        assert {k["id"] for k in keys} == {str(root.id), str(child.id)}
        assert all("key_hash" not in k for k in keys)

        r2 = c.post(
            "/api/account/api-keys",
            headers=_auth_header(root_plain),
            json={"name": "new", "rate_limit_per_min": 11, "monthly_token_cap": 123},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["plaintext_key"].startswith("lc_")
        new_id = uuid.UUID(body["api_key_id"])

    created = await session.get(ApiKey, new_id)
    assert created is not None
    assert created.account_id == root.id
    assert created.key_hash == hash_api_key(body["plaintext_key"])
    assert created.key_hash != body["plaintext_key"]

    with _client() as c:
        r3 = c.get("/api/account/api-keys", headers=_auth_header(root_plain))
        assert r3.status_code == 200
        keys = r3.json()
        assert {k["id"] for k in keys} == {str(root.id), str(child.id), str(new_id)}

        r4 = c.post(f"/api/account/api-keys/{child.id}/deactivate", headers=_auth_header(root_plain))
        assert r4.status_code == 200
        assert r4.json()["is_active"] is False

    child_after = await session.get(ApiKey, child.id)
    assert child_after is not None
    await session.refresh(child_after)
    assert child_after.is_active is False
    assert child_after.deactivated_at is not None

    with _client() as c:
        r5 = c.get("/api/account/api-keys", headers=_auth_header(child_plain))
        assert r5.status_code == 401

        r6 = c.post(f"/api/account/api-keys/{root.id}/rotate", headers=_auth_header(root_plain))
        assert r6.status_code == 200
        rotated = r6.json()
        assert rotated["old_key_id"] == str(root.id)
        assert rotated["plaintext_key"].startswith("lc_")
        new_key_id = uuid.UUID(rotated["new_key_id"])

        r7 = c.get("/api/account/api-keys", headers=_auth_header(root_plain))
        assert r7.status_code == 401

        r8 = c.get("/api/account/api-keys", headers=_auth_header(rotated["plaintext_key"]))
        assert r8.status_code == 200
        ids = {k["id"] for k in r8.json()}
        assert str(new_key_id) in ids
        assert str(root.id) in ids


@pytest.mark.asyncio
async def test_account_usage_aggregates(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    plain = "lc_usage_1234567890"
    key = ApiKey(key_hash=hash_api_key(plain), name="u", is_active=True)
    session.add(key)
    await session.commit()

    in_range = datetime.utcnow() - timedelta(days=2)
    out_range = datetime.utcnow() - timedelta(days=40)

    session.add(
        UsageEvent(
            owner_key_id=key.id,
            run_id=uuid.uuid4(),
            model="m1",
            prompt_tokens=2,
            completion_tokens=3,
            total_tokens=5,
            cost_estimated=0.01,
            created_at=in_range,
        )
    )
    session.add(
        UsageEvent(
            owner_key_id=key.id,
            run_id=uuid.uuid4(),
            model="m1",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost_estimated=0.02,
            created_at=in_range,
        )
    )
    session.add(
        UsageEvent(
            owner_key_id=key.id,
            run_id=uuid.uuid4(),
            model="m2",
            prompt_tokens=10,
            completion_tokens=0,
            total_tokens=10,
            cost_estimated=0.0,
            created_at=in_range,
        )
    )
    session.add(
        UsageEvent(
            owner_key_id=key.id,
            run_id=uuid.uuid4(),
            model="m2",
            total_tokens=999,
            created_at=out_range,
        )
    )
    await session.commit()

    from_d = (date.today() - timedelta(days=10)).isoformat()
    to_d = date.today().isoformat()

    with _client() as c:
        r = c.get(f"/api/account/usage?from={from_d}&to={to_d}", headers=_auth_header(plain))
        assert r.status_code == 200
        body = r.json()
        assert body["total_prompt_tokens"] == 13
        assert body["total_completion_tokens"] == 4
        assert body["total_tokens"] == 17
        assert round(body["total_cost_estimated"], 8) == 0.03

        by_model = {row["model"]: row for row in body["by_model"]}
        assert by_model["m1"]["attempts"] == 2
        assert by_model["m1"]["total_tokens"] == 7
        assert by_model["m2"]["attempts"] == 1
        assert by_model["m2"]["total_tokens"] == 10


@pytest.mark.asyncio
async def test_account_limits(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "test-pepper")

    plain = "lc_limits_1234567890"
    key = ApiKey(key_hash=hash_api_key(plain), name="l", is_active=True, monthly_token_cap=10)
    session.add(key)
    await session.commit()

    session.add(
        UsageEvent(
            owner_key_id=key.id,
            run_id=uuid.uuid4(),
            model="m",
            total_tokens=6,
            created_at=datetime.utcnow(),
        )
    )
    await session.commit()

    with _client() as c:
        r = c.get("/api/account/limits", headers=_auth_header(plain))
        assert r.status_code == 200
        body = r.json()
        assert body["monthly_token_cap"] == 10
        assert body["tokens_used_this_month"] == 6
        assert body["tokens_remaining"] == 4
        assert body["quota_exceeded"] is False


@pytest.mark.asyncio
async def test_account_api_keys_returns_json_with_cors_on_server_misconfig(session, monkeypatch):
    monkeypatch.setattr(auth_module, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(auth_module, "API_KEY_PEPPER", "")

    with _client() as c:
        r = c.get(
            "/api/account/api-keys",
            headers={
                **_auth_header("lc_any_key"),
                "Origin": "http://localhost:5173",
                "X-Request-ID": "req_test_123",
            },
        )
        assert r.status_code == 500
        body = r.json()
        assert body["detail"] == "api_key_pepper_missing"
        assert body["request_id"] == "req_test_123"
        assert body["error_code"] == "api_key_pepper_missing"
        assert r.headers.get("X-Request-ID") == "req_test_123"
        assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
