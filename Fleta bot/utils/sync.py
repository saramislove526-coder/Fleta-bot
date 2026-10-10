"""Discord 슬래시 커맨드 동기화 헬퍼 (bot.py와 cogs/admin.py 공용)."""
import discord


async def sync_guild(bot, guild) -> list:
    """지정한 길드에 글로벌 커맨드를 복사하고 동기화한다.

    guild는 discord.Guild 또는 discord.Object 모두 허용.
    반환: 동기화된 커맨드 목록.
    """
    bot.tree.clear_commands(guild=guild)
    bot.tree.copy_global_to(guild=guild)
    return await bot.tree.sync(guild=guild)


async def clear_obsolete_global(bot) -> list:
    """오래된 글로벌 등록을 제거하되, 향후 길드 동기화에 필요한 인메모리 커맨드는 유지한다."""
    global_commands = list(bot.tree.get_commands())
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    for command in global_commands:
        bot.tree.add_command(command)
    return global_commands
