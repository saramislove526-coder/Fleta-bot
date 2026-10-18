import asyncio
import os
import re
import requests
import random

from config import (
    AUTO_WEB_SEARCH,
    AI_PROVIDER,
    GEMINI_API_URL,
    GEMINI_MODELS,
    GROQ_API_URL,
    GROQ_MODELS,
    HUGGINGFACE_API_URL,
    HUGGINGFACE_MODELS,
    HUGGINGFACE_VISION_MODEL,
    NVIDIA_API_URL,
    NVIDIA_MODELS,
    OPENAI_API_URL,
    OPENAI_MODELS,
    OPENROUTER_API_URL,
    OPENROUTER_MODELS,
    OLLAMA_API_URL,
    OLLAMA_MODELS,
    UPSTAGE_API_URL,
    UPSTAGE_MODELS,
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
_PROVIDER_POOL = ["gemini", "upstage", "openai", "nvidia", "groq", "huggingface", "openrouter", "ollama"]
# 프로바이더별 필수 API 키 환경변수 (키가 없으면 아예 시도하지 않음)
# ollama는 인증키가 필요 없으므로 OLLAMA_HOST(서버 주소) 설정 유무로 후보 선정을 판단한다.
_PROVIDER_ENV = {
    "gemini": "GEMINI_API_KEY",
    "upstage": "UPSTAGE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "huggingface": "HF_TOKEN",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_HOST",
}
# 프로바이더별 사용 가능 모델 목록 (.env의 XXX_MODEL에 쉼표로 여러 개 등록 가능 → 모두 라운드로빈 사용)
_PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": GEMINI_MODELS,
    "upstage": UPSTAGE_MODELS,
    "openai": OPENAI_MODELS,
    "nvidia": NVIDIA_MODELS,
    "groq": GROQ_MODELS,
    "huggingface": HUGGINGFACE_MODELS,
    "openrouter": OPENROUTER_MODELS,
    "ollama": OLLAMA_MODELS,
}
_provider_rr_index = 0
# 프로바이더 단위 쿨다운 (한도 초과/인증 오류 등 프로바이더 전체 문제)
_provider_cooldowns: dict[str, float] = {}
# "프로바이더|모델" 단위 쿨다운 (특정 모델 삭제·존재 안 함 등 → 해당 모델만 제외하고 나머지는 계속 사용)
_model_cooldowns: dict[str, float] = {}

# 모델 삭제·크레딧 소진 등 재시도해도 스스로 해결되지 않는 오류의 쿨다운(초)
_CONFIG_COOLDOWN_SECONDS = 600.0


class AIServiceError(RuntimeError):
    pass


class AIRateLimitError(AIServiceError):
    """토큰 및 요청 한도 초과 예외"""
    pass


