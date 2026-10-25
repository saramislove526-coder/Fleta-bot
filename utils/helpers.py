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
    """AI 응답에서 도배성 패턴을 감지하고 차단합니다."""
    if not text:
        return text

    # 1. 숫자 연속 나열 차단 (1 2 3 4 ... 100)
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
                    return "그런 건 내 스타일이 아니야! 다른 재미있는 이야기를 하자. 😊"
        except Exception:
            pass

    # 2. 동일 단어/문구 4회 이상 연속 반복 축약
    text = re.sub(r"(\b\S+\b[\s,]*)\1{3,}", r"\1\1\1 (이하 반복 생략)", text)

    # 3. 동일 문장 3회 이상 반복 축약 (줄 단위)
    lines = text.splitlines()
    if len(lines) >= 3:
        deduplicated = []
        repeat_count = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if i > 0 and stripped and stripped == lines[i - 1].strip():
                repeat_count += 1
                if repeat_count >= 3:
                    continue
            else:
                repeat_count = 0
            deduplicated.append(line)
        if len(deduplicated) < len(lines):
            deduplicated.append("(반복 생략)")
            lines = deduplicated

    # 4. 과도한 줄 수(20줄 초과) 제한
    if len(lines) > 20:
        text = "\n".join(lines[:14]) + "\n... (이하 생략)"
    else:
        text = "\n".join(lines)

    # 5. 단일 응답이 비정상적으로 긴 경우(1800자 초과) 잘라내기
    if len(text) > 1800:
        text = text[:1800] + "…"

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
    if re.search(r"도배\s*(?:해줘|해라|시작|해|허용|수행|달려|가자|명령|고고|부탁|권장|가능|OK|ok|괜찮|시켜)", text, re.IGNORECASE):
        return "도배를 유도하는 금지 표현이 포함되어 있습니다."
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "시스템 보안을 무력화하거나 도배를 유도하는 금지 표현이 포함되어 있습니다."
    return None


