import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "bot.db"
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
AI_PROVIDER = os.getenv("AI_PROVIDER", "upstage").lower()

# 한국어 1티어 추천 모델: Upstage Solar Pro (Solar LLM)
UPSTAGE_MODEL = os.getenv("UPSTAGE_MODEL", "solar-pro")
UPSTAGE_API_URL = "https://api.upstage.ai/v1/chat/completions"

# NVIDIA Llama 모델
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-405b-instruct")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# HuggingFace 대체 모델 (기존 c4ai-command-r-plus-08-2024는 라우터에서 삭제됨)
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "CohereLabs/c4ai-command-a-03-2025")
HUGGINGFACE_VISION_MODEL = os.getenv("HUGGINGFACE_VISION_MODEL", "CohereLabs/aya-vision-32b")
HUGGINGFACE_API_URL = os.getenv("HUGGINGFACE_API_URL", "https://router.huggingface.co/v1/chat/completions")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "150"))
PROMPT_HISTORY_LIMIT = int(os.getenv("PROMPT_HISTORY_LIMIT", "20"))
SUMMARY_TRIGGER_COUNT = int(os.getenv("SUMMARY_TRIGGER_COUNT", "50"))
SUMMARY_KEEP_RECENT = int(os.getenv("SUMMARY_KEEP_RECENT", "20"))
MAX_MEMORY_ITEMS = int(os.getenv("MAX_MEMORY_ITEMS", "60"))
MAX_CHARACTER_NAME_LENGTH = 50
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "500"))
RESPONSE_TEMPERATURE = float(os.getenv("RESPONSE_TEMPERATURE", "0.85"))
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
PUBLIC_CHARACTER_CHANNEL_ID = int(os.getenv("PUBLIC_CHARACTER_CHANNEL_ID", "0"))
CHAT_TRIGGER = os.getenv("CHAT_TRIGGER", "플레타")
CONVERSATION_TIMEOUT_SECONDS = int(os.getenv("CONVERSATION_TIMEOUT_SECONDS", "1800"))
AUTO_WEB_SEARCH = os.getenv("AUTO_WEB_SEARCH", "true").lower() == "true"

# 유휴 상태 자동 대화 주제: 대화가 끊기면 뉴스/이슈로 먼저 말 걸기
IDLE_TOPIC_ENABLED = os.getenv("IDLE_TOPIC_ENABLED", "true").lower() == "true"
IDLE_TOPIC_INTERVAL_MINUTES = int(os.getenv("IDLE_TOPIC_INTERVAL_MINUTES", "10"))
IDLE_TOPIC_MIN_IDLE_MINUTES = int(os.getenv("IDLE_TOPIC_MIN_IDLE_MINUTES", "30"))
IDLE_TOPIC_COOLDOWN_MINUTES = int(os.getenv("IDLE_TOPIC_COOLDOWN_MINUTES", "120"))

# 응답 길이·말투/온도 제어
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "800"))
RESPONSE_TEMPERATURE = float(os.getenv("RESPONSE_TEMPERATURE", "0.85"))
