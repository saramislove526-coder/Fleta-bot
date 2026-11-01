import ipaddress
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_EXPLICIT_TERMS = (
    "검색", "찾아봐", "찾아줘", "조사해", "웹에서", "인터넷에서",
    "뉴스", "최신", "실시간", "가격", "시세", "날씨", "주가", "환율",
    "업데이트", "일정", "순위", "출시일", "search", "latest", "news",
)
_FACT_TERMS = (
    "출생", "태어났", "태어난", "사망", "생몰", "본명", "국적",
    "작위", "경력", "업적", "역사", "사건", "연도", "몇 년",
    "몇년", "몇 월", "몇월", "몇 일", "몇일", "정의", "원리",
    "정확한", "사실", "근거", "출처", "무슨 뜻", "의미", "호환성",
    "스펙", "법률", "규정", "통계", "최초", "최대", "최소",
)
_PERSONAL_START = re.compile(
    r"^(?:나|내|내가|나는|넌|너는|너|우리|우리는|플레타)(?:\s|가|는|의|한테|에게|랑|도|야|를|의)"
)
_SMALL_TALK = re.compile(
    r"^(?:안녕|ㅎㅇ|하이|고마워|감사|ㅋㅋ|ㅎㅎ|뭐해|뭐하냐|오늘 뭐해|"
    r"심심해|배고파|사랑해|좋아해|놀자|잘자|잘 지냈어|좋은 아침)"
)
_PUBLIC_QUESTION = re.compile(
    r"(?:[가-힣a-z0-9]{2,})(?:은|는|이|가|의|란|이란|에 대해|에 대해서|에서)?\s*"
    r"(?:누구|무엇|뭐야|뭐임|어디|언제|몇\s*(?:년|월|일|명|개|세|살)|"
    r"왜|어떤|무슨|어떻게|알려줘|설명해|정리해)",
    re.IGNORECASE,
)
_FRESHNESS_TERMS = ("최신", "오늘", "현재", "실시간", "이번주", "이번 주", "방금", "속보")
_CACHE: OrderedDict[str, tuple[float, str, tuple[tuple[str, str], ...]]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 128


def needs_search(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip()).casefold()
    if not normalized:
        return False
    if _SMALL_TALK.match(normalized):
        return False
    if _PERSONAL_START.match(normalized) and not any(term in normalized for term in ("검색", "웹에서", "인터넷에서")):
        return False
    if any(term in normalized for term in _EXPLICIT_TERMS):
        return True
    if any(term in normalized for term in _FACT_TERMS):
        return True
    if _PUBLIC_QUESTION.search(normalized):
        return True
    if re.search(r"[가-힣a-z0-9]{2,}(?:에 대해|에 대해서)\s*(?:알려|설명|정리)", normalized):
        return True
    return False


def prepare_search_query(text: str) -> str:
    query = re.sub(r"<@!?\d+>|<@&\d+>|@everyone|@here", " ", text or "")
    query = re.sub(r"^(?:(?:플레타|플레타야|야야|저기|혹시)[,!\s]+)+", "", query.strip(), flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip()
    return query[:240]


def _public_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password:
            return None
        if hostname in ("localhost",) or hostname.endswith((".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(hostname).is_global:
                return None
        except ValueError:
            pass
        return url
    except (ValueError, TypeError):
        return None


def _source_score(url: str, api_score: object) -> float:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith((".go.kr", ".ac.kr", ".gov", ".edu")) or host in ("go.kr", "ac.kr"):
        domain_weight = 4
    elif host.endswith((".or.kr", ".org")) or host.endswith("britannica.com"):
        domain_weight = 2
    elif any(tag in host for tag in ("blog.", "tistory.", "namu.wiki", "fandom.com")):
        domain_weight = -2
    else:
        domain_weight = 0
    relevance = float(api_score) if isinstance(api_score, (int, float)) and not isinstance(api_score, bool) else 0
    return domain_weight + max(0.0, min(1.0, relevance))


def _get_cached(query: str):
    with _CACHE_LOCK:
        cached = _CACHE.get(query)
        if not cached:
            return None
        expires_at, context, sources = cached
        if expires_at <= time.monotonic():
            del _CACHE[query]
            return None
        _CACHE.move_to_end(query)
        return context, list(sources)


def _set_cached(query: str, context: str, sources: list[tuple[str, str]], ttl: int) -> None:
    with _CACHE_LOCK:
        _CACHE[query] = (time.monotonic() + ttl, context, tuple(sources))
        _CACHE.move_to_end(query)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)


def search_web(query: str) -> tuple[str, list[tuple[str, str]]] | None:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    search_query = prepare_search_query(query)
    if not search_query:
        return None
    cache_key = search_query.casefold()
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        response = httpx.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": search_query, "search_depth": "basic", "max_results": 6, "topic": "general"},
            timeout=12.0,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
    except (httpx.HTTPError, ValueError, TypeError):
        return None

    if not isinstance(results, list):
        return None
    ranked = []
    seen_urls = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = _public_url(item.get("url", ""))
        if not url or url in seen_urls:
            continue
        title = re.sub(r"[\[\]()<>]", " ", str(item.get("title") or "검색 결과"))
        title = " ".join(title.split())[:100]
        snippet = " ".join(str(item.get("content") or "").split())[:700]
        if not snippet:
            continue
        seen_urls.add(url)
        ranked.append((_source_score(url, item.get("score")), title, snippet, url))

    ranked.sort(key=lambda row: row[0], reverse=True)
    selected = ranked[:3]
    if not selected:
        return None

    context = "\n\n".join(
        f"[{index}] {title}\n출처: {url}\n내용: {snippet}"
        for index, (_, title, snippet, url) in enumerate(selected, 1)
    )
    sources = [(title, url) for _, title, _, url in selected]
    ttl = 300 if any(term in search_query.casefold() for term in _FRESHNESS_TERMS) else 1800
    _set_cached(cache_key, context, sources, ttl)
    return context, sources
