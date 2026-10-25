import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "bot.db"
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
AI_PROVIDER = os.getenv("AI_PROVIDER", "upstage").lower()


def _model_list(value: str) -> list[str]:
    """환경변수 하나에 쉼표 구분으로 여러 모델을 등록할 수 있게 파싱한다."""
    return [m.strip() for m in value.split(",") if m.strip()]


# 한국어 1티어 추천 모델: Upstage Solar Pro (Solar LLM)
UPSTAGE_MODEL = os.getenv("UPSTAGE_MODEL", "solar-pro4,solar-pro")
UPSTAGE_MODELS = _model_list(UPSTAGE_MODEL)
UPSTAGE_API_URL = "https://api.upstage.ai/v1/chat/completions"

# NVIDIA Llama 모델
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-405b-instruct")
NVIDIA_MODELS = _model_list(NVIDIA_MODEL)
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MODELS = _model_list(GROQ_MODEL)
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODELS = _model_list(OPENAI_MODEL)
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# HuggingFace 대체 모델 (기존 c4ai-command-r-plus-08-2024는 라우터에서 삭제됨)
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "CohereLabs/c4ai-command-a-03-2025")
HUGGINGFACE_VISION_MODEL = os.getenv("HUGGINGFACE_VISION_MODEL", "CohereLabs/aya-vision-32b")
HUGGINGFACE_API_URL = os.getenv("HUGGINGFACE_API_URL", "https://router.huggingface.co/v1/chat/completions")
HUGGINGFACE_MODELS = _model_list(HUGGINGFACE_MODEL)

# Google Gemini (공식 OpenAI 호환 엔드포인트 지원)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash,gemini-1.5-flash")
GEMINI_MODELS = _model_list(GEMINI_MODEL)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# OpenRouter (무료 티어 포함 — OPENROUTER_API_KEY가 있어야 후보 프로바이더에 포함됨)
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")
OPENROUTER_MODELS = _model_list(OPENROUTER_MODEL)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Ollama 로컬 LLM 서버 (OpenAI 호환 API) — .env에 OLLAMA_HOST를 설정하면 후보 프로바이더에 포함됨
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_API_URL = f"{OLLAMA_HOST}/v1/chat/completions"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_MODELS = _model_list(OLLAMA_MODEL)
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "100"))
PROMPT_HISTORY_LIMIT = int(os.getenv("PROMPT_HISTORY_LIMIT", "10"))
MAX_USER_INPUT_CHARS = int(os.getenv("MAX_USER_INPUT_CHARS", "500"))
MAX_CONTEXT_TOTAL_CHARS = int(os.getenv("MAX_CONTEXT_TOTAL_CHARS", "4000"))
SUMMARY_TRIGGER_COUNT = int(os.getenv("SUMMARY_TRIGGER_COUNT", "40"))
SUMMARY_KEEP_RECENT = int(os.getenv("SUMMARY_KEEP_RECENT", "10"))
MAX_MEMORY_ITEMS = int(os.getenv("MAX_MEMORY_ITEMS", "30"))
MAX_CHARACTER_NAME_LENGTH = 50
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "700"))
RESPONSE_TEMPERATURE = float(os.getenv("RESPONSE_TEMPERATURE", "0.85"))
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
PUBLIC_CHARACTER_CHANNEL_ID = int(os.getenv("PUBLIC_CHARACTER_CHANNEL_ID", "0"))
CHAT_TRIGGER = os.getenv("CHAT_TRIGGER", "플레타")
CONVERSATION_TIMEOUT_SECONDS = int(os.getenv("CONVERSATION_TIMEOUT_SECONDS", "300"))
AUTO_WEB_SEARCH = os.getenv("AUTO_WEB_SEARCH", "true").lower() == "true"

# 유휴 상태 자동 대화 주제: 기본 비활성화 (도배 방지)
IDLE_TOPIC_ENABLED = os.getenv("IDLE_TOPIC_ENABLED", "false").lower() == "true"
IDLE_TOPIC_INTERVAL_MINUTES = int(os.getenv("IDLE_TOPIC_INTERVAL_MINUTES", "10"))
IDLE_TOPIC_MIN_IDLE_MINUTES = int(os.getenv("IDLE_TOPIC_MIN_IDLE_MINUTES", "30"))
IDLE_TOPIC_COOLDOWN_MINUTES = int(os.getenv("IDLE_TOPIC_COOLDOWN_MINUTES", "120"))
