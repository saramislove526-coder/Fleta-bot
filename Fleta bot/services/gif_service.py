import logging
import random
import re
from urllib.parse import quote
import httpx
from config import KLIPY_API_KEY

log = logging.getLogger("fleta.gif")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://klipy.com",
    "Referer": "https://klipy.com/",
}

# Klipy 웹사이트 기본 헤더/UI 아이콘 GIF (검색 결과가 아니므로 제외)
EXCLUDED_GIFS = {
    "https://static.klipy.com/ii/d7aec6f6f171607374b2065c836f92f4/ec/f3/OXB1QWhn.gif",
}


def clean_search_term(term: str) -> str:
    """자연어 검색어에서 조사나 불필요한 요청 문구를 정제합니다."""
    q = (term or "").strip()
    q = re.sub(r"^(?:나\s*|저\s*|제발\s*|혹시\s*)", "", q).strip()
    q = re.sub(r"(?:보내줘|보여줘|줘|찾아줘|올려줘|검색해줘|내놔|띄워줘|해줘|부탁해)$", "", q).strip()
    q = re.sub(r"(?:gif|움짤)$", "", q, flags=re.IGNORECASE).strip()
    return q or term.strip()


def search_gif(query: str, limit: int = 20) -> str | None:
    """Klipy에서 검색어에 맞는 고화질 애니메이션 GIF의 직링크(static.klipy.com)를 반환합니다."""
    clean_q = clean_search_term(query)
    if not clean_q:
        return None

    # 1. Klipy 공식 Search API 호출
    api_key = KLIPY_API_KEY or "pmpZyPifwSulBfELHCbpaOllUfgsjqt9yeImc2XWIcHSWjnAUBw9oueRf4kD5r25"
    api_url = f"https://api.klipy.com/api/v1/{api_key}/gifs/search?q={quote(clean_q)}&limit={limit}"
    try:
        with httpx.Client(headers=HEADERS, timeout=6.0) as client:
            resp = client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("data", [])
                candidates = []
                for item in items:
                    f = item.get("file", {})
                    gif_url = (
                        f.get("hd", {}).get("gif", {}).get("url")
                        or f.get("md", {}).get("gif", {}).get("url")
                        or f.get("sm", {}).get("gif", {}).get("url")
                    )
                    if gif_url and gif_url not in EXCLUDED_GIFS:
                        candidates.append(gif_url)
                if candidates:
                    return random.choice(candidates[:8])
    except Exception as err:
        log.warning("Klipy API 호출 중 오류 (fallback 시도): %s", err)

    # 2. API 실패 시 Klipy 웹페이지 폴백 스크래핑
    try:
        scrape_url = f"https://klipy.com/search/{quote(clean_q)}"
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=6.0) as client:
            resp = client.get(scrape_url)
            if resp.status_code == 200:
                clean_text = resp.text.replace(r"\/", "/").replace('\\"', '"')
                gifs = re.findall(r"https://static\.klipy\.com/ii/[^\s\"\'<>\\]+\.gif", clean_text)
                valid_gifs = [g for g in dict.fromkeys(gifs) if g not in EXCLUDED_GIFS]
                if valid_gifs:
                    return random.choice(valid_gifs[:8])
    except Exception as err:
        log.warning("Klipy 스크래핑 폴백 오류: %s", err)

    return None


def extract_gif_query(text: str) -> str | None:
    """유저의 메시지에서 GIF/움짤 요청 의도와 검색어를 감지합니다."""
    t = (text or "").strip()
    if not re.search(r"\b(?:gif|움짤)\b|gif|움짤", t, re.IGNORECASE):
        return None

    # 패턴 1: [검색어] (gif|움짤) (보내줘|보여줘|줘|찾아줘|내놔|띄워줘|올려줘)?
    m1 = re.search(
        r"^(?:플레타(?:야)?\s*)?(.+?)\s*(?:gif|움짤)\s*(?:보내줘|보여줘|줘|찾아줘|내놔|띄워줘|올려줘|검색해줘|해줘)?\s*$",
        t,
        re.IGNORECASE,
    )
    if m1 and m1.group(1).strip():
        q = clean_search_term(m1.group(1).strip())
        if q:
            return q

    # 패턴 2: (gif|움짤) [검색어]
    m2 = re.search(r"^(?:플레타(?:야)?\s*)?(?:gif|움짤)\s+(.+)$", t, re.IGNORECASE)
    if m2 and m2.group(1).strip():
        q = clean_search_term(m2.group(1).strip())
        if q:
            return q

    return None