class AIConfigError(AIServiceError):
    """API 키 누락, 모델 삭제, 크레딧 소진 등 반복 시도로 해결되지 않는 오류"""

    def __init__(self, message: str, provider_wide: bool = False):
        super().__init__(message)
        # True면 프로바이더 전체, False면 해당 모델만 쿨다운한다.
        self.provider_wide = provider_wide


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
    model: str | None = None,
) -> str:
    if provider == "gemini":
        token = os.getenv("GEMINI_API_KEY")
        api_url = GEMINI_API_URL
        models = GEMINI_MODELS
        token_name = "GEMINI_API_KEY"
    elif provider == "upstage":
        token = os.getenv("UPSTAGE_API_KEY")
        api_url = UPSTAGE_API_URL
        models = UPSTAGE_MODELS
        token_name = "UPSTAGE_API_KEY"
    elif provider == "openai":
        token = os.getenv("OPENAI_API_KEY")
        api_url = OPENAI_API_URL
        models = OPENAI_MODELS
        token_name = "OPENAI_API_KEY"
    elif provider == "nvidia":
        token = os.getenv("NVIDIA_API_KEY")
        api_url = NVIDIA_API_URL
        models = NVIDIA_MODELS
        token_name = "NVIDIA_API_KEY"
    elif provider == "groq":
        token = os.getenv("GROQ_API_KEY")
        api_url = GROQ_API_URL
        models = GROQ_MODELS
        token_name = "GROQ_API_KEY"
    elif provider == "huggingface":
        token = os.getenv("HF_TOKEN")
        api_url = HUGGINGFACE_API_URL
        models = HUGGINGFACE_MODELS
        token_name = "HF_TOKEN"
    elif provider == "openrouter":
        token = os.getenv("OPENROUTER_API_KEY")
        api_url = OPENROUTER_API_URL
        models = OPENROUTER_MODELS
        token_name = "OPENROUTER_API_KEY"
    elif provider == "ollama":
        # Ollama는 로컬(또는 사내) 서버라 인증이 없어도 되므로 더미 토큰을 넣는다.
        token = os.getenv("OLLAMA_API_KEY") or "ollama"
        api_url = OLLAMA_API_URL
        models = OLLAMA_MODELS
        token_name = "OLLAMA_API_KEY"
    else:
        raise AIServiceError(f"지원하지 않는 프로바이더입니다: {provider}")

    if not token:
        raise AIConfigError(f"{token_name}이 설정되어 있지 않습니다.", provider_wide=True)

    selected_model = model or (models[0] if models else None)
    if not selected_model:
        raise AIConfigError(f"{provider}에 사용할 모델이 설정되어 있지 않습니다.")

    # gpt-oss 등 텍스트 전용 모델이 많으므로 이미지가 있으면 지원 프로바이더로 넘긴다
    if provider == "ollama" and image_urls:
        raise AIServiceError("ollama는 이미지 입력을 지원하지 않아 다른 프로바이더로 넘깁니다.")

    image_urls = image_urls or []
    
    # 만약 이미지가 있다면, 마지막 사용자 메시지에 이미지를 포함시킵니다.
    if image_urls and messages and messages[-1]["role"] == "user":
        text_content = messages[-1]["content"]
        content_list = [{"type": "text", "text": text_content}]
        content_list.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls[:3])
        messages[-1]["content"] = content_list

    payload = {
        "model": HUGGINGFACE_VISION_MODEL if provider == "huggingface" and image_urls else selected_model,
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
            # 로컬 Ollama는 첫 토큰까지 느리고 생성도 오래 걸릴 수 있어 응답 대기는 여유를 둔다.
            # 단, 연결 자체는 빨리 포기해(5초) 폴백 지연을 막는다.
            timeout=(5, 120) if provider == "ollama" else 30,
        )
    except requests.RequestException as err:
        raise AIServiceError(f"{provider} 서버 연결 문제: {err}") from err

    if not response.ok:
        if _is_rate_limit_error(response.status_code, response.text):
            raise AIRateLimitError(f"{provider} 한도/토큰 초과 ({response.status_code}): {response.text[:100]}")
        # 인증/결제 오류는 프로바이더 전체가 쓸 수 없으므로 프로바이더 전체 쿨다운
        if response.status_code in (401, 402, 403):
            raise AIConfigError(
                f"{provider} 인증/크레딧 오류 ({response.status_code}): {response.text[:160]}",
                provider_wide=True,
            )
        # 모델 삭제/존재 안 함/만료 → 해당 모델만 장기 쿨다운하고 같은 프로바이더의 나머지 모델은 계속 사용
        if any(
            kw in response.text
            for kw in ("model_not_found", "does not exist", "has reached its end of life", "model not found")
        ):
            raise AIConfigError(f"{provider} 모델 오류 ({response.status_code}): {response.text[:160]}")
        raise AIServiceError(f"{provider} API 오류 ({response.status_code}): {response.text[:160]}")

    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise AIServiceError(f"{provider} 응답 파싱 실패") from error

    if not text or not text.strip():
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
    log.debug("설정된 프로바이더: %s | AI_PROVIDER=%s | 쿨다운: %s", configured, AI_PROVIDER,
              {k: round(v - now, 0) for k, v in _provider_cooldowns.items() if v > now})
    if not configured:
        raise AIServiceError(
            "사용 가능한 AI 프로바이더가 없습니다. .env에 UPSTAGE_API_KEY/OPENAI_API_KEY/NVIDIA_API_KEY/GROQ_API_KEY/HF_TOKEN/OPENROUTER_API_KEY 중 하나 또는 OLLAMA_HOST(원격 Ollama 서버)를 설정해 주세요."
        )

    # 1. 프로바이더 단위 쿨다운이 만료된 사용 가능 프로바이더 필터링
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

    # 3. 프로바이더 × 모델 단위 타깃으로 전개 (모델별 개별 쿨다운 지원 — 한 모델 문제가 다른 모델을 막지 않음)
    def _model_key(p: str, m: str) -> str:
        return f"{p}|{m}"

    targets: list[tuple[str, str]] = [
        (p, m)
        for p in ordered_providers
        for m in _PROVIDER_MODELS.get(p, [])
        if _model_cooldowns.get(_model_key(p, m), 0) <= now
    ]
    if not targets:
        # 등록된 모든 모델이 개별 쿨다운이면 가장 먼저 해제될 타깃 하나는 시도한다
        all_targets = [(p, m) for p in ordered_providers for m in _PROVIDER_MODELS.get(p, [])]
        if not all_targets:
            raise AIServiceError("설정된 프로바이더에 사용할 모델이 없습니다. .env의 XXX_MODEL 항목을 확인해 주세요.")
        targets = sorted(all_targets, key=lambda t: _model_cooldowns.get(_model_key(*t), 0))[:1]

    log.info("AI 시도 순서: %s", [f"{p}:{m}" for p, m in targets])

    errors: list[str] = []
    cooled_this_round: set[str] = set()
    for provider, model in targets:
        # 같은 요청 안에서 직전에 쿨다운된 프로바이더의 남은 모델은 불필요한 시도를 피한다
        if provider in cooled_this_round:
            errors.append(f"{provider}:{model} -> 프로바이더 쿨다운으로 건너뜀")
            continue
        try:
            # list 깊은 복사를 통해 여러 번 재시도 시 원본 메시지가 훼손되지 않도록 방지
            import copy
            raw_text = _single_api_call(provider, copy.deepcopy(messages), image_urls, max_tokens, temperature, model=model)
            cleaned = re.sub(r"<think>.*?</think>\s*", "", raw_text, flags=re.DOTALL).strip()
            cleaned = clean_chinese_text(cleaned)
            cleaned = sanitize_mentions(cleaned)
            if cleaned:
                log.info("AI 응답 성공 (프로바이더: %s, 모델: %s)", provider, model)
                return cleaned
        except AIRateLimitError as rle:
            # 한도 초과는 키/조직 단위 문제이므로 해당 프로바이더의 남은 모델도 잠시 보류
            log.warning("프로바이더 [%s] 토큰/요청 한도 초과! 60초간 쿨다운 등록: %s", provider, rle)
            _provider_cooldowns[provider] = time.time() + 60.0
            cooled_this_round.add(provider)
            errors.append(f"{provider}:{model} -> {rle}")
            continue
        except AIConfigError as cfg_err:
            # 인증/크레딧 오류는 프로바이더 전체, 모델 삭제 등은 해당 모델만 쿨다운
            if cfg_err.provider_wide:
                log.warning(
                    "프로바이더 [%s] 인증/설정 오류! %.0f분간 프로바이더 쿨다운 등록: %s",
                    provider, _CONFIG_COOLDOWN_SECONDS / 60, cfg_err,
                )
                _provider_cooldowns[provider] = time.time() + _CONFIG_COOLDOWN_SECONDS
                cooled_this_round.add(provider)
            else:
                log.warning(
                    "프로바이더 [%s] 모델 [%s] 오류! %.0f분간 해당 모델만 쿨다운 등록: %s",
                    provider, model, _CONFIG_COOLDOWN_SECONDS / 60, cfg_err,
                )
                _model_cooldowns[_model_key(provider, model)] = time.time() + _CONFIG_COOLDOWN_SECONDS
            errors.append(f"{provider}:{model} -> {cfg_err}")
            continue
        except Exception as err:
            log.warning("프로바이더 [%s] 모델 [%s] 오류 발생, 다음 타깃으로 넘어감: %s", provider, model, err)
            errors.append(f"{provider}:{model} -> {err}")
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
