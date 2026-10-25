import re
import random


def truncate(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


ZWSP = "\u200b"


def sanitize_mentions(text: str) -> str:
    """모든 @멘션, @everyone, @here, 유저 멘션, 역할 멘션을 무력화하여 핑 알림 테러를 원천 차단합니다."""
    if not text:
        return text
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

    # 2. 동일 단어/문구 4회 이상 연속 반복 차단
    text = re.sub(r"(\b\S+\b[\s,]*)\1{3,}", r"\1\1\1 (이하 반복 생략)", text)

    # 3. 과도하게 많은 줄바꿈(줄 수 18줄 초과) 차단
    lines = text.splitlines()
    if len(lines) > 18:
        text = "\n".join(lines[:12]) + "\n... (도배 방지를 위해 이하 내용이 생략되었습니다)"

    return text


# ── 캐릭터 생성/수정 시 프롬프트 인젝션 탐지 패턴 ──
_JAILBREAK_PATTERNS = [
    r"(?:보안|시스템|안전|규칙|지침|가이드라인|원칙|프롬프트)\s*(?:을|를|은|는)?\s*(?:무시|해제|삭제|취소|무력화|우회|위반|어겨|재정의|잊어)",
    r"(?:모든|이전|기존)\s*(?:명령|규칙|지침|설정|지시)\s*(?:무시|취소|삭제|잊어)",
    r"숫자\s*(?:1부터|세어|나열|카운트|세기)",
    r"\d+\s*부터\s*\d+\s*까지",
    r"멘션\s*(?:테러|도배|해줘|달아|반복|스팸)",
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
    """캐릭터 설정값에 탈옥이나 도배 유도 문구가 있는지 검사합니다."""
    if not text:
        return None
    # 캐릭터 설정에서는 "도배"가 포함된 설정 자체를 차단 (도배 허용 캐릭터 생성 방지)
    if re.search(r"도배\s*(?:해줘|해라|시작|해|허용|수행|달려|가자|명령|고고|부탁|권장|가능|OK|ok|괜찮|시켜)", text, re.IGNORECASE):
        return "도배를 유도하는 금지 표현이 포함되어 있습니다."
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "시스템 보안을 무력화하거나 도배를 유도하는 금지 표현이 포함되어 있습니다."
    return None


# ── 실시간 유저 채팅 프롬프트 차단 패턴 (정밀 매칭 — 오탐 최소화) ──
_PROMPT_BLOCK_PATTERNS = [
    # 1. 보안 지침 무력화 및 탈옥 (명확한 지시 형태만)
    r"(?:보안|시스템|안전|규칙|지침|가이드라인|원칙|프롬프트)\s*(?:을|를|은|는)?\s*(?:무시|해제|삭제|취소|무력화|우회|위반|어겨|재정의|잊어)",
    r"(?:모든|이전|기존)\s*(?:명령|규칙|지침|설정|지시)\s*(?:무시|취소|삭제|잊어)",
    r"ignore\s+(?:all\s+)?(?:rules|instructions|directives|prompts|safety|guidelines)",
    r"bypass\s+(?:safety|rules|filters|censorship)",
    r"(?:^|\s)(?:jailbreak|dan\s+mode|developer\s+mode|unrestricted\s+mode)(?:\s|$)",
    r"system\s*prompt",
    r"\[(?:system|security|instruction|developer|admin|rule|override)\]",
    # 2. 도배 유도 (명령형만 차단, 단순 언급은 허용)
    r"도배\s*(?:해줘|해라|시작|해봐|수행|달려|가자|명령|고고|부탁|쳐줘|시켜|하자)",
    r"숫자\s*(?:1부터|세어|나열|카운트|세기)\s*(?:해|줘|봐|하자)",
    r"\d+\s*부터\s*\d+\s*까지\s*(?:세|나열|출력|말해|써)",
    r"같은\s*말\s*(?:\d+번|계속|반복)\s*(?:반복|해|말해|써)",
    r"(?:\d+번|계속|무한)\s*반복\s*(?:해|말해|써|출력)",
    # 3. 멘션 테러 및 태그 강제
    r"@everyone|@here",
    r"@\S+.*?(?:붙여|태그|멘션|도배|소환|반복)",
    r"멘션\s*(?:테러|도배|해줘|달아|반복|스팸|붙여)",
    # 4. 무조건 복종 및 무제한 강제
    r"모든\s*명령에\s*(?:복종|따라|무조건|응해)",
    r"(?:무조건|절대)\s*복종",
    r"시키는\s*대로\s*(?:다\s*해|무조건|다\s*따라)",
    r"(?:제약|제한|검열|필터링?)\s*(?:없이|해제|풀고|우회)",
    # 5. 서버 테러 관련 원천 차단 (NEW)
    r"(?:ddos|디도스|DDoS)\s*(?:코드|스크립트|만들어|제작|방법|공격|툴|프로그램)",
    r"(?:crack|크랙)\s*(?:방법|만들어|제작|코드|다운|프로그램|툴)",
    r"(?:해킹|핵|익스플로잇|exploit)\s*(?:방법|코드|만들어|제작|툴|스크립트|프로그램)",
    r"(?:토큰|token)\s*(?:그랩|grab|탈취|훔|스틸|steal|파괴|nuker)",
    r"(?:봇|bot)\s*(?:테러|폭파|파괴|nuker|raid|레이드)",
    r"(?:서버|server)\s*(?:테러|폭파|파괴|nuker|raid|레이드)",
    r"(?:ip|아이피)\s*(?:추적|그랩|grab|따|털|로깅|logger)",
    r"(?:피싱|phishing|스캠|scam)\s*(?:사이트|링크|만들|제작|방법|코드)",
    r"(?:랜섬|ransom)\s*(?:웨어|ware|코드|만들|제작|방법)",
    r"(?:허위\s*사실|가짜\s*뉴스|fake\s*news)\s*(?:유포|퍼뜨|만들|작성|제작|생성)",
]


def check_prompt_safety(text: str) -> str | None:
    """유저의 실시간 채팅 입력값에 탈옥, 도배 유도, 테러, 해킹 시도가 있는지 검사합니다.
    위반 시 거부 사유 문자열을 반환하고, 안전하면 None을 반환합니다."""
    if not text:
        return None
    # 3개 이상의 멘션이 포함된 경우 멘션 스팸으로 간주 차단
    if len(re.findall(r"@\S+", text)) >= 3:
        return "과도한 멘션 포함"
    for pattern in _PROMPT_BLOCK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "도배 또는 보안 정책 우회 시도"
    return None


def get_safe_refusal(character_name: str = "플레타") -> str:
    """도배/탈옥 프롬프트 차단 시 반환할 안전하고 친근한 거절 대사"""
    responses = [
        f"그건 {character_name}가 도와줄 수 없는 영역이야! 다른 재밌는 이야기 하자~ 😊",
        f"그런 건 아무리 부탁해도 안 돼! 대신 재미있는 거 찾아볼까? ✨",
        f"그 요청은 들어줄 수 없어! 다른 이야기를 해보자~ 🌿",
        f"위험하거나 문제가 될 수 있는 건 {character_name}도 거절해야 해! 다른 주제로 놀자~ 🎵",
    ]
    return random.choice(responses)


def sanitize_character_field(text: str, default: str = "") -> str:
    """캐릭터 설정값을 프롬프트에 넣기 전 인젝션 태그와 멘션을 무력화하고 정제합니다."""
    if not text or not text.strip():
        return default
    cleaned = text.strip()
    cleaned = sanitize_mentions(cleaned)
    cleaned = re.sub(r"\[(system|instruction|security|developer|admin|rule)[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "'''").replace('"""', "'''")
    for pattern in _JAILBREAK_PATTERNS:
        cleaned = re.sub(pattern, "[금지된 설정]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or default
