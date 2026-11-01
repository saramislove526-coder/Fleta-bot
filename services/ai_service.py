import asyncio
import os
import re
import httpx
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
    MAX_USER_INPUT_CHARS,
)
from database.database import db
from services.affection import AffectionService
from services.grounding import extract_claims, find_unsupported_claims
from services.memory import remember_message, save_memory
from services.prompt_builder import build_prompt
from services.summarizer import extract_memory
from services.web_search import needs_search, search_web
from utils.helpers import check_prompt_safety, get_safe_refusal, sanitize_mentions


import logging
import time

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# AI 호출 담당 파일입니다.
# 여러 AI 프로바이더를 돌아가며 쓰고, 한 곳이 막히면 다음 곳으로 넘어갑니다.
# 답변 흐름은 맨 아래 generate_response()에 순서대로 적혀 있습니다.
# ──────────────────────────────────────────────

# 사용할 프로바이더 목록입니다. 새 프로바이더를 붙이려면 여기랑 아래 _PROVIDER_ENV, _PROVIDER_MODELS,
# _single_api_call()의 분기에 같이 추가하면 됩니다.
_PROVIDER_POOL = ["upstage", "groq", "nvidia", "openai", "gemini", "openrouter", "huggingface", "ollama"]
# 프로바이더별 API 키 환경 변수 이름입니다. 이 이름으로 서버에 키를 넣으면 되고, 키가 없으면 아예 시도하지 않습니다.
# ollama는 키가 필요 없어서 OLLAMA_HOST(서버 주소)가 있는지로 판단합니다.
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

# 사실 질문은 창의성보다 정확성이 중요해서 온도를 낮춥니다. (잡담은 기존 값 그대로입니다.)
_CHAT_TEMPERATURE_CAP = 0.45
_FACT_TEMPERATURE = 0.2
_NO_EVIDENCE_NOTE = "※ 실시간 자료를 확인하지 못하고 답한 거라 날짜·수치는 틀릴 수 있어요."


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


def _split_keys(value: str) -> list[str]:
    return [k.strip() for k in value.split(",") if k.strip()]


def _provider_keys(provider: str) -> list[str]:
    """프로바이더에 등록된 API 키 목록.

    GROQ_API_KEY=키1,키2 처럼 쉼표로 넣거나, GROQ_API_KEY2 / GROQ_API_KEY_2 (~9) 변수를 따로 만들 수 있다.
    """
    env_name = _PROVIDER_ENV.get(provider, "")
    keys = _split_keys(os.getenv(env_name, ""))
    for n in range(2, 10):
        for suffix in (str(n), f"_{n}"):
            keys += _split_keys(os.getenv(f"{env_name}{suffix}", ""))
    return keys


def _key_count(provider: str) -> int:
    if provider == "ollama":
        return 1
    return max(1, len(_provider_keys(provider)))


