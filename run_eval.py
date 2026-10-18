"""Run the account-research agent over the test companies with each search backend.

Examples (from the project folder):
    python run_eval.py --backends mock --llm mock --limit 2          # offline smoke test, no keys
    python run_eval.py --backends brightdata tavily --limit 3       # quick real test
    python run_eval.py --backends brightdata tavily --run-id v1     # full run (12 companies)
    python summarize.py --run-id v1                                 # build the comparison tables

Results are saved per company and backend in results/<run-id>/. Re-running the same run-id
skips companies already done, so an interrupted run can be resumed without spending credits twice.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys

from agent.agent import call_claude, run_agent
from agent.http_util import load_env
from agent.search_backends import make_backend


def mock_llm(messages, system, tools):
    """Offline stand-in for Claude: one search, then a JSON answer citing the first result."""
    turns = sum(1 for m in messages if m["role"] == "assistant")
    if turns == 0:
        return {"usage": {"input_tokens": 100, "output_tokens": 20}, "content": [
            {"type": "tool_use", "id": "t1", "name": "web_search",
             "input": {"query": "Example funding", "recency": "month"}}]}
    url = "https://example.com/news/1"
    answer = {"company": "Example", "signals": [{"type": "funding", "summary": "Raised $50M Series B.",
              "date": "2026-09-30", "source_url": url}], "overall_confidence": "medium", "notes": "mock"}
    return {"usage": {"input_tokens": 300, "output_tokens": 80},
            "content": [{"type": "text", "text": json.dumps(answer)}]}


def had_errors(path):
    """True if a saved result crashed or had any search/fetch errors."""
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, json.JSONDecodeError):
        return True
    return bool(r.get("fatal_error") or r.get("answer") is None
                or (r.get("metrics") or {}).get("tool_errors"))


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backends", nargs="+", default=["brightdata", "tavily"])
    p.add_argument("--companies", default="eval/companies.csv")
    p.add_argument("--limit", type=int, default=0, help="only the first N companies (0 = all)")
    p.add_argument("--max-searches", type=int, default=4)
    p.add_argument("--max-fetches", type=int, default=0, help="page fetches allowed per company (0 = off)")
    p.add_argument("--window-days", type=int, default=90)
    p.add_argument("--run-id", default=dt.datetime.now().strftime("run-%Y%m%d-%H%M"))
    p.add_argument("--llm", choices=["claude", "mock"], default="claude")
    p.add_argument("--redo-errors", action="store_true",
                   help="re-run companies whose saved result has a crash or tool errors "
                        "(e.g. after the laptop slept mid-run); re-runs are logged in config")
    args = p.parse_args()

    load_env()
    llm = mock_llm if args.llm == "mock" else call_claude
    with open(args.companies, newline="", encoding="utf-8") as f:
        companies = list(csv.DictReader(f))
    if args.limit:
        companies = companies[: args.limit]

    out_root = os.path.join("results", args.run_id)
    os.makedirs(out_root, exist_ok=True)
    config = {k: v for k, v in vars(args).items()}
    config.update({"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5") if args.llm == "claude" else "mock",
                   "num_results": os.environ.get("NUM_RESULTS", "5"), "started": dt.datetime.now().isoformat()})
    with open(os.path.join(out_root, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    redone = []
    for backend_name in args.backends:
        os.makedirs(os.path.join(out_root, backend_name), exist_ok=True)
        for row in companies:
            path = os.path.join(out_root, backend_name, slug(row["company"]) + ".json")
            if os.path.exists(path):
                if args.redo_errors and had_errors(path):
                    print(f"[redo] {backend_name:10s} {row['company']} (previous attempt had errors)")
                    redone.append(f"{backend_name}/{row['company']}")
                else:
                    print(f"[skip] {backend_name:10s} {row['company']} (already done)")
                    continue
            backend = make_backend(backend_name)  # fresh counters per company
            try:
                result = run_agent(row["company"], row["domain"], backend,
                                   max_searches=args.max_searches, max_fetches=args.max_fetches,
                                   window_days=args.window_days, llm=llm)
            except Exception as e:
                print(f"[FAIL] {backend_name:10s} {row['company']}: {e}", file=sys.stderr)
                result = {"company": row["company"], "backend": backend_name, "answer": None,
                          "fatal_error": str(e)[:500], "metrics": {}}
            result["segment"] = row.get("segment")
            result["backend_errors"] = backend.errors
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            n = len((result.get("answer") or {}).get("signals", []))
            m = result.get("metrics", {})
            print(f"[done] {backend_name:10s} {row['company']:22s} signals={n} "
                  f"searches={m.get('searches')} time={m.get('wall_time_s')}s")

    if redone:  # keep an honest record of what was re-run
        log_path = os.path.join(out_root, "redo_log.json")
        log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else []
        log.append({"time": dt.datetime.now().isoformat(), "redone": redone})
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    print(f"\nSaved to {out_root}. Next: python summarize.py --run-id {args.run_id}")


if __name__ == "__main__":
    main()
