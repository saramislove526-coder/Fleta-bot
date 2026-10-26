import re


def extract_memory(message: str) -> str | None:
    """사용자가 명시적으로 기억하라고 지시한 내용을 추출합니다.
    예:
      - '기억해: 나 사과 좋아해'
      - '기억해줘 나 오이 못 먹어'
      - '내 생일은 10월 5일이야 꼭 기억해줘'
      - '이거 기억해: 시험 다음주 월요일'
    """
    if not message:
        return None
    msg = message.strip()

    # 1. '기억해:' 또는 '기억해줘:' 등의 콜론 구분자
    for marker in ("기억해:", "기억해줘:", "기억해둬:", "이거 기억해:", "이거 기억해줘:"):
        if marker in msg:
            val = msg.split(marker, 1)[1].strip()
            if val:
                return val[:500]

    # 2. 문두 '기억해줘 / 기억해둬 / 꼭 기억해 / 기억해'
    m_start = re.match(r"^(?:꼭\s*|이거\s*)?기억해(?:줘|둬|라)?[:,\s]\s*(.+)$", msg)
    if m_start:
        val = m_start.group(1).strip()
        if val:
            return val[:500]

    # 3. 문미 '... 기억해줘 / 기억해둬 / 꼭 기억해'
    m_end = re.search(r"^(.*?)(?:,\s*|\s+)(?:꼭\s*)?기억해(?:줘|둬|라)?\.?$", msg)
    if m_end:
        val = m_end.group(1).strip()
        if val and len(val) >= 2:
            return val[:500]

    return None
