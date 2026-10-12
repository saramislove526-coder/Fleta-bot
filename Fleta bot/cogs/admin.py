import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_GUILD_ID
from database.database import db
from utils.sync import clear_obsolete_global, sync_guild


class Admin(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="sync", description="슬래시 명령어를 동기화합니다. (관리자)")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync(self, interaction):
        await interaction.response.defer(ephemeral=True)

        if DISCORD_GUILD_ID:
            guild_obj = discord.Object(id=DISCORD_GUILD_ID)
            synced = await sync_guild(self.bot, guild_obj)
            await clear_obsolete_global(self.bot)
            await interaction.followup.send(f"명령어 {len(synced)}개를 해당 서버에 동기화했습니다.", ephemeral=True)
        elif self.bot.guilds:
            synced = []
            for guild in self.bot.guilds:
                guild_synced = await sync_guild(self.bot, guild)
                synced.extend(guild_synced)
            await clear_obsolete_global(self.bot)
            await interaction.followup.send(f"명령어 {len(synced)}개를 모든 서버에 동기화했습니다.", ephemeral=True)
        else:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"명령어 {len(synced)}개를 글로벌로 동기화했습니다.", ephemeral=True)

    @app_commands.command(name="set_log_channel", description="공개 캐릭터 공지/로그 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="공개 캐릭터 게시용 포럼 채널을 선택하세요.")
    async def set_log_channel(self, interaction, channel: discord.ForumChannel = None):
        await interaction.response.defer(ephemeral=True)
        if channel is None:
            db.set_setting("public_character_channel_id", "")
            await interaction.followup.send("공개 캐릭터 포럼 채널 설정을 삭제했습니다.", ephemeral=True)
            return

        db.set_setting("public_character_channel_id", str(channel.id))
        await interaction.followup.send(f"공개 캐릭터 포럼 채널을 {channel.mention}(으)로 설정했습니다.", ephemeral=True)

    @app_commands.command(name="set_chat_log_channel", description="대화 로그를 보낼 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="대화 로그를 보낼 텍스트 채널을 선택하세요. 비워두면 해제합니다.")
    async def set_chat_log_channel(self, interaction, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        if channel is None:
            db.set_setting("chat_log_channel_id", "")
            await interaction.followup.send("대화 로그 채널 설정을 해제했습니다.", ephemeral=True)
            return

        db.set_setting("chat_log_channel_id", str(channel.id))
        await interaction.followup.send(f"대화 로그 채널을 {channel.mention}(으)로 설정했습니다.", ephemeral=True)

    @app_commands.command(name="log_channel", description="현재 설정된 공개 캐릭터 포럼 채널을 확인합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def log_channel(self, interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = db.get_setting("public_character_channel_id", "")
        if not channel_id:
            await interaction.followup.send("현재 설정된 공개 캐릭터 포럼 채널이 없습니다.", ephemeral=True)
            return

        try:
            channel_id_int = int(channel_id)
        except ValueError:
            await interaction.followup.send(f"잘못된 로그 채널 ID가 저장되어 있습니다: {channel_id}", ephemeral=True)
            return

        target_channel = self.bot.get_channel(channel_id_int)
        if target_channel is None:
            try:
                target_channel = await self.bot.fetch_channel(channel_id_int)
            except discord.DiscordException:
                target_channel = None

        if target_channel is None:
            await interaction.followup.send(f"저장된 공개 캐릭터 포럼 채널 <#{channel_id_int}>을 찾을 수 없습니다.", ephemeral=True)
            return

        if not isinstance(target_channel, discord.ForumChannel):
            await interaction.followup.send("저장된 채널이 포럼 채널이 아닙니다. `/set_log_channel`에서 포럼 채널을 다시 선택해 주세요.", ephemeral=True)
            return

        await interaction.followup.send(f"현재 공개 캐릭터 포럼 채널은 <#{channel_id_int}>입니다.", ephemeral=True)

    @app_commands.command(name="chat_log_channel", description="현재 설정된 대화 로그 채널을 확인합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def chat_log_channel(self, interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = db.get_setting("chat_log_channel_id", "")
        if not channel_id:
            await interaction.followup.send("현재 설정된 대화 로그 채널이 없습니다.", ephemeral=True)
            return
        await interaction.followup.send(f"현재 대화 로그 채널은 <#{channel_id}>입니다.", ephemeral=True)

    @sync.error
    async def sync_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
        else:
            raise error


async def setup(bot): await bot.add_cog(Admin(bot))
