"""인증 플로우 통합 테스트."""
import pytest


def test_register_success(client):
    res = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "newpass123",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "new@example.com"
    assert data["role"] == "user"
    assert "id" in data


def test_register_duplicate_email(client, test_user):
    res = client.post("/api/v1/auth/register", json={
        "email": test_user.email,
        "password": "anypass123",
    })
    assert res.status_code == 409


def test_login_success(client, test_user):
    res = client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "testpass123",
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client, test_user):
    res = client.post("/api/v1/auth/login", json={
        "email": test_user.email,
        "password": "wrongpassword",
    })
    assert res.status_code == 401


def test_me_authenticated(client, user_headers):
    res = client.get("/api/v1/auth/me", headers=user_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "testuser@example.com"


def test_me_unauthenticated(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 403  # HTTPBearer returns 403 when missing
