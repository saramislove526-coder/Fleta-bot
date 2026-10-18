import re


def truncate(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


ZWSP = "\u200b"


def sanitize_mentions(text: str) -> str:
    """모든 @멘션, @everyone, @here, 유저 멘션, 역할 멘션을 무력화하여 핑 알림 테러를 원천 차단합니다."""
    if not text:
        return text
    # 모든 @ 뒤에 제로 너비 공백(\u200b)을 넣어 디스코드의 멘션/핑 파싱을 원천 무력화합니다.
    # 예: @everyone -> @​everyone, @here -> @​here, @j.xyw -> @​j.xyw, <@123> -> <@​123>
    text = re.sub(r"@(?=\S)", f"@{ZWSP}", text)
    return text


def filter_spam_response(text: str) -> str:
    """도배성 숫자 나열(1~100 등), 단어 무한 반복, 과도한 벽돌 텍스트를 감지하여 차단합니다."""
    if not text:
        return text

    # 1. 숫자 세기 도배 차단 (예: 1 2 3 4 5 6 7 8 9 10 11 12 ... 100)
    numbers = re.findall(r"\b\d+\b", text)
    if len(numbers) >= 15:
        try:
            int_nums = [int(n) for n in numbers[:50]]
            consecutive = 0
            for i in range(len(int_nums) - 1):
                if int_nums[i + 1] == int_nums[i] + 1:
                    consecutive += 1
                else:
                    consecutive = 0
                if consecutive >= 6:
                    return "숫자를 줄줄이 세거나 도배하는 장난은 치지 않아요! 다른 재미있는 이야기를 나눠요. 😊"
        except Exception:
            pass

    # 2. 동일 단어/문구 4회 이상 연속 반복 차단 (예: '치피 치피 치피 치피...' 등)
    text = re.sub(r"(\b\S+\b[\s,]*)\1{3,}", r"\1\1\1 (이하 반복 생략)", text)

    # 3. 과도하게 많은 줄바꿈(줄 수 18줄 초과) 차단
    lines = text.splitlines()
    if len(lines) > 18:
        text = "\n".join(lines[:12]) + "\n... (도배 방지를 위해 이하 내용이 생략되었습니다)"

    return text


# 캐릭터 생성/수정 시 악의적인 프롬프트 인젝션 및 보안 해제 시도 탐지 패턴
_JAILBREAK_PATTERNS = [
    r"(?:보안|시스템|안전|규칙|지침|가이드라인|원칙|프롬프트)\s*(?:을|를|은|는)?\s*(?:무시|해제|삭제|취소|무력화|우회|위반|어겨|재정의|잊어)",
    r"(?:모든|이전|기존)\s*(?:명령|규칙|지침|설정|지시)\s*(?:무시|취소|삭제|잊어)",
    r"도배\w*",
    r"숫자\s*(?:1부터|세어|나열|카운트|세기)",
    r"\d+\s*부터\s*\d+\s*까지",
    r"멘션\s*(?:테러|도배|해줘|달아|반복|스팸)",
    r"@\S+",
    r"모든\s*명령에\s*(?:복종|따라|무조건|응해)",
    r"(?:무조건|절대)\s*복종",
    r"시키는\s*대로\s*(?:다\s*해|무조건|다\s*따라)",
    r"(?:제약|제한|검열|필터링?)\s*(?:없이|해제|풀고|우회)",
    r"ignore\s+(?:all\s+)?(?:rules|instructions|directives|prompts|safety|guidelines)",
    r"bypass\s+(?:safety|rules|filters|censorship)",
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode",
    r"unrestricted\s+mode",
    r"system\s*prompt",
    r"\[(?:system|security|instruction|developer|admin|rule|override)\]",
]


def check_character_safety(text: str) -> str | None:
    """캐릭터 설정값(이름, 소개, 성격, 말투, 세계관)에 탈옥이나 도배 유도 문구가 있는지 검사합니다.
    위반 시 사유를 반환하고, 안전하면 None을 반환합니다."""
    if not text:
        return None
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "시스템 보안을 무력화하거나 도배를 유도하는 금지 표현이 포함되어 있습니다."
    return None


def sanitize_character_field(text: str, default: str = "") -> str:
    """캐릭터 설정값을 프롬프트에 넣기 전 인젝션 태그와 멘션을 무력화하고 정제합니다."""
    if not text or not text.strip():
        return default
    cleaned = text.strip()
    # 1. 멘션 기호 무력화
    cleaned = sanitize_mentions(cleaned)
    # 2. 시스템 프롬프트 헤더 형태 ([System], [Instruction] 등) 무력화
    cleaned = re.sub(r"\[(system|instruction|security|developer|admin|rule)[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    # 3. 마크다운 구분선/코드블록 탈옥 기호 제거
    cleaned = cleaned.replace("```", "'''").replace('"""', "'''")
    # 4. 금지된 탈옥 지시어 치환
    for pattern in _JAILBREAK_PATTERNS:
        cleaned = re.sub(pattern, "[금지된 설정]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or default
