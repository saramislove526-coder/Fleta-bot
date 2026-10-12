import asyncio
import os
import re
import requests
import random

from config import (
    AUTO_WEB_SEARCH,
    AI_PROVIDER,
    GROQ_API_URL,
    GROQ_MODEL,
    HUGGINGFACE_API_URL,
    HUGGINGFACE_MODEL,
    HUGGINGFACE_VISION_MODEL,
    NVIDIA_API_URL,
    NVIDIA_MODEL,
    OPENAI_API_URL,
    OPENAI_MODEL,
    UPSTAGE_API_URL,
    UPSTAGE_MODEL,
    SUMMARY_KEEP_RECENT,
    SUMMARY_TRIGGER_COUNT,
    MAX_RESPONSE_TOKENS,
    RESPONSE_TEMPERATURE,
)
from database.database import db
from services.affection import AffectionService
from services.memory import remember_message, save_memory
from services.prompt_builder import build_prompt
from services.summarizer import extract_memory
from services.web_search import needs_search, search_web
from utils.helpers import sanitize_mentions


import logging
import time

log = logging.getLogger(__name__)

# 전역 프로바이더 교대(Round-Robin) 및 쿨다운 관리
_PROVIDER_POOL = ["upstage", "openai", "nvidia", "groq", "huggingface"]
# 프로바이더별 필수 API 키 환경변수 (키가 없으면 아예 시도하지 않음)
_PROVIDER_ENV = {
    "upstage": "UPSTAGE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "huggingface": "HF_TOKEN",
}
_provider_rr_index = 0
_provider_cooldowns: dict[str, float] = {}

# 모델 삭제·크레딧 소진 등 재시도해도 스스로 해결되지 않는 오류의 쿨다운(초)
_CONFIG_COOLDOWN_SECONDS = 600.0


class AIServiceError(RuntimeError):
    pass


class AIRateLimitError(AIServiceError):
    """토큰 및 요청 한도 초과 예외"""
    pass


class AIConfigError(AIServiceError):
    """API 키 누락, 모델 삭제, 크레딧 소진 등 반복 시도로 해결되지 않는 오류"""
    pass


def _is_rate_limit_error(status_code: int, response_text: str) -> bool:
    if status_code in (429, 413, 503):
        return True
    text_lower = response_text.lower()
    return any(kw in text_lower for kw in ["rate limit", "quota", "too many requests", "tokens_per_minute", "exceeded"])


def clean_chinese_text(text: str) -> str:
    """중국어식 문장부호를 정상적인 한국어로 다듬습니다. (사자성어 등 한자 자체는 보존)"""
    punct_map = str.maketrans({
        "，": ", ", "！": "!", "？": "?", "：": ":", "；": ";",
        "（": "(", "）": ")", "“": '"', "”": '"', "『": '"', "』": '"',
        "《": "<", "》": ">"
    })
    text = text.translate(punct_map)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text


