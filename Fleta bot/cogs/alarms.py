import logging
import time

import discord
from discord.ext import commands, tasks

from database.database import db
from utils.helpers import sanitize_mentions

log = logging.getLogger(__name__)

_REPEAT_LABEL = {"daily": "매일", "weekly": "매주"}


def repeat_label(repeat_seconds: int) -> str:
    """반복 주기를 사람이 읽을 라벨로 변환 (86400=매일, 604800=매주, 그 외=빈 문자열)."""
    if repeat_seconds == 86400:
        return "매일"
    if repeat_seconds == 604800:
        return "매주"
    return ""


def _format_remaining(fire_at: float, now: float) -> str:
    seconds = max(1, int(fire_at - now))
    if seconds < 60:
        return f"{seconds}초"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}시간 {mins}분" if mins else f"{hours}시간"
    days, hours = divmod(hours, 24)
    return f"{days}일 {hours}시간" if hours else f"{days}일"


def describe_alarm(alarm) -> str:
    """알람 한 건을 '• **메모** — 3시간 20분 후 · 매일 반복' 형태로 요약."""
    now = time.time()
    repeat = alarm["repeat_seconds"] or 0
    repeat_tag = f" · {repeat_label(repeat)} 반복" if repeat in (86400, 604800) else ""
    return f"• **{alarm['note'] or '알람'}** — {_format_remaining(alarm['fire_at'], now)} 후{repeat_tag}"


class Alarms(commands.Cog):
    """저장된 알람을 주기적으로 확인해 시간이 되면 유저를 멘션하며 알려준다."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.alarm_loop.start()

    async def cog_unload(self):
        self.alarm_loop.cancel()

    @tasks.loop(seconds=20)
    async def alarm_loop(self):
        try:
            await self._fire_due_alarms()
        except Exception:
            log.exception("Alarm loop error")

    @alarm_loop.before_loop
    async def before_alarm_loop(self):
        await self.bot.wait_until_ready()

    async def _fire_due_alarms(self):
        for alarm in db.get_due_alarms(time.time()):
            channel = self.bot.get_channel(alarm["channel_id"])
            repeat = alarm["repeat_seconds"] or 0

            # 반복 알람은 다음 주기로 재예약, 1회성은 삭제
            if repeat > 0:
                db.reschedule_alarm(alarm["id"], alarm["fire_at"] + repeat)
            else:
                db.delete_alarm(alarm["id"])

            if not isinstance(channel, discord.abc.Messageable):
                log.warning("Alarm channel %s not found, alarm dropped", alarm["channel_id"])
                continue
            note = sanitize_mentions(alarm["note"] or "알람")
            repeat_tag = f" ({repeat_label(repeat)} 반복)" if repeat in (86400, 604800) else ""
            try:
                await channel.send(
                    f"⏰ <@{alarm['user_id']}> 알람 시간이에요! **{note}**{repeat_tag}",
                    allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
                )
            except discord.DiscordException:
                log.exception("Failed to send alarm to channel %s", alarm["channel_id"])


async def setup(bot):
    await bot.add_cog(Alarms(bot))
