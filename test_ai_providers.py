"""프로바이더 폴백 로직 수동 검증 스크립트 (실행 후 삭제 가능)"""
import os
import sys
import logging

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE, ".env"))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

from config import HUGGINGFACE_MODEL, HUGGINGFACE_VISION_MODEL, NVIDIA_MODEL, GROQ_MODEL, OPENAI_MODEL
from services import ai_service

print(f"models -> HF: {HUGGINGFACE_MODEL} / vision: {HUGGINGFACE_VISION_MODEL}")
print(f"models -> NV: {NVIDIA_MODEL} / GROQ: {GROQ_MODEL} / OPENAI: {OPENAI_MODEL}")
print(f"openai key set: {bool(os.getenv('OPENAI_API_KEY'))}")

messages = [
    {"role": "system", "content": "너는 한국어로만 답하는 캐릭터 봇이야."},
    {"role": "user", "content": "한국어로 짧게 인사해 줘."},
]

ok = 0
fail = 0
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6
for i in range(runs):
    try:
        text = ai_service._request_generation([dict(m) for m in messages], max_tokens=300)
        ok += 1
        print(f"[{i}] OK   -> {text[:100]!r}")
    except Exception as exc:
        fail += 1
        print(f"[{i}] FAIL -> {exc}")

print("cooldowns:", {k: round(v - __import__('time').time(), 1) for k, v in ai_service._provider_cooldowns.items()})
print(f"RESULT: {ok} success / {fail} fail")
sys.exit(0 if ok > 0 else 1)
