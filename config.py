import os
from pathlib import Path

# ──────────────────────────────────────────────
# 봇 설정 모음입니다.
# 값은 전부 서버 환경 변수(.env 또는 호스팅 패널)에서 읽어 오고, 없으면 오른쪽 기본값을 씁니다.
# API 키는 여기 코드에 직접 적지 말고 꼭 환경 변수에 넣어야 합니다. (저장소가 공개라 바로 털립니다.)
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "bot.db"  # 대화 기록·호감도가 저장되는 DB 파일 위치입니다.
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# 제일 먼저 써 볼 AI 프로바이더입니다. upstage / groq / nvidia / openai / gemini / openrouter / huggingface / ollama 중에 고르면 됩니다.
# 이 프로바이더가 막히면 나머지 키가 있는 프로바이더로 알아서 돌아가며 넘어갑니다.
AI_PROVIDER = os.getenv("AI_PROVIDER", "upstage").lower()


def _model_list(value: str) -> list[str]:
    """환경변수 하나에 쉼표 구분으로 여러 모델을 등록할 수 있게 파싱합니다."""
    return [m.strip() for m in value.split(",") if m.strip()]


# ──────────────────────────────────────────────
# 프로바이더별 모델 설정입니다.
# - API 키 환경 변수 이름: UPSTAGE_API_KEY, NVIDIA_API_KEY, GROQ_API_KEY, OPENAI_API_KEY,
#   HF_TOKEN, GEMINI_API_KEY, OPENROUTER_API_KEY 입니다. 키가 있는 프로바이더만 사용됩니다.
# - 같은 프로바이더 키가 여러 개면 GROQ_API_KEY=키1,키2 처럼 쉼표로 넣거나
#   GROQ_API_KEY2 변수를 따로 만들면 됩니다. 1번 키가 한도에 걸리면 2번 키로 넘어갑니다.
# - 모델도 XXX_MODEL=모델1,모델2 처럼 쉼표로 여러 개 넣을 수 있고, 앞에 적은 모델부터 씁니다.
# ──────────────────────────────────────────────

# 한국어 1티어 추천 모델: Upstage Solar Pro (Solar LLM)입니다.
UPSTAGE_MODEL = os.getenv("UPSTAGE_MODEL", "solar-pro,solar-mini")
UPSTAGE_MODELS = _model_list(UPSTAGE_MODEL)
UPSTAGE_API_URL = "https://api.upstage.ai/v1/chat/completions"

# NVIDIA Llama 모델입니다. (이름에 vision이 들어간 모델은 이미지도 읽습니다.)
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct,meta/llama-3.2-90b-vision-instruct")
NVIDIA_MODELS = _model_list(NVIDIA_MODEL)
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Groq입니다. 무료 한도가 넉넉하고 응답이 빨라서 예비용으로 좋습니다.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b,openai/gpt-oss-20b")
GROQ_MODELS = _model_list(GROQ_MODEL)
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MODELS = _model_list(OPENAI_MODEL)
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# HuggingFace 대체 모델입니다. (기존 c4ai-command-r-plus-08-2024는 라우터에서 삭제됐습니다.)
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "CohereLabs/c4ai-command-a-03-2025")
HUGGINGFACE_VISION_MODEL = os.getenv("HUGGINGFACE_VISION_MODEL", "CohereLabs/aya-vision-32b")
HUGGINGFACE_API_URL = os.getenv("HUGGINGFACE_API_URL", "https://router.huggingface.co/v1/chat/completions")
HUGGINGFACE_MODELS = _model_list(HUGGINGFACE_MODEL)

