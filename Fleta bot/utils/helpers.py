import re


def truncate(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


ZWSP = "\u200b"


def sanitize_mentions(text: str) -> str:
    """@everyone, @here, 역할 멘션 등 대량 멘션 테러를 원천 차단하기 위해 멘션을 무력화합니다."""
    if not text:
        return text
    # @everyone, @here 사이에 제로 너비 공백(\u200b)을 넣어 멘션 파싱 차단
    text = re.sub(r"@everyone", f"@{ZWSP}everyone", text, flags=re.IGNORECASE)
    text = re.sub(r"@here", f"@{ZWSP}here", text, flags=re.IGNORECASE)
    # 역할 멘션 <@&id> 무력화
    text = re.sub(r"<@&(\d+)>", lambda m: f"<@&{ZWSP}{m.group(1)}>", text)
    return text
