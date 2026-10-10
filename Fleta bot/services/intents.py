"""자연어 지시 인식: 대화 중 알람/타이머 요청을 알아듣는다."""
import logging
from datetime import datetime

from services.ai_service import _request_generation

log = logging.getLogger(__name__)

# 이 키워드가 있을 때만 분류기를 호출한다 (API 절약)
ALARM_CUES = (
    "알람", "알림", "타이머", "깨워", "리마인더", "리마인드", "상기",
    "알려줘", "알려 주", "뒤에 알려", "후에 알려", "시간 되면",
)
CANCEL_CUES = ("취소", "없애", "지워", "해제", "지워줘", "그만", "삭제")
LIST_CUES = ("목록", "몇 개", "뭐 있", "뭐가 있", "보여줘", "확인")


def has_alarm_cue(text: str) -> bool:
    return any(cue in text for cue in ALARM_CUES)


def has_cancel_cue(text: str) -> bool:
    return has_alarm_cue(text) and any(cue in text for cue in CANCEL_CUES)


def has_list_cue(text: str) -> bool:
    return has_alarm_cue(text) and any(cue in text for cue in LIST_CUES)


def format_delay(minutes: int) -> str:
    """분 단위를 '90분 → 1시간 30분' 형태로 변환."""
    if minutes < 60:
        return f"{minutes}분"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours}시간"
    return f"{hours}시간 {mins}분"


def detect_alarm_intent(user_message: str) -> dict | None:
    """
    알람/타이머/리마인더 지시를 인식한다 (동기 함수, to_thread로 실행).
    성공 시 {"type": "alarm", "delay_minutes": int, "note": str,
             "repeat": "none"|"daily"|"weekly"}, 아니면 None.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    system = (
        "You are an intent parser for a Korean Discord companion bot. "
        f"Current local time: {now_str}. "
        "If the user asks for an alarm, timer, or reminder (e.g. '10분 뒤에 알려줘', '5분 타이머', "
        "'오후 3시에 깨워줘', '저녁 먹고 나서 알림'), reply with EXACTLY one line:\n"
        "ALARM|<whole minutes from now>|<short reminder note in Korean>|<repeat>\n"
        "Convert absolute clock times into minutes-from-now using the current time. "
        "Round to whole minutes (minimum 1). The note is WHAT to remind about. "
        "<repeat> is one of: none, daily (매일/매일 아침 같은 반복), weekly (매주). "
        "If the message is NOT an alarm/timer/reminder request (searching, chatting, questions), reply EXACTLY: NONE"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message[:300]},
    ]
    try:
        raw = _request_generation(messages, max_tokens=60, temperature=0.0)
    except Exception:
        log.exception("Alarm intent detection failed")
        return None

    raw = (raw or "").strip()
    if not raw.upper().startswith("ALARM"):
        return None
    parts = raw.split("|")
    if len(parts) < 2:
        return None
    try:
        minutes = int(float(parts[1].strip()))
    except ValueError:
        return None
    minutes = max(1, min(minutes, 60 * 24 * 7))  # 1분 ~ 최대 1주일
    note = (parts[2].strip() if len(parts) > 2 else "") or "알람"
    repeat_raw = (parts[3].strip().lower() if len(parts) > 3 else "none")
    repeat = repeat_raw if repeat_raw in ("none", "daily", "weekly") else "none"
    return {
        "type": "alarm",
        "delay_minutes": minutes,
        "note": note[:100],
        "repeat": repeat,
    }
