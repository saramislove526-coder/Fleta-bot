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
