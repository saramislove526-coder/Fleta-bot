import re
import os
import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import MAX_CHARACTER_NAME_LENGTH, PUBLIC_CHARACTER_CHANNEL_ID
from database.database import db
from services.affection import AffectionService
from ui.character_view import CharacterView
from utils.embeds import affection_bar

log = logging.getLogger(__name__)


class PublicCharacterSelectView(discord.ui.View):
    def __init__(self, character_id: int):
        super().__init__(timeout=None)
        self.character_id = character_id
        # 재시작 후에도 버튼이 동작하려면 고유 custom_id가 필요함
        self.select_character.custom_id = f"public_character_select:{character_id}"

    @discord.ui.button(label="이 캐릭터 선택", style=discord.ButtonStyle.primary)
    async def select_character(self, interaction: discord.Interaction, button: discord.ui.Button):
        character = db.get_character(self.character_id)
        if not character:
            await interaction.response.send_message("죄송합니다. 이 캐릭터를 찾을 수 없습니다.", ephemeral=True)
            return

        db.set_selected_character(interaction.user.id, self.character_id)
        await interaction.response.send_message(
            f"✅ **{character['name']}** 캐릭터를 선택했습니다. 이제 일반 채팅으로 대화하세요.",
            ephemeral=True,
        )


class Character(commands.Cog):
    character = app_commands.Group(name="character", description="내 캐릭터를 관리합니다.")

    def __init__(self, bot):
        self.bot = bot
        self._runtime_public_channel_id: int | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇 재시작 후에도 기존 포럼 게시물의 "이 캐릭터 선택" 버튼이 동작하도록 영구 뷰 재등록
        try:
            for row in db.get_public_characters_with_threads():
                self.bot.add_view(PublicCharacterSelectView(row["id"]))
        except Exception:
            log.exception("Failed to re-register persistent public character views")

    def _get_public_character_channel_id(self) -> int:
        if self._runtime_public_channel_id is not None:
            return self._runtime_public_channel_id

        # 1. DB 설정 확인 (/set_log_channel)
        db_channel_id = db.get_setting("public_character_channel_id", "")
        if db_channel_id:
            try:
                return int(db_channel_id)
            except ValueError:
                pass

        # 2. .env 파일 설정 확인
        try:
            env_channel_id = int(os.getenv('PUBLIC_CHARACTER_CHANNEL_ID', '0'))
            if env_channel_id:
                return env_channel_id
        except ValueError:
            pass

        return PUBLIC_CHARACTER_CHANNEL_ID

    async def _announce_public_character(self, interaction: discord.Interaction, character):
        channel_id_val = self._get_public_character_channel_id()
        log.debug("Attempting to announce character id=%s name=%s to channel id=%s", character['id'], character['name'], channel_id_val)
        if not channel_id_val:
            log.warning("Public character channel ID is not configured; aborting announce")
            return
        channel = self.bot.get_channel(channel_id_val)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id_val)
                log.debug("Fetched channel %s via API", channel_id_val)
            except discord.DiscordException as exc:
                log.exception("Failed to fetch channel %s: %s", channel_id_val, exc)
                return
        if channel is None:
            log.warning("Channel %s not found after fetch; aborting announce", channel_id_val)
            return

        embed = discord.Embed(
            title=f"🌟 새 공개 캐릭터: {character['name']}",
            description=character['description'] or '소개 없음',
            color=discord.Color.green(),
        )
        if character['avatar']:
            embed.set_thumbnail(url=character['avatar'])
        embed.add_field(name='성격', value=character['personality'] or '없음', inline=True)
        embed.add_field(name='말투', value=character['speech'] or '없음', inline=True)
        embed.add_field(name='세계관', value=character['world'] or '없음', inline=False)
        embed.set_footer(text=f"작성자: {interaction.user.display_name} ({interaction.user.id})")
        view = PublicCharacterSelectView(character['id'])
        embed.add_field(name='선택 방법', value='아래 버튼을 눌러 캐릭터를 선택할 수 있습니다.', inline=False)

        posted = False
        try:
            if isinstance(channel, discord.ForumChannel) or hasattr(channel, 'create_post'):
                log.debug("Trying forum style posting on channel %s", channel_id_val)
                try:
                    thread_with_message = await channel.create_thread(
                        name=character['name'],
                        embed=embed,
                        view=view
                    )
                    thread = getattr(thread_with_message, 'thread', thread_with_message)
                    if hasattr(thread, 'id'):
                        db.set_character_thread(character['id'], thread.id)
                    posted = True
                except Exception:
                    log.exception("Forum create_thread failed, trying create_post...")
                    try:
                        post_result = await channel.create_post(
                            name=character['name'],
                            embed=embed,
                            view=view
                        )
                        thread = getattr(post_result, 'thread', post_result)
                        if hasattr(thread, 'id'):
                            db.set_character_thread(character['id'], thread.id)
                        posted = True
                    except Exception:
                        log.exception("create_post also failed, trying fallback send...")

            if not posted and hasattr(channel, 'create_thread'):
                log.debug("Trying channel.create_thread on %s", type(channel))
                try:
                    result = await channel.create_thread(
                        name=character['name']
                    )
                    thread = getattr(result, 'thread', result)
                    if hasattr(thread, 'send'):
                        await thread.send(embed=embed, view=view)
                        db.set_character_thread(character['id'], thread.id)
                        posted = True
                    elif hasattr(result, 'send'):
                        await result.send(embed=embed, view=view)
                        db.set_character_thread(character['id'], result.id)
                        posted = True
                except Exception:
                    log.exception("create_thread fallback failed on channel %s", channel_id_val)
        except Exception:
            log.exception("Forum posting attempt failed on channel %s", channel_id_val)
            posted = False

        if not posted:
            if hasattr(channel, 'send'):
                try:
                    msg = await channel.send(embed=embed, view=view)
                    if hasattr(msg, 'create_thread'):
                        try:
                            thread = await msg.create_thread(name=character['name'])
                            db.set_character_thread(character['id'], thread.id)
                        except Exception:
                            pass
                    posted = True
                except Exception:
                    log.exception("Failed to post public character to channel %s", channel_id_val)
            else:
                log.warning("Channel %s does not support send(); skipping fallback send", channel_id_val)

        if not posted:
            try:
                await interaction.followup.send("공개 캐릭터 게시에 실패했습니다. 봇에게 해당 채널에 쓰기 권한이 있는지, 채널 ID가 올바른지 확인해 주세요.", ephemeral=True)
            except Exception:
                pass
            return

    @character.command(name="create", description="새 캐릭터를 만듭니다.")
    @app_commands.describe(name="캐릭터 이름", description="간단한 소개", personality="성격", speech="말투", world="세계관", avatar="캐릭터 대표 이미지 URL", public="다른 사용자가 선택할 수 있게 공개할까요?")
    async def create(self, interaction, name: str, description: str, personality: str = "", speech: str = "", world: str = "", avatar: str = "", public: bool = True):
        name = name.strip()
        if not name or len(name) > MAX_CHARACTER_NAME_LENGTH:
            await interaction.response.send_message(f"이름은 1~{MAX_CHARACTER_NAME_LENGTH}자로 입력해 주세요.", ephemeral=True); return
        if db.get_character_by_name(interaction.user.id, name):
            await interaction.response.send_message("같은 이름의 캐릭터가 이미 있습니다.", ephemeral=True); return
        avatar_url = avatar.strip()

        character_id = db.create_character(
            interaction.user.id,
            name,
            description[:500],
            personality[:500],
            speech[:500],
            world[:500],
            avatar_url,
            1 if public else 0,
        )
        visibility = "공개" if public else "비공개"

        embed = discord.Embed(
            title=f"✨ 새 캐릭터 **{name}** 생성 완료! ({visibility})",
            description=f"**소개**: {description[:300] or '소개 없음'}\n**성격**: {personality[:200] or '미설정'}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=avatar_url)
        embed.set_footer(text="`/character select` 명령어로 이 캐릭터를 선택하면 바로 대화할 수 있습니다.")
        await interaction.response.send_message(embed=embed)

        if public:
            channel_id_val = self._get_public_character_channel_id()
            if not channel_id_val:
                log.warning("Public character channel is not configured; skipping public announce for character %s (owner=%s)", name, interaction.user.id)
            else:
                character = db.get_character(character_id)
                log.info("Announcing new public character %s (id=%s) to channel %s", name, character_id, channel_id_val)
                try:
                    await self._announce_public_character(interaction, character)
                    log.info("Announced character %s to channel %s", name, channel_id_val)
                except Exception:
                    log.exception("Failed to announce public character %s to channel %s", name, channel_id_val)
 
    async def _handle_public_character_selection(self, interaction: discord.Interaction, character_id: int):
       character = db.get_character(character_id)
       if not character:
            await interaction.response.send_message("해당 캐릭터를 찾을 수 없습니다.", ephemeral=True)
            return

       db.set_selected_character(interaction.user.id, character_id)
       await interaction.response.send_message(
            f"✅ **{character['name']}** 캐릭터를 선택했습니다. 이제 일반 채팅으로 대화하세요.",
            ephemeral=True,
       )

    @character.command(name="list", description="내 캐릭터 목록을 봅니다.")
    async def list_characters(self, interaction):
        characters = db.get_user_characters(interaction.user.id)
        if not characters:
            await interaction.response.send_message("아직 만든 캐릭터가 없습니다. `/character create`로 먼저 만들어 주세요.", ephemeral=True); return
        embed = discord.Embed(title=f"🎭 내 캐릭터 ({len(characters)}개)", color=discord.Color.blurple())
        for c in characters[:25]:
            embed.add_field(name=c["name"], value=f"{c['description'] or '소개 없음'}\n공개: {'예' if c['is_public'] else '아니오'}", inline=False)
        embed.set_footer(text="아래 메뉴에서 바로 선택하거나 `/character select`을 사용하세요.")
        view = CharacterView(characters, self._handle_public_character_selection)
        await interaction.response.send_message(embed=embed, view=view)

    @character.command(name="public", description="공개된 캐릭터를 검색하거나 둘러봅니다.")
    @app_commands.describe(query="검색어를 입력하면 이름, 소개, 설정에서 일치하는 공개 캐릭터를 찾아줍니다.")
    async def public_characters(self, interaction, query: str = ""):
        if query:
            characters = db.search_public_characters(query)
            if not characters:
                await interaction.response.send_message(f"'{query}'에 해당하는 공개 캐릭터가 없습니다.", ephemeral=True)
                return
            title = f"🔍 공개 캐릭터 검색 결과: {query}"
        else:
            characters = db.get_public_characters()
            if not characters:
                await interaction.response.send_message("아직 공개된 캐릭터가 없습니다.", ephemeral=True)
                return
            title = "🌍 공개 캐릭터"

        embed = discord.Embed(title=title, color=discord.Color.green())
        for c in characters:
            owner_display = f"<@{c['owner_id']}>"
            embed.add_field(
                name=f"{c['name']} — {owner_display}",
                value=f"{c['description'] or '소개 없음'}\n선택: `/character select {c['name']} {c['owner_id']}`",
                inline=False,
            )
        embed.set_footer(text="같은 이름이 여러 개면 owner_id를 함께 입력해 주세요.")
        view = CharacterView(characters, self._handle_public_character_selection)
        await interaction.response.send_message(embed=embed, view=view)

    @character.command(name="current", description="현재 선택된 캐릭터 정보를 봅니다.")
    async def current(self, interaction):
        character = db.get_selected_character(interaction.user.id)
        if not character:
            await interaction.response.send_message("선택된 캐릭터가 없습니다. `/character select`로 먼저 선택해 주세요.", ephemeral=True)
            return
        value = AffectionService.get(interaction.user.id, character["id"])
        embed = discord.Embed(title="🧠 현재 선택된 캐릭터", color=discord.Color.blurple())
        if character['avatar']:
            embed.set_thumbnail(url=character['avatar'])
        embed.add_field(name="이름", value=character['name'], inline=False)
        embed.add_field(name="소개", value=character['description'] or '소개 없음', inline=False)
        embed.add_field(name="성격", value=character['personality'] or '없음', inline=True)
        embed.add_field(name="말투", value=character['speech'] or '없음', inline=True)
        embed.add_field(name="세계관", value=character['world'] or '없음', inline=False)
        embed.add_field(
            name="💕 호감도",
            value=f"**{value}/100** {affection_bar(value)}\n{AffectionService.get_level(value)}",
            inline=False,
        )
        embed.set_footer(text="일반 채팅을 입력하면 이 캐릭터와 대화합니다.")
        await interaction.response.send_message(embed=embed)

    @character.command(name="select", description="대화할 캐릭터를 선택합니다.")
    @app_commands.describe(name="캐릭터 이름", owner_id="공개 캐릭터 소유자 ID 또는 멘션 (필요 시 입력)")
    async def select(self, interaction, name: str, owner_id: str = ""):
        owner_id_int = None
        if owner_id:
            mention_match = re.match(r"^<@!?(\d+)>$", owner_id)
            if mention_match:
                owner_id = mention_match.group(1)
            try:
                owner_id_int = int(owner_id)
            except ValueError:
                await interaction.response.send_message("owner_id는 숫자 또는 멘션 형식이어야 합니다.", ephemeral=True)
                return

        character = None
        if owner_id_int is not None:
            character = db.get_character_by_name(owner_id_int, name)
        else:
            public_characters = db.get_public_character_by_name(name)
            if len(public_characters) == 1:
                character = public_characters[0]
            elif len(public_characters) > 1:
                await interaction.response.send_message("같은 이름의 공개 캐릭터가 여러 개 있습니다. owner_id를 함께 입력해 주세요.", ephemeral=True)
                return
            else:
                character = db.get_character_by_name(interaction.user.id, name)

        if not character or (character['is_public'] == 0 and character['owner_id'] != interaction.user.id):
            await interaction.response.send_message("캐릭터를 찾을 수 없습니다. 공개 캐릭터는 `/character public`에서 확인하세요.", ephemeral=True)
            return

        db.set_selected_character(interaction.user.id, character['id'])
        await interaction.response.send_message(f"✅ 현재 캐릭터를 **{character['name']}**(으)로 선택했습니다.")

    @character.command(name="delete", description="캐릭터를 삭제합니다.")
    async def delete(self, interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        character = db.get_character_by_name(interaction.user.id, name)
        if not character:
            await interaction.followup.send("캐릭터를 찾을 수 없습니다.", ephemeral=True)
            return

        thread_id = character["thread_id"] if "thread_id" in character.keys() else None
        if thread_id:
            try:
                thread_channel = self.bot.get_channel(int(thread_id))
                if thread_channel is None:
                    thread_channel = await self.bot.fetch_channel(int(thread_id))
                if thread_channel is not None:
                    await thread_channel.delete(reason=f"Public character '{name}' deleted by owner")
                    log.info("Deleted thread %s for character %s", thread_id, name)
            except discord.NotFound:
                log.warning("Thread %s for character %s was already deleted or not found", thread_id, name)
            except discord.DiscordException:
                log.exception("Failed to delete thread %s for character %s", thread_id, name)

        if not db.delete_character(interaction.user.id, name):
            await interaction.followup.send("캐릭터를 삭제하는 중 오류가 발생했습니다.", ephemeral=True)
            return

        await interaction.followup.send(f"🗑️ **{name}** 캐릭터를 삭제했습니다.", ephemeral=True)





async def setup(bot): await bot.add_cog(Character(bot))