# Google Gemini입니다. (OpenAI 호환 주소로 호출합니다.)
# gemini-1.5-flash, gemini-2.0-flash는 구글이 서비스를 종료해서 뺐습니다.
# gemini-3.8-flash는 지금 응답이 30초 넘게 걸려서 일부러 안 넣었습니다. 빨라지면 앞에 추가하면 됩니다.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODELS = _model_list(GEMINI_MODEL)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# OpenRouter입니다. 무료 티어가 있고, OPENROUTER_API_KEY를 넣어야 후보에 들어갑니다.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")
OPENROUTER_MODELS = _model_list(OPENROUTER_MODEL)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Ollama 로컬 LLM 서버입니다. 키 대신 OLLAMA_HOST(서버 주소)를 넣으면 후보에 들어갑니다.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_API_URL = f"{OLLAMA_HOST}/v1/chat/completions"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_MODELS = _model_list(OLLAMA_MODEL)

# ──────────────────────────────────────────────
# 대화 길이·기억 관련 설정입니다. 숫자를 키우면 더 많이 기억하지만 토큰(비용)도 늘어납니다.
# ──────────────────────────────────────────────
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "100"))
PROMPT_HISTORY_LIMIT = int(os.getenv("PROMPT_HISTORY_LIMIT", "30"))
MAX_USER_INPUT_CHARS = int(os.getenv("MAX_USER_INPUT_CHARS", "1500"))  # 사용자가 한 번에 보낼 수 있는 글자 수입니다.
MAX_CONTEXT_TOTAL_CHARS = int(os.getenv("MAX_CONTEXT_TOTAL_CHARS", "12000"))
SUMMARY_TRIGGER_COUNT = int(os.getenv("SUMMARY_TRIGGER_COUNT", "60"))  # 대화가 이만큼 쌓이면 옛날 대화를 요약합니다.
SUMMARY_KEEP_RECENT = int(os.getenv("SUMMARY_KEEP_RECENT", "20"))  # 요약할 때도 최근 대화는 이만큼 원문으로 남깁니다.
MAX_MEMORY_ITEMS = int(os.getenv("MAX_MEMORY_ITEMS", "100"))
KLIPY_API_KEY = os.getenv("KLIPY_API_KEY", "pmpZyPifwSulBfELHCbpaOllUfgsjqt9yeImc2XWIcHSWjnAUBw9oueRf4kD5r25")
MAX_CHARACTER_NAME_LENGTH = 50
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "700"))  # 답변 최대 길이(토큰)입니다.
RESPONSE_TEMPERATURE = float(os.getenv("RESPONSE_TEMPERATURE", "0.85"))  # 잡담 답변의 자유도입니다. 사실 질문은 코드에서 0.2로 낮춥니다.
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
PUBLIC_CHARACTER_CHANNEL_ID = int(os.getenv("PUBLIC_CHARACTER_CHANNEL_ID", "0"))
CHAT_TRIGGER = os.getenv("CHAT_TRIGGER", "플레타")  # 메시지를 이 이름으로 시작하면 봇이 대답합니다.
CONVERSATION_TIMEOUT_SECONDS = int(os.getenv("CONVERSATION_TIMEOUT_SECONDS", "300"))
# 사실 질문이나 "검색/최신/뉴스" 같은 말이 나오면 웹 검색을 합니다. 검색하려면 TAVILY_API_KEY도 있어야 합니다.
AUTO_WEB_SEARCH = os.getenv("AUTO_WEB_SEARCH", "true").lower() == "true"

# 유휴 상태 자동 대화 주제입니다. 도배 방지를 위해 기본은 꺼 둡니다.
IDLE_TOPIC_ENABLED = os.getenv("IDLE_TOPIC_ENABLED", "false").lower() == "true"
IDLE_TOPIC_INTERVAL_MINUTES = int(os.getenv("IDLE_TOPIC_INTERVAL_MINUTES", "10"))
IDLE_TOPIC_MIN_IDLE_MINUTES = int(os.getenv("IDLE_TOPIC_MIN_IDLE_MINUTES", "30"))
IDLE_TOPIC_COOLDOWN_MINUTES = int(os.getenv("IDLE_TOPIC_COOLDOWN_MINUTES", "120"))
