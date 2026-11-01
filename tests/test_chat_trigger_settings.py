import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.admin import Admin
from cogs.events import Events
from database.database import Database


class ChatTriggerPersistenceTests(unittest.TestCase):
    def test_per_guild_settings_survive_new_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("database.database.DATABASE_PATH", Path(temp) / "settings.db"):
                first = Database()
                self.assertTrue(first.get_chat_trigger_enabled(10))
                self.assertTrue(first.get_chat_trigger_enabled(20))
                first.set_chat_trigger_enabled(10, False)
                self.assertFalse(first.get_chat_trigger_enabled(10))
                self.assertTrue(first.get_chat_trigger_enabled(20))
                second = Database()
                self.assertFalse(second.get_chat_trigger_enabled(10))
                self.assertTrue(second.get_chat_trigger_enabled(20))
                second.set_chat_trigger_enabled(10, True)
                self.assertTrue(first.get_chat_trigger_enabled(10))
                second.conn.close()
                first.conn.close()


class ChatTriggerCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = Admin(SimpleNamespace())
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=1234),
            author=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
            interaction=object(),
            send=AsyncMock(),
        )

    async def test_on_off_changes_settings(self):
        with patch("cogs.admin.db") as settings:
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx, "off")
            settings.set_chat_trigger_enabled.assert_called_once_with(1234, False)
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx, "on")
            settings.set_chat_trigger_enabled.assert_called_with(1234, True)
        self.assertTrue(self.ctx.send.await_args.kwargs["ephemeral"])

    async def test_status_does_not_write(self):
        with patch("cogs.admin.db") as settings:
            settings.get_chat_trigger_enabled.return_value = False
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx)
            settings.set_chat_trigger_enabled.assert_not_called()
        self.assertIn("OFF", self.ctx.send.await_args.args[0])

    async def test_non_administrator_cannot_change(self):
        self.ctx.author.guild_permissions.administrator = False
        with patch("cogs.admin.db") as settings:
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx, "off")
            settings.set_chat_trigger_enabled.assert_not_called()
        self.assertIn("관리자", self.ctx.send.await_args.args[0])

    async def test_dm_cannot_change(self):
        self.ctx.guild = None
        with patch("cogs.admin.db") as settings:
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx, "off")
            settings.set_chat_trigger_enabled.assert_not_called()

    async def test_invalid_value_does_not_change(self):
        with patch("cogs.admin.db") as settings:
            await Admin.chat_trigger_setting.callback(self.cog, self.ctx, "invalid")
            settings.set_chat_trigger_enabled.assert_not_called()


class ChatTriggerMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot_user = SimpleNamespace(id=999)
        self.cog = Events(SimpleNamespace(user=self.bot_user))
        self.message = SimpleNamespace(
            author=SimpleNamespace(bot=False, id=111),
            content="플레타 테스트",
            attachments=[],
            stickers=[],
            guild=SimpleNamespace(id=1234),
            channel=SimpleNamespace(id=222),
            mentions=[],
            reply=AsyncMock(),
        )

    async def test_disabled_name_trigger_does_not_reply(self):
        with patch("cogs.events.db") as settings:
            settings.get_chat_trigger_enabled.return_value = False
            with patch.object(self.cog, "_is_reply_to_bot", new_callable=AsyncMock, return_value=False):
                await self.cog.on_message(self.message)
        self.message.reply.assert_not_awaited()

    async def test_enabled_name_trigger_still_replies(self):
        with patch("cogs.events.db") as settings, \
             patch("cogs.events.check_prompt_safety", return_value="blocked"), \
             patch("cogs.events.get_safe_refusal", return_value="no"):
            settings.get_chat_trigger_enabled.return_value = True
            settings.get_selected_character.return_value = None
            await self.cog.on_message(self.message)
        self.message.reply.assert_awaited_once()

    async def test_mention_still_replies_when_disabled(self):
        self.message.mentions = [self.bot_user]
        with patch("cogs.events.db") as settings, \
             patch("cogs.events.check_prompt_safety", return_value="blocked"), \
             patch("cogs.events.get_safe_refusal", return_value="no"):
            settings.get_chat_trigger_enabled.return_value = False
            settings.get_selected_character.return_value = None
            await self.cog.on_message(self.message)
        self.message.reply.assert_awaited_once()

    async def test_mention_does_not_strip_disabled_name(self):
        self.message.mentions = [self.bot_user]
        with patch("cogs.events.db") as settings, \
             patch("cogs.events.check_prompt_safety", return_value="blocked") as safety, \
             patch("cogs.events.get_safe_refusal", return_value="no"):
            settings.get_chat_trigger_enabled.return_value = False
            settings.get_selected_character.return_value = None
            await self.cog.on_message(self.message)
        safety.assert_called_once_with("플레타 테스트")

    async def test_alarm_cancel_does_not_reference_missing_coroutine(self):
        self.message.content = "플레타 알람 취소해줘"
        self.message.reference = None
        self.message.channel.typing = MagicMock(return_value=AsyncMock())
        with patch("cogs.events.db") as settings, \
             patch("cogs.events.generate_response", new_callable=AsyncMock, return_value=("알겠습니다", None)), \
             patch("cogs.events.has_cancel_cue", return_value=True), \
             patch("cogs.events.extract_gif_query", return_value=None), \
             patch.object(self.cog, "_send_chat_log", new_callable=AsyncMock):
            settings.get_chat_trigger_enabled.return_value = True
            settings.cancel_user_alarms.return_value = 0
            await self.cog.on_message(self.message)
        self.assertEqual(self.message.reply.await_count, 2)
        self.assertIn("알겠습니다", self.message.reply.await_args_list[0].args[0])

    async def test_reply_still_works_when_disabled(self):
        with patch("cogs.events.db") as settings, \
             patch.object(self.cog, "_is_reply_to_bot", new_callable=AsyncMock, return_value=True), \
             patch("cogs.events.check_prompt_safety", return_value="blocked"), \
             patch("cogs.events.get_safe_refusal", return_value="no"):
            settings.get_chat_trigger_enabled.return_value = False
            settings.get_selected_character.return_value = None
            await self.cog.on_message(self.message)
        self.message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