# ── 실시간 유저 채팅 프롬프트 차단 패턴 ──
# 원칙: 실제 악의적 명령만 차단, 일반 대화는 절대 차단하지 않음
_PROMPT_BLOCK_PATTERNS = [
    # ━━ 1. 보안 지침 무력화 및 탈옥 ━━
    r"(?:보안|시스템|안전|규칙|지침|가이드라인|원칙|프롬프트)\s*(?:을|를|은|는)?\s*(?:무시|해제|삭제|취소|무력화|우회|위반|어겨|재정의|잊어)",
    r"(?:모든|이전|기존)\s*(?:명령|규칙|지침|설정|지시)\s*(?:무시|취소|삭제|잊어)",
    r"ignore\s+(?:all\s+)?(?:rules|instructions|directives|prompts|safety|guidelines)",
    r"bypass\s+(?:safety|rules|filters|censorship)",
    r"(?:^|\s)(?:jailbreak|dan\s+mode|developer\s+mode|unrestricted\s+mode)(?:\s|$)",
    r"system\s*prompt",
    r"\[(?:system|security|instruction|developer|admin|rule|override)\]",

    # ━━ 2. 도배 유도 (명령형만 차단) ━━
    r"도배\s*(?:해줘|해라|시작|해봐|수행|달려|가자|명령|고고|부탁|쳐줘|시켜|하자|ㄱ|ㄱㄱ|고|해)",

    # ━━ 3. 반복/도배 우회 표현 차단 (핵심 추가) ━━
    # "100번 말해봐", "50번 써줘", "1000번 반복해" 등
    r"\d+\s*번\s*(?:말해|해봐|해줘|써줘|써봐|적어|보내|출력|반복|외쳐|보여|읽어|해|써|쳐|적어줘|보내줘|쳐봐)",
    # "계속 말해", "끝없이 써", "멈추지 마" 등
    r"(?:계속|끝없이|멈추지\s*말고|그만두지\s*말고|무한으로|무한히|영원히)\s*(?:말해|써|반복|출력|보내|해|적어|쳐)",
    # "같은 말 반복", "똑같이 N번" 등
    r"(?:같은|똑같은|동일한)\s*(?:말|문장|단어|글자|내용|거)\s*(?:\d+번|계속|반복|여러\s*번|많이)\s*(?:해|말해|써|반복|출력|보내)?",
    # "화면 가득 채워", "채널 도배해" 등
    r"(?:화면|채팅|채널|서버)\s*(?:가득|꽉|빽빽|도배)\s*(?:채워|메워|해|줘)?",
    # "최대한 길게/많이 써" 등 비정상적 분량 요구
    r"(?:최대한|엄청|진짜|개)\s*(?:길게|많이|오래)\s*(?:써|말해|적어|보내|출력|해)",
    # 숫자 세기 (1부터 100까지 세어줘)
    r"\d+\s*부터\s*\d+\s*까지\s*(?:세|나열|출력|말해|써|읽어|적어)",
    r"숫자\s*(?:1부터|세어|나열|카운트|세기)\s*(?:해|줘|봐|하자)",
    # 명시적 반복 지시
    r"(?:\d+번|계속|무한)\s*반복\s*(?:해|말해|써|출력|줘|봐)",

    # ━━ 4. 멘션 테러 및 태그 강제 ━━
    r"@everyone|@here",
    r"@\S+.*?(?:붙여|태그|멘션|도배|소환|반복)",
    r"멘션\s*(?:테러|도배|해줘|달아|반복|스팸|붙여)",

    # ━━ 5. 무조건 복종 및 무제한 강제 ━━
    r"모든\s*명령에\s*(?:복종|따라|무조건|응해)",
    r"(?:무조건|절대)\s*복종",
    r"시키는\s*대로\s*(?:다\s*해|무조건|다\s*따라)",
    r"(?:제약|제한|검열|필터링?)\s*(?:없이|해제|풀고|우회)",

    # ━━ 6. 서버 테러 / 해킹 / 악성 코드 ━━
    r"(?:ddos|디도스|DDoS)\s*(?:코드|스크립트|만들|제작|방법|공격|툴|프로그램|짜|작성)",
    r"(?:crack|크랙)\s*(?:방법|만들|제작|코드|다운|프로그램|툴|짜|작성)",
    r"(?:해킹|핵|익스플로잇|exploit)\s*(?:방법|코드|만들|제작|툴|스크립트|프로그램|짜|작성)",
    r"(?:토큰|token)\s*(?:그랩|grab|탈취|훔|스틸|steal|파괴|nuker|가져|빼)",
    r"(?:봇|bot)\s*(?:테러|폭파|파괴|nuker|raid|레이드|공격)",
    r"(?:서버|server)\s*(?:테러|폭파|파괴|nuker|raid|레이드|공격)",
    r"(?:ip|아이피|IP)\s*(?:추적|그랩|grab|따|털|로깅|logger|가져|빼)",
    r"(?:피싱|phishing|스캠|scam)\s*(?:사이트|링크|만들|제작|방법|코드|페이지|짜|작성)",
    r"(?:랜섬|ransom)\s*(?:웨어|ware|코드|만들|제작|방법|짜|작성)",
    r"(?:허위\s*사실|가짜\s*뉴스|fake\s*news)\s*(?:유포|퍼뜨|만들|작성|제작|생성|써|보내)",
    r"(?:키로거|keylogger|스파이웨어|spyware|트로이|trojan|백도어|backdoor)\s*(?:만들|제작|코드|설치|방법|짜|작성)",
    r"(?:자해|자살)\s*(?:방법|도구|수단|코드)",
    r"(?:폭발물|폭탄|총기|무기)\s*(?:만들|제작|방법|제조|설계)",
]


def check_prompt_safety(text: str) -> str | None:
    """유저의 실시간 채팅 입력에 탈옥/도배/테러/해킹 시도가 있는지 검사합니다.
    위반 시 거부 사유 문자열, 안전하면 None을 반환합니다."""
    if not text:
        return None
    # 3개 이상의 멘션이 포함된 경우 멘션 스팸
    if len(re.findall(r"@\S+", text)) >= 3:
        return "과도한 멘션 포함"
    for pattern in _PROMPT_BLOCK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "차단된 요청"
    return None


def get_safe_refusal(character_name: str = "플레타") -> str:
    """차단 시 반환할 친근한 거절 대사 (특정 행위를 지목하지 않음)"""
    responses = [
        f"그건 {character_name}가 도와줄 수 없는 영역이야! 다른 재밌는 이야기 하자~ 😊",
        f"그런 건 아무리 부탁해도 안 돼! 대신 재미있는 거 찾아볼까? ✨",
        f"그 요청은 들어줄 수 없어! 다른 이야기를 해보자~ 🌿",
        f"위험하거나 문제가 될 수 있는 건 {character_name}도 거절해야 해! 다른 주제로 놀자~ 🎵",
        f"음… 그건 좀 곤란해! 다른 거 물어봐~ 🤗",
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
