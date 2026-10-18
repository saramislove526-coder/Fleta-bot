import os
import re

import requests


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SEARCH_TERMS = (
    "검색", "찾아", "알아봐", "뉴스", "최신",
    "가격", "시세", "날씨", "주가", "환율", "업데이트", "일정", "순위",
    "실시간", "이슈", "생방송", "search", "news", "weather", "latest",
)


def needs_search(text: str) -> bool:
    """Avoid spending a search credit on ordinary character conversation."""
    normalized = re.sub(r"\s+", "", text).casefold()
    return any(term in normalized for term in SEARCH_TERMS)


def search_web(query: str) -> tuple[str, list[tuple[str, str]]] | None:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    try:
        response = requests.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query[:400], "search_depth": "basic", "max_results": 3, "topic": "general"},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("results", [])[:3]
    except (requests.RequestException, ValueError):
        return None

    sources = [(item.get("title", "검색 결과"), item.get("url", "")) for item in results if item.get("url")]
    if not sources:
        return None
    context = "\n".join(
        f"- {item.get('title', '검색 결과')}: {item.get('content', '')[:700]} ({item.get('url', '')})"
        for item in results
    )
    return context, sources