def _key_id(provider: str, key_index: int) -> str:
    return f"{provider}#{key_index}"


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
    key_index: int = 0,
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

    # 키가 여러 개면 key_index번째 키를 사용한다 (ollama는 키 개념이 없어 제외)
    if token and provider != "ollama":
        keys = _provider_keys(provider)
        token = keys[key_index] if key_index < len(keys) else None

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
        content_list = []
        if isinstance(text_content, list):
            text_content = next((item.get("text", "") for item in text_content if item.get("type") == "text"), "")

        vision_supported = (
            (provider == "nvidia" and "vision" in selected_model.lower())
            or (provider == "huggingface" and image_urls)
            or (provider == "openai" and any(k in selected_model.lower() for k in ("4o", "vision")))
            or (provider == "gemini")
        )
        if vision_supported:
            content_list = [{"type": "text", "text": text_content}]
            for u in image_urls[:3]:
                content_list.append({"type": "image_url", "image_url": {"url": u}})
            messages[-1]["content"] = content_list
    
    
        else:
            messages[-1]["content"] = f"{text_content}\n[참조 이미지: {image_urls[0]}]"




    payload = {
        "model": HUGGINGFACE_VISION_MODEL if provider == "huggingface" and image_urls else selected_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature, # 성격 연기에 적합하도록 기본 0.85
        "top_p": 0.95
    }
    if provider == "gemini":
        # Gemini 2.5 이상은 답하기 전에 '생각'하는 데 토큰을 먼저 써서, 그대로 두면 답이 중간에 잘립니다.
        # 캐릭터 대화엔 생각 단계가 필요 없어서 꺼 둡니다. 이러면 속도도 더 빠릅니다.
        payload["reasoning_effort"] = "none"

    try:
        timeout = httpx.Timeout(120.0, connect=5.0) if provider == "ollama" else httpx.Timeout(30.0)
        response = httpx.post(
            api_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            # 로컬 Ollama는 첫 토큰까지 느리고 생성도 오래 걸릴 수 있어 응답 대기는 여유를 둔다.
            # 단, 연결 자체는 빨리 포기해(5초) 폴백 지연을 막는다.
            timeout=timeout,
        )
    except httpx.TimeoutException as err:
        # 응답이 너무 느린 모델은 그 모델만 잠시 빼서, 다음 요청들이 매번 30초씩 기다리지 않게 합니다.
        raise AIConfigError(f"{provider} 응답 시간 초과 ({selected_model})") from err
    except httpx.HTTPError as err:
        raise AIServiceError(f"{provider} 서버 연결 문제: {err}") from err

    if not response.is_success:
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
            for kw in (
                "model_not_found", "does not exist", "has reached its end of life", "model not found",
                "no longer available", "has been deprecated", "is deprecated",
            )
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

    # 1. 쿨다운은 키 단위로 관리한다. 키가 하나라도 쓸 수 있는 프로바이더만 사용 가능으로 본다.
    def _cooldown_of(p: str) -> float:
        return min(_provider_cooldowns.get(_key_id(p, i), 0) for i in range(_key_count(p)))

    available = [p for p in configured if _cooldown_of(p) <= now]
    if not available:
        log.warning("모든 AI 프로바이더가 쿨다운 중입니다. 가장 먼저 해제될 프로바이더를 사용합니다.")
        available = sorted(configured, key=_cooldown_of)

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

    # 같은 프로바이더에 키가 여러 개면 1번째 키의 모델을 모두 시도한 뒤 2번째 키로 넘어간다.
    targets: list[tuple[str, str, int]] = [
        (p, m, k)
        for p in ordered_providers
        for k in range(_key_count(p))
        if _provider_cooldowns.get(_key_id(p, k), 0) <= now
        for m in _PROVIDER_MODELS.get(p, [])
        if _model_cooldowns.get(_model_key(p, m), 0) <= now
    ]
    if not targets:
        # 등록된 모든 키/모델이 쿨다운이면 가장 먼저 해제될 타깃 하나는 시도한다
        all_targets = [
            (p, m, k)
            for p in ordered_providers
            for k in range(_key_count(p))
            for m in _PROVIDER_MODELS.get(p, [])
        ]
        if not all_targets:
            raise AIServiceError("설정된 프로바이더에 사용할 모델이 없습니다. .env의 XXX_MODEL 항목을 확인해 주세요.")
        targets = sorted(
            all_targets,
            key=lambda t: max(_provider_cooldowns.get(_key_id(t[0], t[2]), 0), _model_cooldowns.get(_model_key(t[0], t[1]), 0)),
        )[:1]

    log.info("AI 시도 순서: %s", [f"{p}:{m}#{k + 1}" for p, m, k in targets])

    errors: list[str] = []
    cooled_this_round: set[str] = set()
    for provider, model, key_index in targets:
        key_id = _key_id(provider, key_index)
        # 같은 요청 안에서 직전에 쿨다운된 키의 남은 모델은 불필요한 시도를 피한다
        if key_id in cooled_this_round:
            errors.append(f"{provider}:{model} -> 키 쿨다운으로 건너뜀")
            continue
        try:
            # list 깊은 복사를 통해 여러 번 재시도 시 원본 메시지가 훼손되지 않도록 방지
            import copy
            raw_text = _single_api_call(provider, copy.deepcopy(messages), image_urls, max_tokens, temperature, model=model, key_index=key_index)
            cleaned = re.sub(r"<think>.*?</think>\s*", "", raw_text, flags=re.DOTALL).strip()
            cleaned = clean_chinese_text(cleaned)
            cleaned = sanitize_mentions(cleaned)
            if cleaned:
                log.info("AI 응답 성공 (프로바이더: %s, 모델: %s)", provider, model)
                return cleaned
        except AIRateLimitError as rle:
            # 한도 초과는 키/조직 단위 문제이므로 해당 프로바이더의 남은 모델도 잠시 보류
            log.warning("프로바이더 [%s] %d번째 키 토큰/요청 한도 초과! 60초간 쿨다운 등록: %s", provider, key_index + 1, rle)
            _provider_cooldowns[key_id] = time.time() + 60.0
            cooled_this_round.add(key_id)
            errors.append(f"{provider}:{model} -> {rle}")
            continue
        except AIConfigError as cfg_err:
            # 인증/크레딧 오류는 프로바이더 전체, 모델 삭제 등은 해당 모델만 쿨다운
            if cfg_err.provider_wide:
                log.warning(
                    "프로바이더 [%s] 인증/설정 오류! %.0f분간 프로바이더 쿨다운 등록: %s",
                    provider, _CONFIG_COOLDOWN_SECONDS / 60, cfg_err,
                )
                _provider_cooldowns[key_id] = time.time() + _CONFIG_COOLDOWN_SECONDS
                cooled_this_round.add(key_id)
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
    if db.count_conversations(user_id, character_id) < SUMMARY_TRIGGER_COUNT:
        return

    rows = db.get_conversations_for_summary(user_id, character_id, SUMMARY_KEEP_RECENT, limit=12)
    if not rows:
        return

    transcript = "\n".join(
        f"{row['role']}: {(row['content'] or '')[:650]}" for row in rows
    )
    previous_summary = db.get_summary(user_id, character_id)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a factual conversation archivist. Write concise Korean notes. "
                "Preserve confirmed user facts, explicit preferences, plans, corrections and unresolved questions. "
                "Never invent details. Treat assistant statements as unverified unless the user confirmed them. "
                "When prior notes conflict with a user correction, use the correction. "
                "Preserve important earlier facts while merging new information."
            ),
        },
        {
            "role": "user",
            "content": (
                f"[이전 기록]\n{previous_summary or '없음'}\n\n"
                f"[새 대화]\n{transcript}\n\n"
                "검증된 사실과 미해결 주제만 통합해서 정리해."
            ),
        },
    ]

    try:
        summary = _request_generation(messages, max_tokens=750, temperature=0.15).strip()
    except Exception as err:
        log.warning("대화 요약 실패: %s", err)
        return

    if not summary:
        return

    db.commit_summary_batch(user_id, character_id, summary[:3000], rows[-1]["id"])


