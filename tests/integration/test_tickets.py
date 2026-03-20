"""티켓 CRUD 통합 테스트."""
import pytest


def test_create_ticket(client, user_headers):
    res = client.post("/api/v1/tickets", json={
        "title": "결제가 두 번 됐어요",
        "content": "어제 카드 결제 후 오늘 또 청구됐습니다. 확인 부탁드립니다.",
    }, headers=user_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "결제가 두 번 됐어요"
    assert data["status"] == "open"
    return data["id"]


def test_create_ticket_too_short(client, user_headers):
    res = client.post("/api/v1/tickets", json={
        "title": "짧",
        "content": "짧은 내용",
    }, headers=user_headers)
    assert res.status_code == 422


def test_list_tickets_user_sees_own_only(client, user_headers, db, test_user):
    from app.models.ticket import Ticket
    # 다른 유저 티켓 삽입
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    other = User(email="other2@example.com", password_hash=hash_password("pass1234"), role=UserRole.user)
    db.add(other)
    db.commit()
    db.refresh(other)
    other_ticket = Ticket(user_id=other.id, title="타인의 티켓입니다", content="이것은 보이면 안 됩니다.")
    db.add(other_ticket)
    db.commit()

    res = client.get("/api/v1/tickets", headers=user_headers)
    assert res.status_code == 200
    tickets = res.json()["tickets"]
    for t in tickets:
        assert t["user_id"] == test_user.id


def test_get_ticket_not_found(client, user_headers):
    res = client.get("/api/v1/tickets/nonexistent-id", headers=user_headers)
    assert res.status_code == 404


def test_delete_ticket_soft(client, user_headers):
    # 먼저 생성
    create_res = client.post("/api/v1/tickets", json={
        "title": "삭제할 티켓입니다",
        "content": "이 티켓은 곧 삭제될 예정입니다.",
    }, headers=user_headers)
    ticket_id = create_res.json()["id"]

    # soft delete
    del_res = client.delete(f"/api/v1/tickets/{ticket_id}", headers=user_headers)
    assert del_res.status_code == 204

    # 삭제 후 조회 → 404
    get_res = client.get(f"/api/v1/tickets/{ticket_id}", headers=user_headers)
    assert get_res.status_code == 404


def test_update_ticket_requires_agent(client, user_headers):
    create_res = client.post("/api/v1/tickets", json={
        "title": "상태 변경 테스트입니다",
        "content": "관리자만 상태를 바꿀 수 있어야 합니다.",
    }, headers=user_headers)
    ticket_id = create_res.json()["id"]

    res = client.patch(f"/api/v1/tickets/{ticket_id}",
                       json={"status": "resolved"},
                       headers=user_headers)
    assert res.status_code == 403
