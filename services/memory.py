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
# 우선순위: 1 = 사용자 명시 지시, 2 = 신상/핵심 사실, 3 = 취향/상태/일상
MEMORY_RULES = (
    (1, ("기억해", "기억할게", "기억해줄게", "기억해줘", "기억해둬", "기억할수", "이거 기억")),
    (2, (
        "내 이름", "제 이름", "내 직업", "제 직업", "내 나이", "제 나이", "내 생일", "제 생일",
        "내 취미", "제 취미", "내 성격", "내 꿈", "내 목표", "내 학교", "내 전공", "내 학과",
        "내가 사는", "내가 다니는", "내가 좋아하는", "내가 싫어하는", "내가 자주", "내가 가진",
        "내 친구", "내 가족", "내 동생", "내 형", "내 누나", "내 오빠", "내 남친", "내 여친",
        "우리 집", "혈액형", "mbti", "MBTI", "나는 ", "저는 ", "난 ", "전 ",
    )),
    (3, (
        "좋아해", "좋아함", "싫어해", "싫어함", "못 먹어", "안 먹어", "키우고", "키워", "키움",
        "다니고", "다녀", "살고", "살아", "취미는", "특기는", "생일은", "나이는", "이름은",
        "내 생각엔", "내가 생각하기엔", "나 사실", "나 요즘", "나 오늘",
    )),
)

# 순수 부정/반박 (사실 저장이 아닌 반박 대화)
DENIAL_PATTERNS = (
    "아니야", "아니거든", "아닌데", "아닙니다", "거짓말이야", "그런 적 없어", "착각이야", "틀렸어",
)


def _cleaned(text: str) -> str:
    return " ".join(text.split()).strip()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _is_denial(text: str) -> bool:
    return any(kw in text for kw in DENIAL_PATTERNS)


def _is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or t.endswith("까?") or t.endswith("니?") or t.endswith("냐?")


def remember_message(user_id: int, character_id: int, text: str) -> None:
    """사용자 사실/취향/신상을 장기 기억에 저장한다.
    - 질문이나 단순 반박은 저장 보류
    - 정규화 후 동일한 내용은 중복 저장 방지
    """
    cleaned = _cleaned(text)
    if not cleaned or len(cleaned) > 300:
        return
    if _is_question(cleaned):
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

    # 명시적 지시가 아닌 일반 대화 중 단순 반박문은 제외
    if matched_priority > 1 and _is_denial(cleaned):
        return

    # 정규화 후 동일한 내용이 있으면 중복 저장하지 않음
    cleaned_key = _normalized(cleaned)
    for row in db.get_memories(user_id, character_id, 200):
        if _normalized(row["memory"]) == cleaned_key:
            return

    db.add_memory(user_id, character_id, cleaned)
