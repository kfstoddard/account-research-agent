"""Interchangeable search backends.

Every backend exposes the same two methods so the agent never knows which one it is using:
    search(query, recency) -> list[dict]   each dict: {title, url, snippet, date}
    fetch(url)             -> str           readable page text (optional deep read)

Backends:
    brightdata  - Bright Data SERP API (Google results, parsed JSON) + Web Unlocker for fetch
    tavily      - Tavily Search API + Tavily Extract for fetch
"""
import json
import os
import re
import time
import urllib.parse

from .http_util import HttpError, post_json

RECENCY_GOOGLE = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
RECENCY_TAVILY = {"day": "day", "week": "week", "month": "month", "year": "year"}

DATE_PATTERNS = [
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d+ (?:hour|day|week|month)s? ago\b",
]


def guess_date(text):
    """Pull a date-looking string out of a snippet, if there is one."""
    for pat in DATE_PATTERNS:
        m = re.search(pat, text or "")
        if m:
            return m.group(0)
    return None


def _as_items(value):
    """Normalize a SERP section into a list of dicts (sections can be lists, dicts or missing)."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for k in ("items", "results", "stories", "news"):
            if isinstance(value.get(k), list):
                return [v for v in value[k] if isinstance(v, dict)]
        return [value] if ("link" in value or "url" in value) else []
    return []


def _flatten_text(obj, limit=2000):
    """All string values inside a nested dict/list, joined (used to find a date anywhere in a result)."""
    parts = []

    def walk(o):
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return " ".join(parts)[:limit]


def strip_html(html, limit=6000):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:limit]


class SearchBackend:
    name = "base"

    def __init__(self):
        self.calls = {"search": 0, "fetch": 0}
        self.latency_s = 0.0
        self.errors = []

    def _timed(self, kind, fn):
        self.calls[kind] += 1
        start = time.time()
        try:
            return fn()
        except Exception as e:  # keep the agent running; record the failure
            self.errors.append(f"{kind}: {e}")
            raise
        finally:
            self.latency_s += time.time() - start

    def search(self, query, recency="month"):
        return self._timed("search", lambda: self._search(query, recency))

    def fetch(self, url):
        return self._timed("fetch", lambda: self._fetch(url))


class BrightDataBackend(SearchBackend):
    """Bright Data SERP API (and Web Unlocker for page fetches)."""
    name = "brightdata"
    ENDPOINT = "https://api.brightdata.com/request"

    def __init__(self):
        super().__init__()
        self.key = os.environ["BRIGHTDATA_API_KEY"]
        self.serp_zone = os.environ["BRIGHTDATA_SERP_ZONE"]
        self.unlocker_zone = os.environ.get("BRIGHTDATA_UNLOCKER_ZONE", "")
        self.num_results = int(os.environ.get("NUM_RESULTS", "5"))
        self.non_json_responses = 0
        self.debug_count = 0

    def _request(self, zone, url):
        payload = {"zone": zone, "url": url, "format": "raw"}
        _, body = post_json(self.ENDPOINT, payload, {"Authorization": f"Bearer {self.key}"})
        return body

    def _search(self, query, recency):
        params = {"q": query, "hl": "en", "gl": "us", "num": str(max(self.num_results, 10)), "brd_json": "1"}
        if recency in RECENCY_GOOGLE:
            params["tbs"] = RECENCY_GOOGLE[recency]
        url = "https://www.google.com/search?" + urllib.parse.urlencode(params)
        data, body = None, ""
        for attempt in range(2):  # one retry: occasional empty / non-JSON responses
            body = self._request(self.serp_zone, url)
            self._save_debug(query, attempt, body)
            try:
                data = json.loads(body)
                break
            except json.JSONDecodeError:
                self.non_json_responses += 1
        if data is None:
            raise RuntimeError(f"non-JSON SERP response after retry (first 150 chars: {body[:150]!r})")
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected SERP response type: {type(data).__name__}")

        results = []
        # Parsed Google JSON: organic results live under "organic"; news may sit under
        # "top_stories" / "news", sometimes as a list and sometimes wrapped in a dict.
        for key in ("top_stories", "news", "organic"):
            for item in _as_items(data.get(key)):
                link = item.get("link") or item.get("url")
                if not link or not isinstance(link, str):
                    continue
                snippet = item.get("description") or item.get("snippet") or ""
                if not isinstance(snippet, str):
                    snippet = str(snippet)
                date = item.get("date") if isinstance(item.get("date"), str) else None
                results.append({
                    "title": str(item.get("title", "")),
                    "url": link,
                    "snippet": snippet,
                    # dates can hide in several fields; scan the whole item as a fallback
                    "date": date or guess_date(snippet) or guess_date(_flatten_text(item)),
                })
        # de-duplicate by URL, keep order
        seen, unique = set(), []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)
        return unique[: self.num_results]

    def _save_debug(self, query, attempt, body):
        """With DEBUG_RAW=1, keep every raw SERP response so the parsed format can be inspected."""
        if not os.environ.get("DEBUG_RAW"):
            return
        os.makedirs(os.path.join("results", "_debug"), exist_ok=True)
        self.debug_count += 1
        name = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]
        path = os.path.join("results", "_debug", f"serp_{self.debug_count:02d}_{name}_try{attempt}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    def _fetch(self, url):
        if not self.unlocker_zone:
            raise RuntimeError("BRIGHTDATA_UNLOCKER_ZONE not set")
        return strip_html(self._request(self.unlocker_zone, url))


class TavilyBackend(SearchBackend):
    """Tavily Search API (and Tavily Extract for page fetches)."""
    name = "tavily"

    def __init__(self):
        super().__init__()
        self.key = os.environ["TAVILY_API_KEY"]
        self.num_results = int(os.environ.get("NUM_RESULTS", "5"))

    def _search(self, query, recency):
        payload = {"query": query, "max_results": self.num_results, "search_depth": "basic"}
        if recency in RECENCY_TAVILY:
            payload["time_range"] = RECENCY_TAVILY[recency]
        _, body = post_json("https://api.tavily.com/search", payload, {"Authorization": f"Bearer {self.key}"})
        data = json.loads(body)
        out = []
        for item in data.get("results", []):
            snippet = item.get("content", "")
            out.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": snippet,
                "date": item.get("published_date") or guess_date(snippet),
            })
        return out

    def _fetch(self, url):
        _, body = post_json("https://api.tavily.com/extract", {"urls": [url]},
                            {"Authorization": f"Bearer {self.key}"})
        data = json.loads(body)
        results = data.get("results") or []
        if not results:
            raise RuntimeError(f"Tavily extract returned nothing for {url}")
        return (results[0].get("raw_content") or "")[:6000]


class MockBackend(SearchBackend):
    """Offline backend for testing the agent loop without API keys."""
    name = "mock"

    def _search(self, query, recency):
        return [{"title": f"Mock result for {query}", "url": "https://example.com/news/1",
                 "snippet": "Sep 30, 2026 - Example Co raised a $50M Series B.", "date": "Sep 30, 2026"}]

    def _fetch(self, url):
        return "Example Co raised a $50M Series B led by Example Ventures on Sep 30, 2026."


BACKENDS = {"brightdata": BrightDataBackend, "tavily": TavilyBackend, "mock": MockBackend}


def make_backend(name):
    if name not in BACKENDS:
        raise ValueError(f"Unknown backend '{name}'. Choose from: {', '.join(BACKENDS)}")
    return BACKENDS[name]()


__all__ = ["make_backend", "BACKENDS", "HttpError"]
