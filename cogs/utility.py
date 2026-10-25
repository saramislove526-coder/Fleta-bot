"""유틸리티 명령어 모음: 채널 요약, 투표, 정보 조회, 번역, 수학 등"""
import asyncio
import logging
import random
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from services.ai_service import _request_generation
from utils.helpers import sanitize_mentions

log = logging.getLogger(__name__)


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── 채널 요약 ──
    @app_commands.command(name="summarize", description="현재 채널의 최근 대화를 AI가 요약해줍니다.")
    @app_commands.describe(count="요약할 메시지 수 (기본 30, 최대 100)")
    async def summarize(self, interaction: discord.Interaction, count: int = 30):
        count = max(5, min(count, 100))
        await interaction.response.defer()

        try:
            messages_list = []
            async for msg in interaction.channel.history(limit=count):
                if msg.author.bot and msg.author.id == self.bot.user.id:
                    continue
                content = msg.content.strip()
                if not content:
                    continue
                author = msg.author.display_name
                messages_list.append(f"{author}: {content[:200]}")

            messages_list.reverse()

            if len(messages_list) < 2:
                await interaction.followup.send("요약할 메시지가 충분하지 않아요!", ephemeral=True)
                return

            transcript = "\n".join(messages_list)[:4000]

            ai_messages = [
                {"role": "system", "content": (
                    "You are a helpful assistant that summarizes Discord chat conversations. "
                    "Summarize in Korean with bullet points for key topics. "
                    "Start with a one-line overview, then bullet points. Be concise."
                )},
                {"role": "user", "content": f"다음 대화를 요약해줘:\n\n{transcript}"},
            ]

            summary = await asyncio.to_thread(_request_generation, ai_messages, max_tokens=600, temperature=0.3)
            summary = sanitize_mentions(summary)

            embed = discord.Embed(
                title=f"📋 채널 대화 요약 (최근 {count}개 메시지)",
                description=summary[:4000],
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"요청: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed)
        except Exception:
            log.exception("Channel summarize failed")
            await interaction.followup.send("요약 생성 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.", ephemeral=True)

    # ── 투표 ──
    @app_commands.command(name="poll", description="간단한 투표를 만듭니다.")
    @app_commands.describe(
        question="투표 질문",
        option1="선택지 1", option2="선택지 2",
        option3="선택지 3 (선택)", option4="선택지 4 (선택)", option5="선택지 5 (선택)",
    )
    async def poll(self, interaction: discord.Interaction, question: str, option1: str, option2: str,
                   option3: str = "", option4: str = "", option5: str = ""):
        options = [o for o in [option1, option2, option3, option4, option5] if o.strip()]
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        description = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options))
        embed = discord.Embed(title=f"📊 {question}", description=description, color=discord.Color.gold())
        embed.set_footer(text=f"투표 생성: {interaction.user.display_name} · 이모지를 눌러 투표하세요!")
        await interaction.response.send_message(embed=embed)
        try:
            msg = await interaction.original_response()
            for i in range(len(options)):
                await msg.add_reaction(emojis[i])
        except discord.DiscordException:
            pass

    # ── 서버 정보 ──
    @app_commands.command(name="serverinfo", description="서버 정보를 확인합니다.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("이 명령어는 서버에서만 사용할 수 있어요!", ephemeral=True)
            return
        embed = discord.Embed(title=f"📌 {guild.name} 서버 정보", color=discord.Color.green())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="👑 서버장", value=str(guild.owner) if guild.owner else "알 수 없음", inline=True)
        embed.add_field(name="👥 멤버 수", value=f"{guild.member_count}명", inline=True)
        embed.add_field(name="💬 채널 수", value=f"텍스트 {len(guild.text_channels)} / 음성 {len(guild.voice_channels)}", inline=True)
        embed.add_field(name="🎭 역할 수", value=f"{len(guild.roles)}개", inline=True)
        embed.add_field(name="📅 생성일", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="🔒 인증 수준", value=str(guild.verification_level), inline=True)
        if guild.description:
            embed.add_field(name="📝 서버 설명", value=guild.description[:200], inline=False)
        await interaction.response.send_message(embed=embed)

    # ── 유저 정보 ──
    @app_commands.command(name="userinfo", description="유저 정보를 확인합니다.")
    @app_commands.describe(user="정보를 볼 유저 (비워두면 본인)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"👤 {target.display_name}", color=target.color or discord.Color.blurple())
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)
        embed.add_field(name="🏷️ 사용자명", value=str(target), inline=True)
        embed.add_field(name="🆔 ID", value=str(target.id), inline=True)
        embed.add_field(name="📅 계정 생성", value=target.created_at.strftime("%Y-%m-%d"), inline=True)
        if hasattr(target, "joined_at") and target.joined_at:
            embed.add_field(name="📥 서버 참가", value=target.joined_at.strftime("%Y-%m-%d"), inline=True)
        roles = [r.mention for r in target.roles[1:]][:10]
        if roles:
            embed.add_field(name=f"🎭 역할 ({len(target.roles) - 1}개)", value=" ".join(roles), inline=False)
        await interaction.response.send_message(embed=embed)

    # ── 아바타 ──
    @app_commands.command(name="avatar", description="유저의 프로필 사진을 크게 봅니다.")
    @app_commands.describe(user="프로필을 볼 유저 (비워두면 본인)")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"🖼️ {target.display_name}의 프로필 사진", color=discord.Color.blurple())
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ── 주사위 ──
    @app_commands.command(name="dice", description="주사위를 굴립니다.")
    @app_commands.describe(sides="주사위 면 수 (기본 6)", count="주사위 개수 (기본 1)")
    async def dice(self, interaction: discord.Interaction, sides: int = 6, count: int = 1):
        sides = max(2, min(sides, 100))
        count = max(1, min(count, 10))
        results = [random.randint(1, sides) for _ in range(count)]
        dice_str = ", ".join(str(r) for r in results)
        msg = f"🎲 **{sides}면 주사위 {count}개 결과**: {dice_str}"
        if count > 1:
            msg += f"\n**합계**: {sum(results)}"
        await interaction.response.send_message(msg)

    # ── 선택 ──
    @app_commands.command(name="choose", description="여러 선택지 중 하나를 골라줍니다.")
    @app_commands.describe(choices="선택지들을 쉼표(,)로 구분해서 입력하세요")
    async def choose(self, interaction: discord.Interaction, choices: str):
        options = [c.strip() for c in choices.split(",") if c.strip()]
        if len(options) < 2:
            await interaction.response.send_message("최소 2개의 선택지를 쉼표로 구분해서 입력해주세요!", ephemeral=True)
            return
        await interaction.response.send_message(f"🤔 고민 끝! **{random.choice(options)}** (으)로 결정! 🎯")

    # ── 번역 ──
    @app_commands.command(name="translate", description="텍스트를 다른 언어로 번역합니다.")
    @app_commands.describe(text="번역할 텍스트", to="번역할 언어 (기본: 영어)")
    @app_commands.choices(to=[
        app_commands.Choice(name="영어", value="English"),
        app_commands.Choice(name="한국어", value="Korean"),
        app_commands.Choice(name="일본어", value="Japanese"),
        app_commands.Choice(name="중국어", value="Chinese"),
        app_commands.Choice(name="스페인어", value="Spanish"),
        app_commands.Choice(name="프랑스어", value="French"),
    ])
    async def translate(self, interaction: discord.Interaction, text: str, to: str = "English"):
        await interaction.response.defer()
        try:
            ai_messages = [
                {"role": "system", "content": f"You are a translator. Translate the following text to {to}. Output ONLY the translated text, nothing else."},
                {"role": "user", "content": text[:1000]},
            ]
            result = await asyncio.to_thread(_request_generation, ai_messages, max_tokens=500, temperature=0.1)
            result = sanitize_mentions(result)
            embed = discord.Embed(title=f"🌐 번역 → {to}", color=discord.Color.teal())
            embed.add_field(name="원문", value=text[:500], inline=False)
            embed.add_field(name="번역", value=result[:1000], inline=False)
            await interaction.followup.send(embed=embed)
        except Exception:
            log.exception("Translation failed")
            await interaction.followup.send("번역 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.", ephemeral=True)

    # ── 계산기 ──
    @app_commands.command(name="calc", description="수학 계산을 해줍니다.")
    @app_commands.describe(expression="계산할 수식 (예: 2+3*4, sqrt(16), 15%4)")
    async def calc(self, interaction: discord.Interaction, expression: str):
        # 안전한 수학 계산만 허용 (eval 대신 제한된 파서 사용)
        import math
        safe_expr = expression.strip()
        # 허용 문자: 숫자, 연산자, 괄호, 공백, 소수점, 수학 함수명
        if not re.match(r'^[\d\s+\-*/().%,a-zA-Z_]+$', safe_expr):
            await interaction.response.send_message("❌ 유효하지 않은 수식이에요!", ephemeral=True)
            return
        # 금지 키워드 (코드 실행 방지)
        forbidden = ['import', 'exec', 'eval', 'open', 'os', 'sys', '__', 'lambda', 'class', 'def', 'print', 'input', 'file', 'globals', 'locals', 'compile', 'getattr', 'setattr', 'delattr']
        if any(kw in safe_expr.lower() for kw in forbidden):
            await interaction.response.send_message("❌ 허용되지 않는 표현이에요!", ephemeral=True)
            return
        try:
            allowed_names = {
                "sqrt": math.sqrt, "abs": abs, "round": round,
                "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log, "log10": math.log10, "log2": math.log2,
                "pi": math.pi, "e": math.e, "pow": pow,
                "floor": math.floor, "ceil": math.ceil,
                "min": min, "max": max,
            }
            result = eval(safe_expr, {"__builtins__": {}}, allowed_names)
            if isinstance(result, float):
                if result == int(result) and abs(result) < 1e15:
                    result = int(result)
                else:
                    result = round(result, 10)
            await interaction.response.send_message(f"🧮 `{safe_expr}` = **{result}**")
        except ZeroDivisionError:
            await interaction.response.send_message("❌ 0으로 나눌 수 없어요!", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ 계산할 수 없는 수식이에요!", ephemeral=True)

    # ── 핑 ──
    @app_commands.command(name="ping", description="봇의 응답 속도를 확인합니다.")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        if latency < 100:
            status = "🟢 매우 빠름"
        elif latency < 200:
            status = "🟡 양호"
        else:
            status = "🔴 느림"
        await interaction.response.send_message(f"🏓 퐁! **{latency}ms** {status}")


async def setup(bot):
    await bot.add_cog(Utility(bot))
