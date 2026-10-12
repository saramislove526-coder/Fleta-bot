import discord
from discord import app_commands
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="플레타 봇의 사용 방법과 명령어 목록을 확인합니다.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✨ 플레타 봇 도움말",
            description="자연스럽고 똑똑한 AI 캐릭터 챗봇, 플레타입니다!\n멘션이나 `플레타`로 시작하는 말로 대화를 시작해보세요.",
            color=discord.Color.pink()
        )
        embed.add_field(
            name="🗣️ 기본 대화",
            value="- 봇을 멘션(`@플레타`)하거나 `플레타`로 시작하는 채팅을 치면 대답합니다.\n- `10분 뒤에 알려줘`처럼 자연스럽게 알람을 설정할 수 있습니다.\n- 이미지를 첨부하면 이미지를 보고 대답할 수 있습니다.",
            inline=False
        )
        embed.add_field(
            name="🛠️ 주요 명령어",
            value="`/character select` - 대화할 캐릭터를 선택합니다.\n`/character create` - 나만의 새 캐릭터를 만듭니다.\n`/status` - 현재 캐릭터와의 호감도 및 관계를 확인합니다.\n`/clear` - 현재 캐릭터와의 기억/대화를 초기화합니다.",
            inline=False
        )
        embed.set_footer(text="궁금한 점이 있다면 대화로 물어보셔도 좋아요!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
