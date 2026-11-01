import unittest

import discord
from discord.ext import commands

from cogs.admin import Admin


class HybridRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_prefix_and_slash_with_on_off_choices(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        try:
            await bot.add_cog(Admin(bot))
            prefix = bot.get_command("호출설정")
            self.assertIsInstance(prefix, commands.HybridCommand)

            slash = bot.tree.get_command("호출설정")
            self.assertIsNotNone(slash)
            self.assertEqual(slash.name, "호출설정")

            payload = slash.to_dict(bot.tree)
            options = {item["name"]: item for item in payload.get("options", [])}
            self.assertIn("state", options)
            self.assertFalse(options["state"].get("required", False))
            self.assertEqual(
                [(x["name"], x["value"]) for x in options["state"].get("choices", [])],
                [("ON", "on"), ("OFF", "off")],
            )
        finally:
            await bot.close()


if __name__ == "__main__":
    unittest.main()
