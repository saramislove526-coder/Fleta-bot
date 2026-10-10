import time
import re
from datetime import datetime
from database.database import db

class AffectionService:
    MIN_VALUE, MAX_VALUE = 0, 100

    # 1위 키워드: 칭찬, 감사의 말, 애정 표현 (+3~+5)
    PRAISE_KEYWORDS = [
        "고마워", "감사", "좋아해", "사랑해", "귀여", "귀엽", "멋지", "대단해",
        "최고", "보고싶", "착하", "착해", "수고했", "고생했", "예쁘", "이쁘", "응원해"
    ]

    # 2위 키워드: 자기 개방 / 정보 공유 (+2~+3)
    SELF_DISCLOSURE_KEYWORDS = [
        "나 오늘", "내 생각엔", "내가 좋아하는", "내가 제일", "나 사실", "내 비밀",
        "나 슬퍼", "나 기뻐", "나 힘들어", "나는 ", "요즘 나는"
    ]

    # 감소 키워드: 공격적 표현 / 비하 (-2~-5)
    NEGATIVE_KEYWORDS = [
        "바보", "멍청", "싫어", "짜증", "꺼져", "너 별로", "시끄러", "꺼져라", "못생겼"
    ]

    # 유저별 마지막 대화 시간 (도배 쿨다운 방지: 3초)
    _last_chat_time = {}

    @classmethod
    def get(cls, user_id: int, character_id: int) -> int:
        db.cursor.execute("SELECT value FROM affection WHERE user_id = ? AND character_id = ?", (user_id, character_id))
        row = db.cursor.fetchone()
        if row:
            return row["value"]
        cls.set(user_id, character_id, 0)
        return 0

    @classmethod
    def set(cls, user_id: int, character_id: int, value: int):
        value = max(cls.MIN_VALUE, min(cls.MAX_VALUE, value))
        db.cursor.execute(
            "INSERT INTO affection(user_id, character_id, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, character_id) DO UPDATE SET value = excluded.value",
            (user_id, character_id, value)
        )
        db.conn.commit()

    @classmethod
    def get_level(cls, value: int) -> str:
        if value >= 95: return "💍 영혼의 짝 (Level 6)"
        if value >= 80: return "💕 깊은 유대 (Level 5)"
        if value >= 60: return "💖 매우 친함 (Level 4)"
        if value >= 40: return "😊 친함 (Level 3)"
        if value >= 20: return "🙂 인지함 (Level 2)"
        return "🌱 낯선 사이 (Level 1)"

    # 도배 방지 쿨다운 (초)
    COOLDOWN_SECONDS = 3.0

    @classmethod
    def check_cooldown(cls, user_id: int, character_id: int) -> bool:
        """도배 방지: 쿨다운 이내 연속 채팅이면 False(평가 스킵). 허용되면 시각을 기록하고 True."""
        now = time.time()
        user_key = (user_id, character_id)

        # 딕셔너리 무한 증가 방지 (주기적 정리)
        if len(cls._last_chat_time) > 2000:
            cutoff = now - 60.0
            cls._last_chat_time = {k: v for k, v in cls._last_chat_time.items() if v > cutoff}

        last_time = cls._last_chat_time.get(user_key, 0)
        if now - last_time < cls.COOLDOWN_SECONDS:
            return False
        cls._last_chat_time[user_key] = now
        return True

    @classmethod
    def is_first_greeting_today(cls, user_id: int, character_id: int) -> bool:
        """오늘 이 캐릭터와 나눈 대화가 아직 없으면 True (첫 인사 보너스 판정용)."""
        db.cursor.execute(
            "SELECT COUNT(*) as count FROM conversations "
            "WHERE user_id = ? AND character_id = ? "
            "AND date(timestamp, 'localtime') = date('now', 'localtime')",
            (user_id, character_id)
        )
        row = db.cursor.fetchone()
        return bool(row and row["count"] == 0)

    @classmethod
    def evaluate_keywords(cls, user_id: int, character_id: int, message: str) -> int:
        """키워드 기반 폴백 평가: AI 감정 평가 실패 시 사용. DB 업데이트 없이 변화량만 반환."""
        delta = 0
        if any(kw in message for kw in cls.PRAISE_KEYWORDS):
            delta += 4
        if any(kw in message for kw in cls.SELF_DISCLOSURE_KEYWORDS):
            delta += 2
        if any(kw in message for kw in cls.NEGATIVE_KEYWORDS):
            delta -= 3
        return delta

    @classmethod
    def apply_delta(cls, user_id: int, character_id: int, delta: int, reasons: list[str] | None = None) -> dict:
        """계산된 호감도 변화량을 DB에 적용하고 결과를 반환."""
        current_val = cls.get(user_id, character_id)
        old_level = cls.get_level(current_val)

        new_val = current_val
        if delta != 0:
            new_val = max(cls.MIN_VALUE, min(cls.MAX_VALUE, current_val + delta))
            cls.set(user_id, character_id, new_val)

        new_level = cls.get_level(new_val)
        return {
            "delta": delta,
            "reasons": reasons if reasons is not None else [],
            "old_value": current_val,
            "new_value": new_val,
            "old_level": old_level,
            "new_level": new_level,
            "level_changed": (old_level != new_level)
        }

