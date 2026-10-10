def extract_memory(message: str) -> str | None:
    """A user can explicitly persist a fact by starting a phrase with '기억해:'."""
    marker = "기억해:"
    if marker not in message:
        return None
    value = message.split(marker, 1)[1].strip()
    return value[:500] if value else None
