# main.py — 호스팅 서버 진입점 (STARTUP_FILE=main.py)
# 실제 로직은 bot.py에 있습니다.

import bot

if __name__ == "__main__":
    import asyncio
    asyncio.run(bot.main())
