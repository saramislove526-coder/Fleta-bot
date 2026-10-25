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
            value=(
                "- 봇을 멘션(`@플레타`)하거나 `플레타`로 시작하는 채팅을 치면 대답합니다.\n"
                "- `10분 뒤에 알려줘`처럼 자연스럽게 알람을 설정할 수 있습니다.\n"
                "- 이미지를 첨부하면 이미지를 보고 대답할 수 있습니다.\n"
                "- 애니 추천, 음악 추천, 고민 상담 등 다양한 대화가 가능합니다."
            ),
            inline=False
        )
        embed.add_field(
            name="🎭 캐릭터 관리",
            value=(
                "`/character create` - 나만의 새 캐릭터를 만듭니다.\n"
                "`/character select` - 대화할 캐릭터를 선택합니다.\n"
                "`/character list` - 내 캐릭터 목록을 봅니다.\n"
                "`/character public` - 공개 캐릭터를 찾아봅니다.\n"
                "`/status` - 현재 캐릭터와의 호감도 및 관계를 확인합니다.\n"
                "`/clear` - 현재 캐릭터와의 기억/대화를 초기화합니다."
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ 유틸리티",
            value=(
                "`/summarize` - 채널의 최근 대화를 AI가 요약해줍니다.\n"
                "`/poll` - 간단한 투표를 만듭니다.\n"
                "`/serverinfo` - 서버 정보를 확인합니다.\n"
                "`/userinfo` - 유저 정보를 확인합니다.\n"
                "`/avatar` - 유저의 프로필 사진을 크게 봅니다.\n"
                "`/dice` - 주사위를 굴립니다.\n"
                "`/choose` - 선택지 중 하나를 골라줍니다."
            ),
            inline=False
        )
        embed.add_field(
            name="⚙️ 관리자 전용",
            value=(
                "`/sync` - 슬래시 명령어를 동기화합니다.\n"
                "`/set_log_channel` - 공개 캐릭터 포럼 채널을 설정합니다.\n"
                "`/set_chat_log_channel` - 대화 로그 채널을 설정합니다."
            ),
            inline=False
        )
        embed.set_footer(text="궁금한 점이 있다면 대화로 물어보셔도 좋아요!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
