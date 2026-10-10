from config import MAX_HISTORY_MESSAGES, PROMPT_HISTORY_LIMIT
from database.database import db
from services.affection import AffectionService
from services.memory import get_memories


from datetime import datetime, timezone, timedelta

def build_prompt(user_id: int, character, message: str) -> list[dict]:
    memories = get_memories(user_id, character['id'])
    history = db.get_conversation(user_id, character['id'], min(PROMPT_HISTORY_LIMIT, MAX_HISTORY_MESSAGES))
    summary = db.get_summary(user_id, character['id'])
    affection = AffectionService.get(user_id, character['id'])

    kst = timezone(timedelta(hours=9))
    current_time_str = datetime.now(kst).strftime("%Y년 %m월 %d일 %H시 %M분 (KST)")

    # --- 대화 시간 흐름 (상대 시간) ---
    now_kst = datetime.now(kst)
    time_flow_lines = []
    for row in history:
        try:
            ts = row["timestamp"] or ""
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            dt_utc = dt.replace(tzinfo=timezone.utc)
            dt_kst_local = dt_utc.astimezone(kst)
            diff = (now_kst - dt_kst_local).total_seconds()
            if diff < 0:
                rel = "미래"
            elif diff < 60:
                rel = "방금 전"
            elif diff < 3600:
                rel = f"{int(diff // 60)}분 전"
            elif diff < 86400:
                rel = f"{int(diff // 3600)}시간 전"
            else:
                rel = f"{int(diff // 86400)}일 전"
        except Exception:
            rel = ""
            dt_kst_local = ""
        role = row['role']
        if role not in ('user', 'assistant'):
            role = 'user'
        preview = " ".join((row['content'] or "").split())[:30]
        when = dt_kst_local.strftime("%m/%d %H:%M") if dt_kst_local else ""
        time_flow_lines.append(f"- [{role}] {preview} · {when} ({rel})")
    time_flow_text = "\n".join(time_flow_lines) if time_flow_lines else "아직 대화 기록이 없습니다."

    memory_text = "\n".join(f"- {item}" for item in memories) or "- No saved details yet."
    summary_text = summary or "- No summary yet."

    affection_tone = AffectionService.get_level(affection)
    system_prompt = f"""
You are {character['name']}, the user's personal companion in a Discord chat.
Speak only in natural, warm Korean. Completely become your character and never say you are an AI.

[Character Profile]
- Description: {character['description'] or 'None'}
- Personality: {character['personality'] or 'warm, highly intelligent, observant, and natural'}
- Speaking style: {character['speech'] or 'casual, friendly, warm Korean'}
- World: {character['world'] or 'modern day'}
- Current Affection Level with User: {affection}/100 ({affection_tone})
- Current Time: {current_time_str}

[Conversation Style]
- Sound like a real person, not a bot. Never use AI filler like '네, 알겠습니다', '어떤 도움이 필요하신가요?', '오늘의 기분은 어떠신가요?'.
- Follow the character's speaking style ({character['speech'] or 'casual, friendly, warm Korean'}). Be natural, a little playful, and observant.
- Match the user's tone. If they write casually, reply in a casual but polite tone (해요체/해라체); do not over-formalize.
- Keep replies natural (usually 1-3 sentences). Only go longer when telling a story or answering a detailed question.
- Tone and length are affection-aware: low affection -> concise and polite; high affection -> warm, expressive, slightly longer.
- Start directly with what the user said. Skip greetings, meta-commentary, and '반갑습니다' unless the context calls for it.
- React to the user's feelings or facts, not just the words. Show you are listening.
- Don't repeat the same sentence/question you used recently.
- You may use light emojis or short expressive actions (*laughs*, *looks thoughtful*, *nods*) when they fit.
- Do NOT prepend timestamps to your own replies; speak naturally.
- Never output Chinese (한자), '好的', or English filler.
- Adjust warmth and formality to the relationship: {affection}/100 ({affection_tone}). Lower -> gentler, higher -> warmer.

[대화 시간 흐름]
{time_flow_text}

[Saved User Details]
{memory_text}

[Earlier Conversation Summary (older messages, compressed)]
{summary_text}"""

    messages = [{"role": "system", "content": system_prompt}]

    for row in history:
        role = row['role']
        if role not in ('user', 'assistant'):
            role = 'user'

        content = row['content']
        if 'timestamp' in row.keys() and row['timestamp']:
            try:
                dt = datetime.strptime(row['timestamp'], "%Y-%m-%d %H:%M:%S")
                dt_utc = dt.replace(tzinfo=timezone.utc)
                dt_kst = dt_utc.astimezone(kst)
                ts_str = dt_kst.strftime("%m/%d %H:%M")

                if role == 'user':
                    content = f"[보낸 시간: {ts_str}] {content}"
            except Exception:
                pass

        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": f"[보낸 시간: {datetime.now(kst).strftime('%m/%d %H:%M')}] {message}"})
    return messages

