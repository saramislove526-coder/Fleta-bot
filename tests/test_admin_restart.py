import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.admin import Admin


class RestartCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(_restart_requested=False, close=AsyncMock())
        self.cog = Admin(self.bot)

    def make_interaction(self, administrator, guild_id=123):
        guild = SimpleNamespace(id=guild_id) if guild_id else None
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=administrator),
        )
        response = SimpleNamespace(send_message=AsyncMock())
        return SimpleNamespace(guild=guild, user=member, response=response)

    async def test_server_administrator_can_restart(self):
        interaction = self.make_interaction(True)
        with patch("cogs.admin.DISCORD_GUILD_ID", 0):
            await Admin.restart.callback(self.cog, interaction)
        self.assertTrue(self.bot._restart_requested)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])
        self.bot.close.assert_awaited_once_with()

    async def test_non_admin_cannot_restart(self):
        interaction = self.make_interaction(False)
        with patch("cogs.admin.DISCORD_GUILD_ID", 0):
            await Admin.restart.callback(self.cog, interaction)
        self.assertFalse(self.bot._restart_requested)
        self.bot.close.assert_not_awaited()

    async def test_dm_cannot_restart(self):
        interaction = self.make_interaction(True, guild_id=0)
        with patch("cogs.admin.DISCORD_GUILD_ID", 0):
            await Admin.restart.callback(self.cog, interaction)
        self.assertFalse(self.bot._restart_requested)
        self.bot.close.assert_not_awaited()

    async def test_other_guild_cannot_restart_if_restricted(self):
        interaction = self.make_interaction(True, guild_id=222)
        with patch("cogs.admin.DISCORD_GUILD_ID", 123):
            await Admin.restart.callback(self.cog, interaction)
        self.assertFalse(self.bot._restart_requested)
        self.bot.close.assert_not_awaited()

    async def test_duplicate_restart_is_blocked(self):
        self.bot._restart_requested = True
        interaction = self.make_interaction(True)
        with patch("cogs.admin.DISCORD_GUILD_ID", 0):
            await Admin.restart.callback(self.cog, interaction)
        self.bot.close.assert_not_awaited()

    async def test_failed_ack_does_not_restart(self):
        interaction = self.make_interaction(True)
        interaction.response.send_message.side_effect = RuntimeError("send failed")
        with patch("cogs.admin.DISCORD_GUILD_ID", 0):
            with self.assertRaises(RuntimeError):
                await Admin.restart.callback(self.cog, interaction)
        self.assertFalse(self.bot._restart_requested)
        self.bot.close.assert_not_awaited()

    def test_command_metadata(self):
        command = Admin.restart
        self.assertEqual(command.name, "봇재시작")
        self.assertTrue(command.guild_only)
        self.assertTrue(command.default_permissions.administrator)
        self.assertTrue(command.checks)


if __name__ == "__main__":
    unittest.main()
