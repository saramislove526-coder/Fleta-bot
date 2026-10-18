import discord


class CharacterModal(discord.ui.Modal, title="캐릭터 만들기"):
    name = discord.ui.TextInput(label="이름", max_length=50)
    description = discord.ui.TextInput(label="소개", style=discord.TextStyle.paragraph, max_length=500)
    personality = discord.ui.TextInput(label="성격 (선택)", required=False, max_length=500)
    speech = discord.ui.TextInput(label="말투 (선택)", required=False, max_length=500)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.name.value, self.description.value, self.personality.value, self.speech.value)
