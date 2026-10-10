import discord

from utils.embeds import affection_bar


def build_affection_card(result: dict) -> discord.ui.LayoutView:
    """
    호감도 변화 상황을 Components V2 카드(LayoutView)로 만든다.
    AI 응답 직후 events.py에서 별도 메시지로 함께 전송된다.
    """
    name = result.get("character_name", "캐릭터")
    delta = result.get("delta", 0)
    old_value = result.get("old_value", 0)
    new_value = result.get("new_value", 0)
    mood = "✨" if delta > 0 else "💧"

    header = discord.ui.TextDisplay(f"### {mood} {name}와의 관계에 변화가 있어요")
    change = discord.ui.TextDisplay(
        f"**호감도 {old_value}** ➡️ **{new_value}** ({delta:+d})\n"
        f"{affection_bar(new_value)}\n"
        f"{result.get('old_level', '-')} ➡️ **{result.get('new_level', '-')}**"
    )

    avatar = result.get("avatar") or None
    if avatar:
        top = discord.ui.Section(header, change, accessory=discord.ui.Thumbnail(avatar))
    else:
        top = [header, change]  # 아바타가 없으면 섹션 없이 텍스트 직접 배치

    reasons = result.get("reasons") or []
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- 자연스러운 대화의 흐름"
    reasons_display = discord.ui.TextDisplay(f"**이번에 느낀 것**\n{reason_text}")
    footer = discord.ui.TextDisplay("-# `/status` 명령어로 관계를 자세히 볼 수 있어요")

    children = top if isinstance(top, list) else [top]
    container = discord.ui.Container(
        *children,
        discord.ui.Separator(),
        reasons_display,
        footer,
        accent_colour=discord.Colour.pink() if delta > 0 else discord.Colour.blurple(),
    )

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view
