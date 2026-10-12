"""대화가 끊겼을 때 뉴스/이슈를 주제로 캐릭터가 먼저 말을 거는 기능."""
import asyncio
import logging
import random

from database.database import db
from services.ai_service import _request_generation
from services.prompt_builder import build_prompt
from services.web_search import search_web

log = logging.getLogger(__name__)

# 사람들이 흥미로워할 만한 주제 후보 (매번 무작위 선택)
TOPIC_QUERIES = [
    "오늘 대한민국 주요 뉴스",
    "오늘 연예 이슈 화제",
    "어제 오늘 스포츠 경기 결과",
    "신작 게임 출시 소식",
    "IT 신기술 AI 소식",
    "재미있는 과학 소식",
    "요즘 유행하는 것",
]


async def create_topic_starter(user_id: int, character) -> str | None:
    """
    웹 검색으로 화제성 주제를 뽑아 캐릭터가 유저에게 먼저 말을 거는 인사말을 생성한다.
    생성된 말은 대화 기록(assistant)으로 저장된다. 실패 시 None(이번 턴 건너뜀).
    """
    query = random.choice(TOPIC_QUERIES)
    try:
        search_result = await asyncio.to_thread(search_web, query)
    except Exception:
        log.exception("Idle topic search failed")
        search_result = None

    if search_result:
        topic_context, _sources = search_result
        topic_block = f"[참고 주제 - 지금 화제인 소식]\n{topic_context[:700]}"
    else:
        topic_block = "[참고 주제]\n요즘 사람들이 흥미로워할 만한 주제를 하나 골라 이야기를 시작해 주세요."

    instruction = (
        "[시스템 지시] 유저와의 대화가 한동안 이어지지 않았습니다. "
        "아래 주제를 활용해 유저에게 먼저 말을 걸어 주세요.\n"
        "- 뉴스 낭독처럼 읽지 말고 캐릭터의 성격과 말투로 자연스럽게\n"
        "- 1~3문장으로 짧게, 마지막은 유저에게 던지는 가벼운 질문으로\n"
        "- 유저가 최근 관심 있어 했던 것과 연결하면 더 좋음\n\n"
        f"{topic_block}"
    )
    try:
        messages = build_prompt(user_id, character, instruction)
        starter = await asyncio.to_thread(_request_generation, messages)
    except Exception:
        log.exception("Failed to generate idle topic starter")
        return None

    starter = (starter or "").strip()
    if not starter:
        return None
    db.add_conversation(user_id, character["id"], "assistant", starter)
    return starter[:1500]