def _single_api_call(
    provider: str,
    messages: list[dict],
    image_urls: list[str] | None = None,
    max_tokens: int = 500,
    temperature: float = 0.85,
) -> str:
    if provider == "upstage":
        token = os.getenv("UPSTAGE_API_KEY")
        api_url = UPSTAGE_API_URL
        model = UPSTAGE_MODEL
        token_name = "UPSTAGE_API_KEY"
    elif provider == "openai":
        token = os.getenv("OPENAI_API_KEY")
        api_url = OPENAI_API_URL
        model = OPENAI_MODEL
        token_name = "OPENAI_API_KEY"
    elif provider == "nvidia":
        token = os.getenv("NVIDIA_API_KEY")
        api_url = NVIDIA_API_URL
        model = NVIDIA_MODEL
        token_name = "NVIDIA_API_KEY"
    elif provider == "groq":
        token = os.getenv("GROQ_API_KEY")
        api_url = GROQ_API_URL
        model = GROQ_MODEL
        token_name = "GROQ_API_KEY"
    elif provider == "huggingface":
        token = os.getenv("HF_TOKEN")
        api_url = HUGGINGFACE_API_URL
        model = HUGGINGFACE_MODEL
        token_name = "HF_TOKEN"
    else:
        raise AIServiceError(f"지원하지 않는 프로바이더입니다: {provider}")

    if not token:
        raise AIConfigError(f"{token_name}이 설정되어 있지 않습니다.")

    image_urls = image_urls or []
    
    # 만약 이미지가 있다면, 마지막 사용자 메시지에 이미지를 포함시킵니다.
    if image_urls and messages and messages[-1]["role"] == "user":
        text_content = messages[-1]["content"]
        content_list = [{"type": "text", "text": text_content}]
        content_list.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls[:3])
        messages[-1]["content"] = content_list

    payload = {
        "model": HUGGINGFACE_VISION_MODEL if provider == "huggingface" and image_urls else model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature, # 성격 연기에 적합하도록 기본 0.85
        "top_p": 0.95
    }

    try:
        response = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as err:
        raise AIServiceError(f"{provider} 서버 연결 문제: {err}") from err

    if not response.ok:
        if _is_rate_limit_error(response.status_code, response.text):
            raise AIRateLimitError(f"{provider} 한도/토큰 초과 ({response.status_code}): {response.text[:100]}")
        # 모델 존재 안 함/만료/크레딧 소진/키 무효 → 반복 시도해도 스스로 해결되지 않으므로 장기 쿨다운
        if response.status_code in (401, 402, 403) or any(
            kw in response.text for kw in ("model_not_found", "does not exist", "has reached its end of life")
        ):
            raise AIConfigError(f"{provider} 모델/크레딧 오류 ({response.status_code}): {response.text[:160]}")
        raise AIServiceError(f"{provider} API 오류 ({response.status_code}): {response.text[:160]}")

    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise AIServiceError(f"{provider} 응답 파싱 실패") from error

    if not text.strip():
        raise AIServiceError(f"{provider} 빈 응답")
    return text


def _request_generation(
    messages: list[dict],
    image_urls: list[str] | None = None,
    max_tokens: int = MAX_RESPONSE_TOKENS,
    temperature: float = RESPONSE_TEMPERATURE,
) -> str:
    global _provider_rr_index
    now = time.time()

    # 0. API 키가 설정된 프로바이더만 후보로 삼는다 (키 없이 시도하면 불필요한 지연만 발생)
    configured = [p for p in _PROVIDER_POOL if os.getenv(_PROVIDER_ENV.get(p, ""))]
    if not configured:
        raise AIServiceError(
            "사용 가능한 AI 프로바이더가 없습니다. .env에 UPSTAGE_API_KEY/OPENAI_API_KEY/NVIDIA_API_KEY/GROQ_API_KEY 중 하나를 설정해 주세요."
        )

    # 1. 쿨다운이 만료된 사용 가능 프로바이더 필터링
    available = [p for p in configured if _provider_cooldowns.get(p, 0) <= now]
    if not available:
        log.warning("모든 AI 프로바이더가 쿨다운 중입니다. 가장 먼저 해제될 프로바이더를 사용합니다.")
        available = sorted(configured, key=lambda p: _provider_cooldowns.get(p, 0))

    # 2. 지정된 AI_PROVIDER가 가용 상태라면 최우선 사용, 그 외는 라운드로빈 정렬
    if AI_PROVIDER in available:
        others = [p for p in available if p != AI_PROVIDER]
        start_idx = _provider_rr_index % len(others) if others else 0
        ordered_providers = [AI_PROVIDER] + others[start_idx:] + others[:start_idx]
    else:
        start_idx = _provider_rr_index % len(available)
        ordered_providers = available[start_idx:] + available[:start_idx]
    _provider_rr_index += 1

    errors: list[str] = []
    for provider in ordered_providers:
        try:
            # list 깊은 복사를 통해 여러 번 재시도 시 원본 메시지가 훼손되지 않도록 방지
            import copy
            raw_text = _single_api_call(provider, copy.deepcopy(messages), image_urls, max_tokens, temperature)
            cleaned = re.sub(r"<think>.*?</think>\s*", "", raw_text, flags=re.DOTALL).strip()
            cleaned = clean_chinese_text(cleaned)
            cleaned = sanitize_mentions(cleaned)
            if cleaned:
                log.info("AI 응답 성공 (프로바이더: %s)", provider)
                return cleaned
        except AIRateLimitError as rle:
            log.warning("프로바이더 [%s] 토큰/요청 한도 초과! 60초간 쿨다운 등록: %s", provider, rle)
            _provider_cooldowns[provider] = time.time() + 60.0
            errors.append(f"{provider}: {rle}")
            continue
        except AIConfigError as cfg_err:
            log.warning(
                "프로바이더 [%s] 설정/크레딧 오류! %.0f분간 쿨다운 등록: %s",
                provider, _CONFIG_COOLDOWN_SECONDS / 60, cfg_err,
            )
            _provider_cooldowns[provider] = time.time() + _CONFIG_COOLDOWN_SECONDS
            errors.append(f"{provider}: {cfg_err}")
            continue
        except Exception as err:
            log.warning("프로바이더 [%s] 오류 발생, 다른 프로바이더로 교체: %s", provider, err)
            errors.append(f"{provider}: {err}")
            continue

    raise AIServiceError("모든 AI 프로바이더 접속에 실패했습니다: " + " | ".join(errors))


