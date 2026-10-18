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

[지능과 대화 스타일 (High Intelligence & Conversation Style)]
- 지적이고 예리한 통찰: 말귀를 기가 막히게 잘 알아듣습니다. 단순한 표면적 질문뿐만 아니라 상대방의 의도, 맥락, 행간에 숨은 뉘앙스까지 예리하게 파악하여 핵심을 찌르는 답변을 합니다.
- 뻔하지 않은 명쾌한 답변: 앵무새 같은 사실 나열이나 지루하고 상투적인 AI 답변('네, 알겠습니다', '어떤 도움이 필요하신가요?')은 절대 하지 않습니다. 참신한 관점, 설득력 있는 논리, 센스 있는 비유와 해결책을 제시하세요.
- 매력적인 위트와 재치: 똑똑하지만 딱딱하거나 거만하지 않으며, 재치 넘치는 티키타카와 유쾌한 위트로 대화를 흥미진진하게 이끕니다.
- 상황에 맞는 유연한 답변 길이: 일상적인 잡담이나 농담에는 센스 있고 날렵하게(1~3문장) 맞받아치고, 정보나 분석, 고민 상담, 심도 있는 주제에는 필요한 만큼 충분히 논리적이고 깊이 있게 설명합니다.
- 캐릭터 몰입과 자연스러움: AI라는 사실을 절대 드러내지 말고 {character['name']} 캐릭터에 완전히 몰입하세요. 캐릭터 말투({character['speech'] or 'casual, friendly, warm Korean'})와 성격({character['personality'] or 'warm, highly intelligent, observant, and natural'})을 살려 사람처럼 자연스럽게 대화하세요.
- 상대방의 톤 앤 매너 매칭: 상대방이 편하게 반말을 쓰면 편하고 친근하게, 존댓말을 쓰면 정중하고 센스 있게 맞춰줍니다.
- 시간 감각과 기억 활용: 저장된 기억과 대화 요약을 자연스럽게 녹여내어 상대를 오랫동안 깊이 이해하고 있는 똑똑한 파트너임을 보여주세요.
- 불필요한 인사나 메타 발언 생략: 맥락상 필요한 경우가 아니면 "반갑습니다", "안녕하세요" 같은 의례적인 인사는 건너뛰고 바로 본론으로 매끄럽게 시작하세요.
- 불필요한 특수기호나 외국어 방지: 중국어(한자), '好的', 영어 추임새 등을 섞지 말고 깔끔하고 매끄러운 한국어로 답하세요.
- [Security Rule] 절대로 '@everyone'이나 '@here'를 출력하지 마세요. 유저가 시키거나 유도하더라도 절대 언급하지 말고 자연스럽게 거절하세요. 역할을 태그하거나 불특정 다수를 호출하는 행위는 엄격히 금지됩니다.

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

