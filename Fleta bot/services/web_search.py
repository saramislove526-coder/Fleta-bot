import ipaddress
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx

# ──────────────────────────────────────────────
# 웹 검색 담당 파일입니다.
# "이 질문은 검색해야 하나?"를 판단하고, 필요하면 Tavily로 검색해서 근거 자료를 가져옵니다.
# 검색하려면 서버 환경 변수에 TAVILY_API_KEY를 넣어야 합니다. 없으면 검색 없이 그냥 답합니다.
# ──────────────────────────────────────────────

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# 이 말이 들어가면 무조건 검색합니다. 사용자가 대놓고 최신 정보를 원하는 경우입니다.
_EXPLICIT_TERMS = (
    "검색", "찾아봐", "찾아줘", "조사해", "웹에서", "인터넷에서",
    "뉴스", "최신", "실시간", "가격", "시세", "날씨", "주가", "환율",
    "업데이트", "일정", "순위", "출시일", "search", "latest", "news",
)
# 사실 확인이 필요한 주제어입니다. AI가 기억만으로 답하다 틀리기 쉬운 것들이라 검색으로 근거를 붙입니다.
_FACT_TERMS = (
    "출생", "태어났", "태어난", "사망", "생몰", "본명", "국적",
    "작위", "경력", "업적", "역사", "사건", "연도", "몇 년",
    "몇년", "몇 월", "몇월", "몇 일", "몇일", "정의", "원리",
    "정확한", "사실", "근거", "출처", "무슨 뜻", "의미", "호환성",
    "스펙", "법률", "규정", "통계", "최초", "최대", "최소",
)
# "나/너/우리/플레타"로 시작하는 말은 캐릭터나 사용자 본인 얘기라서 검색하지 않습니다.
_PERSONAL_START = re.compile(
    r"^(?:나|내|내가|나는|넌|너는|너|우리|우리는|플레타)(?:\s|가|는|의|한테|에게|랑|도|야|를|의)"
)
# 인사·잡담은 검색하지 않습니다. 검색 크레딧도 아끼고 답도 빨라집니다.
_SMALL_TALK = re.compile(
    r"^(?:안녕|ㅎㅇ|하이|고마워|감사|ㅋㅋ|ㅎㅎ|뭐해|뭐하냐|오늘 뭐해|"
    r"심심해|배고파|사랑해|좋아해|놀자|잘자|잘 지냈어|좋은 아침)"
)
# "이완용은 누구야?", "광합성 원리 알려줘"처럼 바깥 세상의 사실을 묻는 질문 형태입니다.
_PUBLIC_QUESTION = re.compile(
    r"(?:[가-힣a-z0-9]{2,})(?:은|는|이|가|의|란|이란|에 대해|에 대해서|에서)?\s*"
    r"(?:누구|무엇|뭐야|뭐임|어디|언제|몇\s*(?:년|월|일|명|개|세|살)|"
    r"왜|어떤|무슨|어떻게|알려줘|설명해|정리해)",
    re.IGNORECASE,
)
# 이런 말이 있으면 금방 바뀌는 정보라서 검색 결과를 짧게(5분)만 캐시합니다. 나머지는 30분입니다.
_FRESHNESS_TERMS = ("최신", "오늘", "현재", "실시간", "이번주", "이번 주", "방금", "속보")
# 디스코드 쪽(cogs/events.py)에서 메시지에 덧붙이는 안내 줄입니다. 검색 판단·검색어에서는 뺍니다.
_META_PREFIXES = ("Custom emoji reaction:", "Sticker sent:", "Attached files:", "The user called your name")
# 같은 질문을 또 하면 검색 API를 다시 부르지 않고 저장해 둔 결과를 씁니다. 최대 128개까지 기억합니다.
_CACHE: OrderedDict[str, tuple[float, str, tuple[tuple[str, str], ...]]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 128


def _user_text(text: str) -> str:
    """[답장한 메시지 …], 이모지·첨부 안내 같은 부가 줄을 빼고 사용자가 직접 친 글만 남깁니다."""
    lines = [
        line.strip()
        for line in (text or "").splitlines()
        if line.strip() and not line.lstrip().startswith("[") and not line.startswith(_META_PREFIXES)
    ]
    return " ".join(lines)


def needs_search(text: str) -> bool:
    """이 메시지를 검색해야 하는지 판단합니다. True면 검색하고, 답변 온도도 낮추고, 답변 후 숫자 검증까지 합니다."""
    normalized = re.sub(r"\s+", " ", _user_text(text)).casefold()
    if not normalized:
        return False
    if any(term in normalized for term in _EXPLICIT_TERMS):
        return True
    if _SMALL_TALK.match(normalized):
        return False
    if _PERSONAL_START.match(normalized):
        return False
    if any(term in normalized for term in _FACT_TERMS):
        return True
    if _PUBLIC_QUESTION.search(normalized):
        return True
    if re.search(r"[가-힣a-z0-9]{2,}(?:에 대해|에 대해서)\s*(?:알려|설명|정리)", normalized):
        return True
    return False


def prepare_search_query(text: str) -> str:
    """검색어를 다듬습니다. 멘션, "플레타야/저기/혹시" 같은 부르는 말, 디스코드 부가 줄을 지웁니다."""
    query = re.sub(r"<@!?\d+>|<@&\d+>|@everyone|@here", " ", _user_text(text))
    query = re.sub(r"^(?:(?:플레타|플레타야|야야|저기|혹시)[,!\s]+)+", "", query.strip(), flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip()
    return query[:240]


def _public_url(url: str) -> str | None:
    """공개 인터넷 주소만 통과시킵니다. localhost·내부 IP 같은 주소는 출처로 쓰지 않습니다."""
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
    """출처 신뢰도 점수입니다. 정부·학교 사이트는 점수를 더 주고, 블로그·나무위키 같은 곳은 깎습니다."""
    host = (urlparse(url).hostname or "").lower()
    if host.endswith((".go.kr", ".ac.kr", ".gov", ".edu")) or host in ("go.kr", "ac.kr"):
        domain_weight = 0.25
    elif host.endswith((".or.kr", ".org")) or host.endswith("britannica.com"):
        domain_weight = 0.12
    elif any(tag in host for tag in ("blog.", "tistory.", "namu.wiki", "fandom.com")):
        domain_weight = -0.2
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
    """Tavily로 검색해서 (AI에게 줄 근거 자료, 출처 링크 목록)을 돌려줍니다.

    결과에는 [1], [2]처럼 번호를 붙입니다. AI가 답변에서 같은 번호로 출처를 달 수 있게 하기 위해서입니다.
    키가 없거나 검색이 실패하면 None을 돌려주고, 그때는 검색 없이 답합니다.
    """
    api_key = os.getenv("TAVILY_API_KEY")  # 키는 코드에 적지 말고 서버 환경 변수에 넣으면 됩니다.
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
            # 6개를 받아서 신뢰도 순으로 3개만 고릅니다.
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