def _summarize_conversation(user_id: int, character_id: int) -> None:
    """대화가 임계치를 넘으면 오래된 기록을 AI로 요약해 저장하고 원본은 정리한다.

    이렇게 하면 프롬프트가 항상 "누적 요약 + 최근 대화" 구조가 되어
    토큰을 절약하면서도 오래된 맥락을 유지할 수 있다.
    """
    total = db.count_conversations(user_id, character_id)
    if total < SUMMARY_TRIGGER_COUNT:
        return

    rows = db.get_conversations_for_summary(user_id, character_id, SUMMARY_KEEP_RECENT)
    if not rows:
        return

    transcript = "\n".join(f"{row['role']}: {row['content'][:400]}" for row in rows)[:6000]
    previous_summary = db.get_summary(user_id, character_id)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a conversation archiver for a Korean character chat app. "
                "Compress the given chat log into concise Korean bullet-point notes covering: "
                "key facts about the user, emotional beats, promises or plans, and unresolved topics. "
                "Use at most 12 bullets starting with '- '. Output the bullets only, no preamble."
            ),
        },
        {
            "role": "user",
            "content": (
                f"[기존 누적 요약]\n{previous_summary or '없음'}\n\n"
                f"[새 대화 기록]\n{transcript}\n\n"
                "위 내용을 기존 요약과 합쳐 하나의 누적 요약으로 정리해 주세요."
            ),
        },
    ]

    try:
        summary = _request_generation(messages, max_tokens=800, temperature=0.3)
    except Exception as err:
        log.warning("대화 요약 생성 실패, 이번 턴은 건너뜀: %s", err)
        return

    summary = " ".join(summary.split()).strip()
    if not summary:
        log.warning("대화 요약이 비어 있어 건너뜀")
        return

    # 기존 누적 요약을 다시 붙여넣지 않고, LLM이 만든 통합 요약만 저장한다.
    # 중복 저장은 요약을 계속 불려 토큰 낭비와 요약 품질 저하를 유발한다.
    db.set_summary(user_id, character_id, summary[:2000])
    db.delete_oldest_conversations(user_id, character_id, SUMMARY_KEEP_RECENT)
    log.info(
        "대화 요약 완료 (user=%s, character=%s): %d통 요약, 잔여 %d통",
        user_id, character_id, len(rows), SUMMARY_KEEP_RECENT,
    )