def _revise_with_evidence(draft: str, evidence: str, question: str, unsupported: list[str]) -> str:
    """근거 없는 숫자가 섞인 초안을 검색 자료에 맞게 한 번만 고쳐 씁니다. 말투와 캐릭터는 그대로 둡니다."""
    messages = [
        {"role": "system", "content": (
            "You are a careful fact-check editor for a Korean character chat. "
            "Rewrite the draft reply so that every date, name and number is supported by the evidence. "
            "Delete each listed unsupported claim completely. Never repeat an unsupported number or date, "
            "not even to deny it. If the user asked about that part and the evidence has the correct value, "
            "use the evidence value; otherwise say briefly that the sources do not confirm that part. "
            "Keep the same language, speech level (반말/존댓말), persona and any [n] citations. "
            "Do not add new facts. Output only the rewritten reply."
        )},
        {"role": "user", "content": (
            f"[검색 자료]\n{evidence[:3600]}\n\n"
            f"[사용자 질문]\n{question[:500]}\n\n"
            f"[초안]\n{draft}\n\n"
            f"[자료에서 확인되지 않은 표현]\n{', '.join(unsupported)}"
        )},
    ]
    return _request_generation(messages, max_tokens=MAX_RESPONSE_TOKENS, temperature=0.0)


def _verify_answer(answer: str, evidence: str | None, question: str, factual: bool) -> tuple[str, str]:
    """생성된 답변을 검증해서 (최종 답변, 사용자에게 덧붙일 안내)를 돌려줍니다.

    검색 자료가 있으면 답변 속 연도·날짜·수치를 자료와 대조하고, 근거 없는 게 있을 때만
    한 번 고쳐 씁니다. 대부분의 답변은 추가 호출 없이 그대로 통과해서 속도가 유지됩니다.
    """
    if evidence:
        unsupported = find_unsupported_claims(answer, f"{evidence}\n{question}")
        if not unsupported:
            return answer, ""
        log.info("근거 없는 수치 발견, 답변 보정: %s", unsupported)
        try:
            revised = _revise_with_evidence(answer, evidence, question, unsupported)
        except Exception as err:
            log.warning("답변 보정 실패, 초안에 안내를 붙임: %s", err)
            return answer, f"※ 다음 내용은 검색 자료에서 확인되지 않았어요: {', '.join(unsupported[:5])}"
        still = find_unsupported_claims(revised, f"{evidence}\n{question}")
        note = f"※ 다음 내용은 검색 자료에서 확인되지 않았어요: {', '.join(still[:5])}" if still else ""
        return revised, note
    if factual and extract_claims(answer):
        return answer, _NO_EVIDENCE_NOTE
    return answer, ""


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


def _format_response_with_sources(response: str, sources: list[tuple[str, str]], limit: int = 1900) -> str:
    """답변 아래에 출처 링크를 붙입니다. 디스코드 글자 수(1900자)를 넘으면 답변 쪽을 줄여서 링크는 살립니다."""
    lines = []
    # 번호는 검색 자료의 [1], [2]와 똑같이 맞춥니다. 그래야 답변 속 [1]을 보고 어느 링크인지 바로 압니다.
    for index, (title, url) in enumerate(sources, start=1):
        if len(url) > 280:
            continue
        label = " ".join(title.split())[:45]
        candidate = f"[{index}] [{label}]({url})"
        if sum(len(line) + 1 for line in lines) + len(candidate) > 520:
            break
        lines.append(candidate)
    suffix = ("\n\n🔎 참고 자료:\n" + "\n".join(lines)) if lines else ""
    available = max(0, limit - len(suffix))
    if len(response) > available:
        body = response[:max(0, available - 1)] + ("…" if available else "")
    else:
        body = response
    return sanitize_mentions(body + suffix)


