import discord


class CharacterSelect(discord.ui.Select):
    def __init__(self, characters, callback):
        options = [discord.SelectOption(label=row["name"][:100], value=str(row["id"]), description=(row["description"] or "소개 없음")[:100]) for row in characters[:25]]
        super().__init__(placeholder="캐릭터를 선택하세요", options=options)
        self.callback_handler = callback

    async def callback(self, interaction: discord.Interaction):
        await self.callback_handler(interaction, int(self.values[0]))