def _ai_affection_delta(user_id: int, character, user_message: str) -> int | None:
    """
    AI 감정 평가: 유저의 최신 메시지가 캐릭터의 호감도에 주는 영향을 -5 ~ +5 정수로 판정한다.
    칭찬/감사/애정/자기 개방/성의/유머는 상승, 무례함/모욕/냉담함은 하락.
    키워드 매칭 없이 맥락과 뉘앙스를 이해하며, 실패 시 None(키워드 폴백).
    """
    try:
        context_rows = db.get_conversation(user_id, character["id"], 4)
        context_text = "\n".join(
            f"{row['role']}: {row['content'][:150]}" for row in context_rows
        )
    except Exception:
        context_text = ""

    messages = [
        {"role": "system", "content": (
            f"You are the affection scorer for a Korean AI companion chat. "
            f"The companion's name is {character['name']}. Rate how strongly the user's latest message "
            "would warm up or please this companion, weighing praise, gratitude, affection, sincere "
            "self-disclosure, effort, humor, teasing, rudeness, and insults. "
            "Reply with ONLY a single integer from -5 to +5 (0 = neutral small talk). No other text."
        )},
        {"role": "user", "content": (
            (f"[최근 대화]\n{context_text}\n\n" if context_text else "")
            + f"[유저의 새 메시지]\n{user_message[:500]}"
        )},
    ]
    try:
        raw = _request_generation(messages, max_tokens=8, temperature=0.0)
        match = re.search(r"-?\d+", raw)
        if not match:
            return None
        return max(-5, min(5, int(match.group(0))))
    except Exception:
        return None


async def generate_response(user_id: int, guild_id: int | None, message: str, image_urls: list[str] | None = None) -> str:
    del guild_id
    character = db.get_selected_character(user_id)
    if not character:
        raise AIServiceError("먼저 `/character create`로 캐릭터를 만들고 `/character select`로 선택해 주세요. 선택 후에는 채팅을 바로 보내면 대화할 수 있습니다.")
    original_message = message
    if memory := extract_memory(original_message):
        save_memory(user_id, character["id"], memory)
    remember_message(user_id, character["id"], original_message)

    # 장기 대화는 자동 요약하여 컨텍스트 창을 유지 (임계치 미만이면 즉시 반환)
    await asyncio.to_thread(_summarize_conversation, user_id, character["id"])

    sources = []
    if AUTO_WEB_SEARCH and needs_search(original_message):
        search_result = await asyncio.to_thread(search_web, original_message)
        if search_result:
            search_context, sources = search_result
            message = f"{original_message}\n\n[웹 검색 결과 - 이 정보에 근거해 답하고, 확실하지 않으면 모른다고 말해]\n{search_context}"

    # --- 호감도 평가: AI 감정 분석을 본 응답 생성과 병렬 실행 (응답 지연 없음) ---
    can_evaluate = AffectionService.check_cooldown(user_id, character["id"])
    # 비용/토큰 절감을 위해 AI 평가는 25% 확률로만 수행하고, 나머지는 키워드 평가로 대체합니다.
    use_ai_eval = can_evaluate and random.random() < 0.25

    eval_coro = asyncio.to_thread(_ai_affection_delta, user_id, character, original_message) if use_ai_eval else None
    gen_coro = asyncio.to_thread(_request_generation, build_prompt(user_id, character, message), image_urls)
    
    if use_ai_eval:
        response, ai_delta = await asyncio.gather(gen_coro, eval_coro)
    else:
        response = await gen_coro
        ai_delta = None

    if can_evaluate:
        if ai_delta is not None:
            delta = ai_delta
            reasons = [f"AI 감정 평가 ({ai_delta:+d})"]
        else:
            delta = AffectionService.evaluate_keywords(user_id, character["id"], original_message)
            reasons = [f"키워드 평가 ({delta:+d})"]
        if AffectionService.is_first_greeting_today(user_id, character["id"]):
            delta += 2
            reasons.append("오늘의 첫 인사 (+2)")
    else:
        delta, reasons = 0, ["도배 방지 쿨다운"]
    affection_result = AffectionService.apply_delta(user_id, character["id"], delta, reasons)

    full_response = response
    if sources:
        links = "\n".join(f"- [{title}]({url})" for title, url in sources)
        full_response = f"{full_response}\n\n🔎 참고한 검색 결과:\n{links}"
    full_response = sanitize_mentions(full_response)
    db.add_conversation(user_id, character["id"], "user", original_message)
    # 레벨 알림/검색 링크가 히스토리에 저장되면 AI가 자기 말로 착각하므로 순수 응답만 저장
    db.add_conversation(user_id, character["id"], "assistant", response)
    # 레벨 알림은 텍스트 대신 Components V2 상황 카드(events.py)로 전송되므로 결과를 그대로 반환
    affection_result["character_name"] = character["name"]
    affection_result["avatar"] = character["avatar"]
    return full_response[:1900], affection_result