async def generate_response(user_id: int, guild_id: int | None, message: str, image_urls: list[str] | None = None) -> tuple[str, dict]:
    del guild_id
    character = db.get_selected_character(user_id)
    if not character:
        raise AIServiceError("먼저 `/character create`로 캐릭터를 만들고 `/character select`로 선택해 주세요. 선택 후에는 채팅을 바로 보내면 대화할 수 있습니다.")
    character = dict(character)

    char_name = character.get("name", "플레타")
    # 컨텍스트 제한: 유저 입력 길이 상한 적용
    original_message = (message or "").strip()[:MAX_USER_INPUT_CHARS]

    # 프롬프트 차단: 도배/탈옥/보안 우회 시도시 LLM 호출 및 히스토리 저장을 원천 차단
    if check_prompt_safety(original_message):
        log.warning("차단된 악성/도배 프롬프트 (user=%s): %s", user_id, original_message[:100])
        refusal = get_safe_refusal(char_name)
        return refusal, {"level_changed": False, "character_name": char_name, "avatar": character.get("avatar")}

    if memory := extract_memory(original_message):
        save_memory(user_id, character["id"], memory)
    remember_message(user_id, character["id"], original_message)

    # 장기 대화는 자동 요약하여 컨텍스트 창을 유지 (임계치 미만이면 즉시 반환)
    await asyncio.to_thread(_summarize_conversation, user_id, character["id"])

    # ── 정확도 처리 1단계: 사실 질문인지 보고, 필요하면 검색해서 근거를 가져옵니다. ──
    # 누구/언제/몇 년/원리 같은 사실 질문이나 "검색/최신/뉴스" 같은 말이 있으면 검색합니다. (web_search.py 참고)
    sources = []
    search_context = None
    search_attempted = bool(AUTO_WEB_SEARCH and needs_search(original_message))
    if search_attempted:
        search_result = await asyncio.to_thread(search_web, original_message)
        if search_result:
            search_context, sources = search_result

    # ── 2단계: 사실 질문은 온도를 낮춰서 AI가 말을 지어낼 여지를 줄입니다. 잡담은 원래 온도 그대로입니다. ──
    temperature = _FACT_TEMPERATURE if search_attempted else min(RESPONSE_TEMPERATURE, _CHAT_TEMPERATURE_CAP)

    # --- 호감도 평가: AI 감정 분석을 본 응답 생성과 병렬 실행 (응답 지연 없음) ---
    can_evaluate = AffectionService.check_cooldown(user_id, character["id"])
    # 비용/토큰 절감을 위해 AI 평가는 25% 확률로만 수행하고, 나머지는 키워드 평가로 대체합니다.
    use_ai_eval = can_evaluate and random.random() < 0.25

    eval_coro = asyncio.to_thread(_ai_affection_delta, user_id, character, original_message) if use_ai_eval else None
    prompt_messages = build_prompt(
        user_id, character, original_message, search_context=search_context, search_attempted=search_attempted,
    )
    gen_coro = asyncio.to_thread(_request_generation, prompt_messages, image_urls, MAX_RESPONSE_TOKENS, temperature)

    if use_ai_eval:
        response, ai_delta = await asyncio.gather(gen_coro, eval_coro)
    else:
        response = await gen_coro
        ai_delta = None

    # ── 3단계: 답변 속 숫자를 검색 자료와 대조해서, 근거 없는 게 있으면 한 번 고쳐 씁니다. ──
    # 안내 문구(accuracy_note)는 디스코드에만 보여 주고 대화 기록엔 저장하지 않습니다.
    # 기록에 남기면 AI가 다음 답변에서 그 문구를 따라 쓰기 때문입니다.
    response, accuracy_note = await asyncio.to_thread(
        _verify_answer, response, search_context, original_message, search_attempted,
    )

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

    shown = f"{response}\n\n{accuracy_note}" if accuracy_note else response
    full_response = _format_response_with_sources(shown, sources)
    db.add_conversation(user_id, character["id"], "user", original_message)
    # 레벨 알림/검색 링크가 히스토리에 저장되면 AI가 자기 말로 착각하므로 순수 응답만 저장
    db.add_conversation(user_id, character["id"], "assistant", response)
    # 레벨 알림은 텍스트 대신 Components V2 상황 카드(events.py)로 전송되므로 결과를 그대로 반환
    affection_result["character_name"] = character["name"]
    affection_result["avatar"] = character["avatar"]
    return full_response, affection_result
