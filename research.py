"""Research one company with one backend and print the result.

    python research.py "Ramp" ramp.com --backend brightdata
    python research.py "Ramp" ramp.com --backend tavily
    python research.py "Ramp" ramp.com --backend mock --llm mock     # offline, no keys
"""
import argparse
import json

from agent.agent import call_claude, run_agent
from agent.http_util import load_env
from agent.search_backends import make_backend
from run_eval import mock_llm


def main():
    p = argparse.ArgumentParser()
    p.add_argument("company")
    p.add_argument("domain")
    p.add_argument("--backend", default="brightdata", choices=["brightdata", "tavily", "mock"])
    p.add_argument("--max-searches", type=int, default=4)
    p.add_argument("--max-fetches", type=int, default=0)
    p.add_argument("--llm", choices=["claude", "mock"], default="claude")
    args = p.parse_args()

    load_env()
    backend = make_backend(args.backend)
    result = run_agent(args.company, args.domain, backend, max_searches=args.max_searches,
                       max_fetches=args.max_fetches, llm=mock_llm if args.llm == "mock" else call_claude)
    result["backend_errors"] = backend.errors
    print(json.dumps({k: result[k] for k in ("answer", "metrics", "trace", "backend_errors")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
