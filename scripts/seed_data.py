"""
데모 데이터 시드 스크립트.
실행: python scripts/seed_data.py

- 관리자/상담원/일반유저 계정 생성
- 샘플 티켓 30개 삽입
- 활성 프롬프트 템플릿 삽입
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.base import SessionLocal, engine, Base
import app.models  # noqa
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketStatus, TicketCategory
from app.models.prompt_template import PromptTemplate, PromptCategory
from app.core.security import hash_password
from app.services.ai_provider import DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_TEMPLATE

# 샘플 티켓 데이터
SAMPLE_TICKETS = [
    ("결제가 두 번 됐어요", "어제 카드로 결제했는데 오늘 또 결제 문자가 왔습니다. 환불 부탁드립니다."),
    ("로그인이 안 됩니다", "비밀번호를 맞게 입력했는데 계속 오류가 납니다. 계정이 잠긴 건가요?"),
    ("앱이 자꾸 튕겨요", "iOS 17.4 업데이트 이후로 앱 열면 3초 뒤에 꺼집니다."),
    ("구독 취소하고 싶어요", "다음 달 결제 전에 구독을 해지하고 싶습니다. 방법을 알려주세요."),
    ("환불 요청합니다", "상품을 받았는데 사진과 완전히 달라서 환불 원합니다."),
    ("비밀번호 찾기 메일이 안 와요", "비밀번호 재설정 메일을 요청했는데 30분째 안 옵니다."),
    ("결제 수단 변경이 안 됩니다", "새 카드를 등록하려고 하는데 계속 오류 코드 ERR-402가 뜹니다."),
    ("서비스 이용 방법 문의", "처음 사용하는데 어떻게 시작해야 하는지 모르겠어요."),
    ("계정 두 개를 합칠 수 있나요", "실수로 계정을 두 개 만들었는데 합치는 방법이 있나요?"),
    ("다운로드가 너무 느려요", "파일 다운로드 속도가 100KB/s 밖에 안 나옵니다."),
    ("세금계산서 발급 요청", "지난달 결제 내역에 대한 세금계산서가 필요합니다."),
    ("알림이 안 와요", "설정에서 알림을 켰는데 푸시 알림이 오지 않습니다."),
    ("데이터가 사라졌어요", "어제까지 있던 데이터가 오늘 보니 전부 없어졌습니다."),
    ("요금제 문의", "프리미엄과 베이직 차이가 뭔지 상세히 알고 싶습니다."),
    ("이메일 변경하고 싶어요", "가입할 때 쓴 이메일을 더 이상 사용 안 해서 변경하고 싶습니다."),
    ("API 키가 작동을 안 해요", "발급받은 API 키로 요청을 보내면 401 에러가 납니다."),
    ("팀 멤버 초대가 안 돼요", "팀에 멤버를 초대하면 상대방이 메일을 못 받는다고 합니다."),
    ("결제 영수증 재발송 요청", "3월 결제 영수증을 이메일로 다시 보내주실 수 있나요?"),
    ("앱 한국어 지원 요청", "영어만 지원하는데 한국어도 추가해주실 수 있나요?"),
    ("업로드 용량 제한 문의", "파일 업로드할 때 최대 용량이 얼마인가요?"),
    ("계정 탈퇴하고 싶습니다", "개인정보 삭제와 함께 계정을 완전히 탈퇴하고 싶습니다."),
    ("쿠폰이 적용이 안 돼요", "쿠폰 코드를 입력했는데 '유효하지 않은 코드'라고 나옵니다."),
    ("동시 접속 제한이 있나요", "여러 기기에서 동시에 로그인할 수 있나요?"),
    ("이상한 결제 내역이 있어요", "제가 결제하지 않은 내역이 청구됐습니다. 해킹당한 것 같아요."),
    ("서버가 다운됐나요", "지금 서비스 접속이 전혀 안 됩니다. 서버 문제인가요?"),
    ("리포트 내보내기 오류", "PDF로 내보내기 클릭하면 빈 파일이 다운로드됩니다."),
    ("2단계 인증 설정 방법", "보안을 높이고 싶어서 2FA 설정하는 방법을 알고 싶습니다."),
    ("프리미엄 기능이 안 열려요", "프리미엄으로 업그레이드했는데 기능이 여전히 잠겨있습니다."),
    ("데이터 백업은 어떻게 하나요", "내 데이터를 정기적으로 백업하는 방법이 있나요?"),
    ("협박성 메시지를 받았어요", "다른 사용자로부터 협박성 메시지를 받았습니다. 신고합니다."),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 계정 생성
        accounts = [
            ("admin@example.com", "admin1234", UserRole.admin),
            ("agent@example.com", "agent1234", UserRole.agent),
            ("user@example.com", "user12345", UserRole.user),
        ]
        users = {}
        for email, pw, role in accounts:
            existing = db.query(User).filter(User.email == email).first()
            if not existing:
                u = User(email=email, password_hash=hash_password(pw), role=role)
                db.add(u)
                db.flush()
                users[role] = u
                print(f"  생성: {email} [{role}]")
            else:
                users[role] = existing
                print(f"  이미 존재: {email}")

        # 프롬프트 템플릿 삽입
        existing_tmpl = db.query(PromptTemplate).filter(
            PromptTemplate.category == PromptCategory.analyze,
            PromptTemplate.is_active == True,
        ).first()
        if not existing_tmpl:
            tmpl = PromptTemplate(
                version="v1.0",
                category=PromptCategory.analyze,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                user_prompt_template=DEFAULT_USER_TEMPLATE,
                is_active=True,
                notes="초기 프롬프트 버전",
            )
            db.add(tmpl)
            print("  프롬프트 템플릿 v1.0 생성")

        # 티켓 삽입
        user = users.get(UserRole.user)
        if user:
            for i, (title, content) in enumerate(SAMPLE_TICKETS):
                t = Ticket(user_id=user.id, title=title, content=content)
                db.add(t)
            print(f"  샘플 티켓 {len(SAMPLE_TICKETS)}개 생성")

        db.commit()
        print("\n✅ 시드 완료!")
        print("\n계정 정보:")
        for email, pw, role in accounts:
            print(f"  {role.value:6s}  {email}  /  {pw}")

    except Exception as e:
        db.rollback()
        print(f"\n❌ 시드 실패: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("시드 데이터 삽입 중...")
    seed()
