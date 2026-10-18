import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    CHAT_TRIGGER,
    CONVERSATION_TIMEOUT_SECONDS,
    IDLE_TOPIC_COOLDOWN_MINUTES,
    IDLE_TOPIC_ENABLED,
    IDLE_TOPIC_INTERVAL_MINUTES,
    IDLE_TOPIC_MIN_IDLE_MINUTES,
    MAX_USER_INPUT_CHARS,
)
from database.database import db
from services.ai_service import AIServiceError, generate_response
from services.conversation_starter import create_topic_starter
from services.intents import (
    detect_alarm_intent,
    format_delay,
    has_alarm_cue,
    has_cancel_cue,
    has_list_cue,
)
from cogs.alarms import describe_alarm
from ui.status_card import build_affection_card
from utils.helpers import check_prompt_safety, filter_spam_response, get_safe_refusal, sanitize_mentions

log = logging.getLogger(__name__)
CUSTOM_EMOJI = re.compile(r"<a?:([^:>]+):\d+>")
IMAGE_URL = re.compile(r"https?://\S+?\.(?:png|jpe?g|webp|gif)(?:\?\S*)?$", re.IGNORECASE)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_conversations: dict[tuple[int, int], float] = {}
        self.idle_starter_sent: dict[int, float] = {}
        self._starter_busy = False
        self.processing_users: set[int] = set()
        self.user_cooldowns: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Ready as %s", self.bot.user)

    # --- 유휴 상태 자동 대화 주제 ---
    async def cog_load(self):
        if IDLE_TOPIC_ENABLED:
            self.idle_topic_loop.start()

    async def cog_unload(self):
        self.idle_topic_loop.cancel()

    @tasks.loop(minutes=IDLE_TOPIC_INTERVAL_MINUTES)
    async def idle_topic_loop(self):
        if self._starter_busy:
            return
        self._starter_busy = True
        try:
            await self._maybe_start_topic_conversation()
        except Exception:
            log.exception("Idle topic loop error")
        finally:
            self._starter_busy = False

    @idle_topic_loop.before_loop
    async def before_idle_topic_loop(self):
        await self.bot.wait_until_ready()

    async def _maybe_start_topic_conversation(self):
        """대화가 끊긴 채널에 뉴스/이슈 주제로 먼저 말을 건다 (틱당 1채널)."""
        now = time.monotonic()
        min_idle = IDLE_TOPIC_MIN_IDLE_MINUTES * 60
        cooldown = IDLE_TOPIC_COOLDOWN_MINUTES * 60

        # 세션이 만료된(=바쁘지 않은) 대화 채널 후보 수집
        candidates = []
        for (user_id, channel_id), expiry in list(self.active_conversations.items()):
            idle_for = now - expiry
            if idle_for < min_idle:
                continue
            if now - self.idle_starter_sent.get(channel_id, float("-inf")) < cooldown:
                continue
            candidates.append((idle_for, user_id, channel_id))

        if not candidates:
            return

        # 가장 오래 방치된 순으로 시도
        candidates.sort(reverse=True)
        for _idle_for, user_id, channel_id in candidates[:3]:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                continue
            character = db.get_selected_character(user_id)
            if not character:
                continue

            async with channel.typing():
                starter = await create_topic_starter(user_id, character)
            if not starter:
                continue

            try:
                await channel.send(
                    sanitize_mentions(starter),
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
                )
            except discord.DiscordException:
                log.exception("Failed to send idle topic starter to channel %s", channel_id)
                continue
            self.idle_starter_sent[channel_id] = now
            # 세션을 다시 활성화해 유저가 답하면 자연스럽게 이어지도록 함
            self.active_conversations[(user_id, channel_id)] = time.monotonic() + CONVERSATION_TIMEOUT_SECONDS
            log.info("Sent idle topic starter to channel %s", channel_id)
            return

    async def _is_reply_to_bot(self, message: discord.Message) -> bool:
        if not message.reference or not message.reference.message_id:
            return False
        referenced = message.reference.resolved
        try:
            if not isinstance(referenced, discord.Message):
                referenced = await message.channel.fetch_message(message.reference.message_id)
            return referenced.author.id == self.bot.user.id
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

    @staticmethod
    def _image_urls(message: discord.Message) -> list[str]:
        urls = []
        for attachment in message.attachments:
            content_type = attachment.content_type or ""
            if content_type.startswith("image/") or attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
                urls.append(attachment.url)
        for embed in message.embeds:
            if embed.image and embed.image.url:
                urls.append(embed.image.url)
            if embed.thumbnail and embed.thumbnail.url:
                urls.append(embed.thumbnail.url)
        urls.extend(match.group(0) for match in IMAGE_URL.finditer(message.content))
        urls.extend(str(sticker.url) for sticker in message.stickers if getattr(sticker, "url", None))
        return list(dict.fromkeys(urls))[:3]

    @staticmethod
    def _message_context(message: discord.Message, text: str) -> str:
        details = []
        emoji_names = CUSTOM_EMOJI.findall(text)
        if emoji_names:
            details.append(f"Custom emoji reaction: {', '.join(emoji_names)}. Treat it as an emotion, not a photo.")
        if message.stickers:
            details.append(f"Sticker sent: {', '.join(sticker.name for sticker in message.stickers)}. React naturally to its mood.")
        if message.attachments:
            details.append(f"Attached files: {', '.join(item.filename for item in message.attachments)}.")
        if text:
            details.insert(0, text)
        return "\n".join(details)

    async def _send_chat_log(self, message: discord.Message, question: str, response: str):
        channel_id = db.get_setting("chat_log_channel_id", "")
        if not channel_id:
            return
        try:
            channel = self.bot.get_channel(int(channel_id))
        except (TypeError, ValueError):
            log.warning("Invalid chat log channel ID: %s", channel_id)
            return
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except discord.DiscordException:
                log.exception("Failed to fetch chat log channel %s", channel_id)
                return

        embed = discord.Embed(title="채팅 로그", color=discord.Color.blurple())
        embed.add_field(name="사용자", value=f"{message.author} ({message.author.id})", inline=False)
        embed.add_field(name="채널", value=f"<#{message.channel.id}>", inline=False)
        embed.add_field(name="질문", value=question[:1024] or "(내용 없음)", inline=False)
        embed.add_field(name="응답", value=response[:1024] or "(내용 없음)", inline=False)
        try:
            await channel.send(embed=embed)
        except discord.DiscordException:
            log.exception("Failed to send chat log to channel %s", channel_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content.strip()
        if not content and not message.attachments and not message.stickers:
            return

        # 중복 생성 방지: 이미 해당 유저의 응답을 생성 중이면 중복 요청 무시 (도배 방지)
        if message.author.id in self.processing_users:
            return

        now = time.monotonic()
        # 유저별 1.5초 쿨다운: 너무 빠른 연속 호출 차단 (도배 방지)
        if now - self.user_cooldowns.get(message.author.id, 0) < 1.5:
            return

        key = (message.author.id, message.channel.id)
        is_mentioned = self.bot.user in message.mentions if self.bot.user else False

        # 한글 트리거 비교 시 안전하게 공백 및 소문자 처리
        triggered = bool(CHAT_TRIGGER) and content.startswith(CHAT_TRIGGER)
        # 멘션/트리거로 이미 응답할 메시지가 아니라면 답글 여부(API fetch)만 확인
        is_reply = False
        if message.guild is not None and not (is_mentioned or triggered):
            is_reply = await self._is_reply_to_bot(message)

        # DM은 1:1 대화이므로 항상 응답.
        # 서버에서는 멘션(@플레타), 답장(Reply), 트리거("플레타 ...")일 때만 명확히 응답.
        # (서버 일반 대화에 끼어들어 도배하는 현상 완전 차단)
        if message.guild is None:
            should_respond = True
        else:
            should_respond = is_mentioned or is_reply or triggered

        if not should_respond:
            return

        # 멘션 문자열 제거
        prompt = content
        if self.bot.user:
            prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", prompt).strip()

        # 호출 트리거 이름으로 시작한 경우 트리거 이름 떼어내기 (한글 글자 수 기준 안전 슬라이싱)
        if CHAT_TRIGGER and prompt.startswith(CHAT_TRIGGER):
            prompt = prompt[len(CHAT_TRIGGER):].strip()

        # (로그용) 유저가 실제로 입력한 질문 — reply/이모지/이미지 컨텍스트가 붙기 전 시점
        user_question = prompt

        # 프롬프트 차단: 도배/탈옥/보안 정책 우회 시도시 AI 호출 없이 즉각 거절 (비용 및 도배 원천 차단)
        if check_prompt_safety(prompt):
            char = db.get_selected_character(message.author.id)
            char_name = char["name"] if char else "플레타"
            refusal = get_safe_refusal(char_name)
            await message.reply(
                refusal,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False, replied_user=False),
            )
            return

        # 컨텍스트 제한: 유저 입력 길이 상한 적용
        prompt = prompt[:MAX_USER_INPUT_CHARS]

        # 답장 대상 메시지 내용을 컨텍스트로 제공 (캐시에 있을 때만, 추가 API 호출 없음)
        resolved_ref = message.reference.resolved if message.reference else None
        if isinstance(resolved_ref, discord.Message) and resolved_ref.content:
            ref_author = resolved_ref.author.display_name if resolved_ref.author else "알 수 없음"
            reply_context = f"[답장한 메시지 - {ref_author}]: {resolved_ref.content[:150]}"
            prompt = f"{reply_context}\n{prompt}" if prompt else reply_context

        image_urls = self._image_urls(message)
        prompt = self._message_context(message, prompt)
        if not prompt:
            prompt = "The user called your name without adding a new topic. Continue the most recent conversation naturally."
        prompt = prompt[:MAX_USER_INPUT_CHARS + 200]

        # 만료된 세션 주기적 정리
        if len(self.active_conversations) > 300:
            self.active_conversations = {k: v for k, v in self.active_conversations.items() if v > now}

        # 자연어 알람 지시 감지 (본 응답 생성과 병렬 실행, 관련 키워드가 있을 때만)
        if has_cancel_cue(prompt):
            alarm_intent: dict | None = {"type": "cancel"}  # 키워드만으로 판정 (AI 호출 없음)
        elif has_list_cue(prompt):
            alarm_intent = {"type": "list"}
        elif has_alarm_cue(prompt):
            alarm_intent = None
            intent_coro = asyncio.to_thread(detect_alarm_intent, prompt)
        else:
            alarm_intent = None
            intent_coro = None

        self.processing_users.add(message.author.id)
        self.user_cooldowns[message.author.id] = now
        try:
            async with message.channel.typing():
                gen_coro = generate_response(message.author.id, message.guild.id if message.guild else None, prompt, image_urls)
                if intent_coro:
                    (response, affection_result), detected_intent = await asyncio.gather(gen_coro, intent_coro)
                    if detected_intent:
                        alarm_intent = detected_intent
                else:
                    response, affection_result = await gen_coro
                self.active_conversations[key] = now + CONVERSATION_TIMEOUT_SECONDS
                safe_response = filter_spam_response(response)
                safe_response = sanitize_mentions(safe_response[:1980])
                await message.reply(
                    safe_response,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False, replied_user=False),
                )
                # 호감도 "레벨"이 올랐거나 내렸을 때만 축하/알림 카드 전송 (매 대화마다 카드 2개씩 보내는 도배 방지)
                if affection_result and affection_result.get("level_changed"):
                    try:
                        await message.reply(view=build_affection_card(affection_result), mention_author=False)
                    except discord.DiscordException:
                        log.exception("Failed to send affection status card")
                # 자연어로 요청한 알람 설정/취소/목록
                if alarm_intent and alarm_intent.get("type") == "cancel":
                    count = db.cancel_user_alarms(message.author.id, message.channel.id)
                    if count:
                        cancel_msg = f"🔕 예약된 알람 **{count}개**를 취소했어요!"
                    else:
                        cancel_msg = "😴 이 채널에 예약된 알람이 없어요."
                    await message.reply(cancel_msg, mention_author=False, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
                elif alarm_intent and alarm_intent.get("type") == "list":
                    rows = db.get_user_alarms(message.author.id, message.channel.id)
                    if rows:
                        lines = "\n".join(describe_alarm(row) for row in rows[:10])
                        list_msg = f"⏰ 예약된 알람 **{len(rows)}개**야:\n{lines}"
                    else:
                        list_msg = "😴 이 채널에 예약된 알람이 없어요. \"10분 뒤에 알려줘\"처럼 말하면 설정해 드릴게요!"
                    await message.reply(sanitize_mentions(list_msg[:1980]), mention_author=False, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
                elif alarm_intent:
                    delay = alarm_intent["delay_minutes"]
                    raw_note = alarm_intent.get("note") or "알람"
                    note = sanitize_mentions(raw_note)
                    repeat = alarm_intent.get("repeat", "none")
                    repeat_seconds = {"daily": 86400, "weekly": 604800}.get(repeat, 0)
                    db.add_alarm(message.author.id, message.channel.id, time.time() + delay * 60, note, repeat_seconds)
                    repeat_tag = " (매일 반복)" if repeat == "daily" else " (매주 반복)" if repeat == "weekly" else ""
                    await message.reply(
                        f"⏰ 알람 설정 완료! **{format_delay(delay)}** 뒤에 \"{note}\"(으)로 알려드릴게요.{repeat_tag}",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False),
                    )
                await self._send_chat_log(message, user_question, response)
        except AIServiceError as error:
            if is_mentioned or is_reply or triggered or message.guild is None:
                await message.reply(str(error), mention_author=False)
        except Exception:
            log.exception("Message conversation error")
            if is_mentioned or is_reply or triggered or message.guild is None:
                await message.reply("응답을 생성하는 중 오류가 발생했습니다.", mention_author=False)
        finally:
            self.processing_users.discard(message.author.id)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ 요청이 너무 빠릅니다. {error.retry_after:.1f}초 후에 다시 시도해 주세요."
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 이 명령어를 사용할 권한이 없습니다."
        else:
            log.exception("Application command error", exc_info=error)
            msg = "명령을 처리하는 중 오류가 발생했습니다."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Events(bot))