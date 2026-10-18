import discord
from discord import app_commands
from discord.ext import commands

from database.database import db
from services.affection import AffectionService
from ui.confirm_view import ConfirmView
from utils.embeds import affection_bar
from utils.helpers import truncate


class AI(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="status", description="선택한 캐릭터와의 관계 상태를 확인합니다.")
    async def status(self, interaction):
        character = db.get_selected_character(interaction.user.id)
        if not character:
            await interaction.response.send_message(
                "선택된 캐릭터가 없습니다. `/character select`로 먼저 선택해 주세요.", ephemeral=True)
            return

        user_id = interaction.user.id
        value = AffectionService.get(user_id, character["id"])
        memory_count = len(db.get_memories(user_id, character["id"], limit=1000))
        chat_count = db.count_conversations(user_id, character["id"])

        embed = discord.Embed(title=f"💬 {character['name']}와의 관계", color=discord.Color.pink())
        if character["avatar"]:
            embed.set_thumbnail(url=character["avatar"])
        embed.add_field(name="💕 호감도", value=f"**{value}/100**\n{affection_bar(value)}", inline=False)
        embed.add_field(name="관계 단계", value=AffectionService.get_level(value), inline=True)
        embed.add_field(name="🗂 저장된 기억", value=f"{memory_count}개", inline=True)
        embed.add_field(name="🗨 나눈 대화", value=f"{chat_count}통", inline=True)
        embed.add_field(name="소개", value=truncate(character["description"] or "소개 없음", 400), inline=False)
        embed.set_footer(text=f"캐릭터 #{character['id']} · 일반 채팅이나 멘션으로 대화할 수 있어요")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear", description="현재 캐릭터와의 대화 기록을 지웁니다.")
    async def clear(self, interaction):
        character = db.get_selected_character(interaction.user.id)
        if not character:
            await interaction.response.send_message("선택된 캐릭터가 없습니다.", ephemeral=True)
            return

        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ **{character['name']}**와의 대화 기록과 요약을 모두 지울까요?\n삭제하면 되돌릴 수 없습니다.",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.confirmed:
            db.clear_conversation(interaction.user.id, character["id"])
            await interaction.followup.send("🧹 대화 기록을 모두 지웠습니다. 새로운 첫인사로 시작해요!", ephemeral=True)
        elif view.confirmed is None:
            await interaction.followup.send("⌛ 시간이 지나 취소되었습니다.", ephemeral=True)


async def setup(bot): await bot.add_cog(AI(bot))
