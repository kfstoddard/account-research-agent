# Account-research agent: Bright Data SERP API vs. Tavily

A small agent that does a seller's pre-call research. Give it a company name and it searches the
live web for **current** sales signals (funding, launches, leadership changes, hiring,
partnerships), then returns structured JSON with a dated source for every signal.

The search layer is interchangeable. The same agent, prompt, model and budget run on either:

- **Bright Data SERP API**: Google results as parsed JSON (Web Unlocker optional, for page fetches)
- **Tavily Search API**: a search API built for LLM agents (Tavily Extract optional, for page fetches)

A repeatable evaluation runs the agent over 20 companies with each backend and compares the results.
See [`findings.md`](findings.md) for methodology, results, limitations and implications.

## Why this task

Account research is a real, recurring workload for go-to-market agents (AI SDRs, enrichment tools,
CRM copilots). It depends on *current* information, so freshness and source quality can be measured
instead of judged by feel.

## Project layout

```
agent/
  agent.py            the agent loop (Claude + tool use), prompt, output schema
  search_backends.py  Bright Data, Tavily and offline mock backends behind one interface
  http_util.py        standard-library HTTP and .env helpers (no pip installs needed)
eval/
  companies.csv       20 test companies across segments (large tech, growth startups, non-tech)
run_eval.py           runs every company with every backend, saves raw outputs
summarize.py          builds the comparison tables from a run
research.py           research a single company (handy for demos)
results/<run-id>/     raw JSON per company and backend, plus summary tables
findings.md           methodology, results, limitations, implications
```

## Setup

Requirements: **Python 3.10+**. Only the standard library is used, so there is nothing to `pip install`.

1. Clone the repo and open a terminal in the project folder.
2. Copy `.env.example` to `.env` and fill in your keys:
   - `ANTHROPIC_API_KEY`, from console.anthropic.com
   - `BRIGHTDATA_API_KEY` and `BRIGHTDATA_SERP_ZONE`: create a SERP API zone in the Bright Data
     dashboard; the zone name is on its Overview tab. `BRIGHTDATA_UNLOCKER_ZONE` is only needed for page fetches.
   - `TAVILY_API_KEY`, from app.tavily.com
3. Check everything works offline first (no keys needed):

   ```
   python run_eval.py --backends mock --llm mock --limit 2 --run-id smoke
   ```

## Run

Research one company:

```
python research.py "Ramp" ramp.com --backend brightdata
python research.py "Ramp" ramp.com --backend tavily
```

Run the comparison and build the tables:

```
python run_eval.py --backends brightdata tavily --run-id v1
python summarize.py --run-id v1
```

Useful options: `--limit 3` (first N companies only), `--max-searches 4` (search budget per company),
`--max-fetches 2` (allow full-page reads), `--window-days 90` (what counts as "recent").
Re-running the same `--run-id` skips finished companies, so an interrupted run can be resumed
without spending credits twice. Set `DEBUG_RAW=1` to save every raw Bright Data SERP response to `results/_debug/`
(PowerShell: `$env:DEBUG_RAW="1"`).

## How it is kept fair

- Same model, prompt, search budget and results per search (`NUM_RESULTS`) for both backends. (The model does not accept a temperature setting, so outputs can vary slightly between runs; see limitations in `findings.md`.)
- Same recency filter mapped to each API's own parameter (Google `tbs=qdr:*` / Tavily `time_range`).
- Same companies, run on the same day; the run date and config are saved with every run.

## Results at a glance (run `v1`, 17 Oct 2026)

| | Bright Data SERP | Tavily |
|---|---|---|
| Recent signals found (20 companies) | 64 | 74 |
| Share of signals that were recent | 72% | 57% |
| Median time per search | 12.7s | 2.1s |
| Failed searches | 5 of 78 | 0 of 75 |
| Est. cost per recent signal | $0.016 | $0.028 |

The full analysis and caveats are in [`findings.md`](findings.md). Raw outputs, summary tables and the manual
spot-check (`manual_review.csv`) are in `results/v1/`.

## Free-tier note

Built to fit free tiers: 20 companies × 2 backends × up to 4 searches ≈ 160 search calls per full run.
Where a limit stopped a test, it is noted in `findings.md` rather than worked around with paid usage.

## Credits

Built with Claude as a coding assistant. I designed the evaluation, ran it, reviewed the outputs
and wrote the conclusions.
