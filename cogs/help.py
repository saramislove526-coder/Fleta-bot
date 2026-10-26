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
                "- 봇을 멘션(`@플레타`)하거나 `플레타`로 시작하면 대답합니다.\n"
                "- `10분 뒤에 알려줘`처럼 자연어로 알람을 설정할 수 있어요.\n"
                "- `고양이 gif 보내줘`, `춤추는 움짤 줘`처럼 GIF도 요청할 수 있어요.\n"
                "- 이미지를 첨부하면 이미지를 보고 대답합니다.\n"
                "- 애니 추천, 음악 추천, 고민 상담 등 뭐든 물어보세요!"
            ),
            inline=False
        )
        embed.add_field(
            name="🎭 캐릭터",
            value=(
                "`/character create` - 새 캐릭터 생성\n"
                "`/character select` - 캐릭터 선택\n"
                "`/character list` - 내 캐릭터 목록\n"
                "`/character public` - 공개 캐릭터 검색\n"
                "`/status` - 호감도/관계 확인\n"
                "`/clear` - 대화 기록 초기화"
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ 유틸리티",
            value=(
                "`/summarize` - 채널 대화 AI 요약\n"
                "`/translate` - 텍스트 번역 (6개 언어)\n"
                "`/calc` - 수학 계산기\n"
                "`/poll` - 투표 생성\n"
                "`/serverinfo` - 서버 정보\n"
                "`/userinfo` - 유저 정보\n"
                "`/avatar` - 프로필 사진 확대\n"
                "`/dice` - 주사위 굴리기\n"
                "`/choose` - 선택 도우미\n"
                "`/gif` - Klipy 애니메이션 GIF(움짤) 검색\n"
                "`/ping` - 봇 응답 속도"
            ),
            inline=False
        )
        embed.add_field(
            name="⚙️ 관리자 전용",
            value=(
                "`/sync` - 슬래시 명령어 동기화\n"
                "`/set_log_channel` - 공개 캐릭터 포럼 채널 설정\n"
                "`/set_chat_log_channel` - 대화 로그 채널 설정"
            ),
            inline=False
        )
        embed.set_footer(text="궁금한 점이 있다면 대화로 물어보셔도 좋아요!")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
