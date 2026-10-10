from config import MAX_MEMORY_ITEMS
from database.database import db
import re


def get_memories(user_id: int, character_id: int) -> list[str]:
    return [row["memory"] for row in db.get_memories(user_id, character_id, MAX_MEMORY_ITEMS)]


def save_memory(user_id: int, character_id, text) -> None:
    cleaned = " ".join(text.split()).strip()[:500]
    if cleaned:
        db.add_memory(user_id, character_id, cleaned)


# 기억 규칙: (우선순위, 키워드 목록)
# 우선순위: 1 = 사용자 명시("기억해:"), 2 = 자기소개/사실, 3 = 간접/감정
MEMORY_RULES = (
    (1, ("기억해", "기억할게", "기억해줄게", "기억해줘", "기억할수")),
    (2, (
        "내 이름", "내 직업", "내 나이", "내 생일", "내 취미", "내 취향이", "내 스타일이",
        "내 성격이", "내 꿈이", "내 계획이", "내 취미가", "내가 좋아하는", "내가 싫어하는",
        "내가 자주", "내가 가진", "내가 사는", "내 가족이", "내 친구가", "내 성격은",
        "내 취향을", "내 스타일을", "내 직업이", "내 나이가", "내 생일이", "나의", "제 이름",
        "저는 ", "제가 좋아", "제 취향", "제 생일", "제 직업", "제 나이", "우리 집", "내 친구",
        "내 가족", "혈액형", "mbti", "MBTI", "취미"
    )),
    (3, (
        "내 생각엔", "내가 생각하기에는", "내 의견엔", "내가 아는", "나 오늘", "내가 제일", "나 사실",
        "나 슬퍼", "나 기뻐", "나 힘들어", "나는", "내 생각", "내 취향", "내 스타일", "내 의견",
        "내 장점", "내 단점", "내가 말하길", "내 경험상", "내 사는", "내 꿈은", "내 성격이",
    )),
)

# 부정 표현: 이 말이 섞이면 사실로 저장하지 않는다.
MEMORY_NEGATIONS = (
    "아닌", "아니", "않는", "않", "안 ", "안", "못 ", "못", "싫어하지", "좋아하지", "없이", "전혀", "별로",
)


def _cleaned(text: str) -> str:
    return " ".join(text.split()).strip()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _is_negated(text: str) -> bool:
    return any(kw in text for kw in MEMORY_NEGATIONS)


def _is_question(text: str) -> bool:
    return text.strip().endswith("?")


def remember_message(user_id: int, character_id: int, text: str) -> None:
    """사용자 사실/취향/감정을 장기 기억에 저장한다.

    - "기억해:" 등 명시적 저장을 우선 처리
    - 부정문/질문은 저장 보류
    - 정규화 후 동일한 내용은 중복 저장하지 않음
    """
    cleaned = _cleaned(text)
    if not cleaned or len(cleaned) > 300:
        return
    if _is_negated(cleaned) or _is_question(cleaned):
        return

    matched_priority = 0
    for priority, keywords in MEMORY_RULES:
        for kw in keywords:
            if kw in cleaned:
                matched_priority = priority
                break
        if matched_priority >= 1:
            break

    if matched_priority == 0:
        return

    # 정규화 후 동일한 내용이 있으면 저장하지 않음
    cleaned_key = _normalized(cleaned)
    for row in db.get_memories(user_id, character_id, 200):
        if _normalized(row["memory"]) == cleaned_key:
            return

    db.add_memory(user_id, character_id, cleaned)
