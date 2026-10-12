def affection_bar(value: int, width: int = 10) -> str:
    """호감도를 시각적으로 표현하는 진행바 (예: ▰▰▰▰▱▱▱▱▱▱)."""
    value = max(0, min(100, value))
    filled = round(value * width / 100)
    return "▰" * filled + "▱" * (width - filled)
