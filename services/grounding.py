import re

# ──────────────────────────────────────────────
# 답변 검증 담당 파일입니다.
# AI가 쓴 답변에서 연도·날짜·수치를 뽑아서, 검색 자료에 진짜 나오는 숫자인지 대조합니다.
# AI 호출 없이 문자열만 비교하기 때문에 빠르고 비용도 안 듭니다.
# 근거 없는 숫자가 나왔을 때만 ai_service.py에서 한 번 고쳐 쓰게 합니다.
# ──────────────────────────────────────────────

# 답변 속 "검증이 필요한 숫자"를 찾는 패턴입니다.
# 연도(1999년), 날짜(3월 1일, 2024-05-01), 단위가 붙은 수치(12%, 3억 원, 5,000명)를 잡습니다.
_CLAIM_PATTERN = re.compile(
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}"
    r"|\d{1,2}월\s?\d{1,2}일"
    r"|\d{3,4}년"
    r"|\d[\d,]*(?:\.\d+)?\s?(?:%|퍼센트|억|만|천|조|명|개|원|달러|위|살|세|배"
    r"|mAh|GB|TB|MB|Hz|km|kg|cm|m|W)(?![A-Za-z])"
)
# 1~2 같은 작은 숫자 단독("1개", "2명")은 일상 대화에도 너무 흔해서 검증 대상에서 뺍니다.
_TRIVIAL = re.compile(r"^[1-3]\s?(?:개|명|위|배|번)$")


def _numbers(text: str) -> list[str]:
    """글 속 숫자를 정규화해서 뽑습니다.

    "5,000"과 "5000", "05"와 "5"를 같은 값으로 보려고 쉼표와 앞자리 0을 지웁니다.
    """
    return [token.replace(",", "").lstrip("0") or "0" for token in re.findall(r"\d[\d,]*", text or "")]


def extract_claims(answer: str) -> list[str]:
    """답변에서 연도·날짜·수치 표현만 뽑아 중복 없이 돌려줍니다."""
    claims = []
    for match in _CLAIM_PATTERN.finditer(answer or ""):
        claim = match.group(0).strip()
        if _TRIVIAL.match(claim) or claim in claims:
            continue
        claims.append(claim)
    return claims


def find_unsupported_claims(answer: str, evidence: str) -> list[str]:
    """검색 자료(evidence)에 숫자가 등장하지 않는 주장만 골라 돌려줍니다.

    "2024년"이면 자료에 2024가 있는지, "3월 1일"이면 3과 1이 함께 있는지처럼
    숫자 단위로 대조합니다. 단어 표현이 달라도 숫자가 같으면 근거가 있는 것으로 봅니다.
    """
    evidence_numbers = set(_numbers(evidence))
    return [
        claim
        for claim in extract_claims(answer)
        if not all(number in evidence_numbers for number in _numbers(claim))
    ]
