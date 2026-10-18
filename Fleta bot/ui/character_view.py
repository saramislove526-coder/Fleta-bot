import discord

from ui.character_select import CharacterSelect


class CharacterView(discord.ui.View):
    def __init__(self, characters, callback, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.add_item(CharacterSelect(characters, callback))
