"""Account-research agent.

Given a company, the agent uses a web-search tool (backed by Bright Data or Tavily) to find
current sales signals and returns structured JSON with a dated source for every signal.

The LLM is Claude, called through the Anthropic Messages API with plain HTTP.
"""
import datetime as dt
import json
import os
import re
import time

from .http_util import post_json

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are an account-research agent for a B2B sales team.
Today's date is {today}. Your job: find CURRENT signals about the target company that a seller
could use to open a conversation. Focus on the last {window} days.

Signal types: funding, acquisition, product_launch, leadership_change, hiring, partnership,
earnings, layoffs, other_news.

Rules:
- Use the web_search tool. You have a budget of at most {max_searches} searches{fetch_rule}.
- Only report a signal if a search result (or fetched page) supports it.
- Every signal must cite a source_url that appeared in your tool results. Never invent URLs.
- Give each signal a date (YYYY-MM-DD) if the source shows one; otherwise null.
- If you find nothing recent, say so. An honest empty result beats a guess.

When done, reply with ONLY a JSON object, no prose, in this shape:
{{"company": "...", "signals": [{{"type": "...", "summary": "one sentence", "date": "YYYY-MM-DD or null", "source_url": "..."}}],
  "overall_confidence": "high|medium|low", "notes": "anything the seller should know, incl. gaps"}}"""

SEARCH_TOOL = {
    "name": "web_search",
    "description": ("Search the live web. Returns up to ~5 results with title, url, snippet and date. "
                    "Use specific queries, e.g. '<Company> funding 2026' or '<Company> new CEO'."),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "recency": {"type": "string", "enum": ["week", "month", "year", "any"],
                        "description": "Limit results to this time window. Default: month."},
        },
        "required": ["query"],
    },
}

FETCH_TOOL = {
    "name": "fetch_page",
    "description": "Fetch the readable text of one URL from your search results, to confirm details or dates.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}


def call_claude(messages, system, tools):
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    payload = {"model": model, "max_tokens": 2000,
               "system": system, "tools": tools, "messages": messages}
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
    _, body = post_json(ANTHROPIC_URL, payload, headers, timeout=120)
    return json.loads(body)


def extract_json(text):
    """Return the first JSON object found in the model's final text."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def run_agent(company, domain, backend, max_searches=4, max_fetches=0, window_days=90,
              llm=call_claude, today=None):
    """Run the agent for one company. Returns a dict with the answer plus run metrics."""
    today = today or dt.date.today().isoformat()
    tools = [SEARCH_TOOL] + ([FETCH_TOOL] if max_fetches > 0 else [])
    fetch_rule = f" and {max_fetches} page fetches" if max_fetches > 0 else ""
    system = SYSTEM_PROMPT.format(today=today, window=window_days,
                                  max_searches=max_searches, fetch_rule=fetch_rule)
    messages = [{"role": "user", "content": f"Research this company: {company} ({domain})."}]

    seen_urls, trace = set(), []
    usage = {"input_tokens": 0, "output_tokens": 0}
    searches = fetches = 0
    start = time.time()
    final_text, stop = "", "max_turns"

    for _ in range(max_searches + max_fetches + 3):  # hard stop on turns
        resp = llm(messages, system, tools)
        for k in usage:
            usage[k] += resp.get("usage", {}).get(k, 0)
        content = resp.get("content", [])
        messages.append({"role": "assistant", "content": content})
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if not tool_uses:
            final_text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            stop = "answered"
            break

        results = []
        for tu in tool_uses:
            name, args = tu["name"], tu.get("input", {})
            try:
                if name == "web_search":
                    if searches >= max_searches:
                        output = "Search budget used up. Give your final JSON answer now."
                    else:
                        searches += 1
                        hits = backend.search(args.get("query", ""), args.get("recency", "month"))
                        seen_urls.update(h["url"] for h in hits)
                        output = json.dumps(hits, ensure_ascii=False)
                        trace.append({"tool": name, "query": args.get("query"),
                                      "recency": args.get("recency", "month"), "n_results": len(hits)})
                elif name == "fetch_page":
                    if fetches >= max_fetches:
                        output = "Fetch budget used up. Give your final JSON answer now."
                    else:
                        fetches += 1
                        url = args.get("url", "")
                        output = backend.fetch(url)
                        seen_urls.add(url)
                        trace.append({"tool": name, "url": url, "chars": len(output)})
                else:
                    output = f"Unknown tool {name}"
            except Exception as e:
                output = f"Tool error: {e}"
                trace.append({"tool": name, "query": args.get("query") or args.get("url"),
                              "error": str(e)[:300]})
            results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": output})
        messages.append({"role": "user", "content": results})

    answer = extract_json(final_text)
    return {
        "company": company,
        "domain": domain,
        "backend": backend.name,
        "run_date": today,
        "answer": answer,
        "raw_final_text": final_text if answer is None else None,
        "stop_reason": stop,
        "metrics": {
            "wall_time_s": round(time.time() - start, 2),
            "search_api_time_s": round(backend.latency_s, 2),
            "searches": searches,
            "fetches": fetches,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "tool_errors": len([t for t in trace if "error" in t]),
        },
        "seen_urls": sorted(seen_urls),
        "trace": trace,
    }
