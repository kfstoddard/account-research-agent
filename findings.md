# Findings: Bright Data SERP API vs. Tavily for sales account research

**Run:** `v1`, 17 Oct 2026 · 20 companies × 2 backends · Claude (`claude-sonnet-5-5`) · 4 searches per company, 5 results per search, no page fetches, 90-day recency window.

## TL;DR

- **Tavily was faster, more reliable and found more.** It returned 74 recent signals against Bright Data's 64. The median search took 2.1s on Tavily and 12.7s on Bright Data, and Tavily had 0 failed searches against Bright Data's 5 of 78.
- **Bright Data was more precise and about 45% cheaper per useful signal.** Of its signals, 72% were recent (Tavily: 57%) and 76% were dated (Tavily: 62%). Google's short snippets meant the agent read about half the tokens per company. All-in, that came to an estimated **$0.011 per recent signal, against $0.021 for Tavily**.
- **Accuracy was high on both.** A manual check of 10 signals found 9 correct and 1 unverifiable, with none wrong or stale. Every undated signal checked turned out to be recent: the date was on the page, just not in the snippet.
- **Decision this points to:** position Bright Data SERP for **batch, background account research and enrichment pipelines**, where cost per signal and precision matter and nobody waits on latency. Don't lead with real-time, in-chat agents, where Tavily's speed wins today. (See *Implications*.)

## What was built

An agent that does a seller's pre-call research. Given a company, it runs up to 4 web searches and returns JSON: a list of signals (funding, launches, leadership changes, hiring, partnerships, earnings and similar), each with a one-line summary, a date and the source URL it came from.

The search tool sits behind one interface (`agent/search_backends.py`), so switching backends changes nothing else. The model, prompt, budget, results per search, recency window and companies are all identical across backends.

- **Bright Data:** SERP API (Google, parsed JSON via `brd_json=1`, US/English). The recency filter maps to Google `tbs=qdr:*`.
- **Tavily:** `/search`, basic depth, general topic. The recency filter maps to `time_range`.

## Methodology

**Test set** (`eval/companies.csv`): 20 companies in three segments.

| Segment | Companies |
|---|---|
| large_tech (4) | Databricks, Figma, Mistral AI, Cohere |
| growth_startup (11) | Ramp, Rippling, Glean, Harvey, Clay, Vercel, Supabase, ElevenLabs, Runway, Crusoe, Zipline |
| non_tech (5) | Chobani, Allbirds, Peloton, Vacasa, Columbia Sportswear |

The mix was chosen on purpose. Large and growth tech companies get heavy press coverage. Non-tech brands and ambiguous names (Clay, Ramp, Runway) are harder.

**Metrics** (computed automatically by `summarize.py` from the saved JSON):

| Metric | Definition |
|---|---|
| Valid JSON | The agent returned parseable JSON in the required shape |
| Signals | Number of signals returned |
| Dated | Share of signals with a date (YYYY-MM-DD) |
| Recent | Share of signals dated within the last 90 days. This is the measure of *useful* output |
| Grounded | Share of signals whose `source_url` appeared in the tool results, i.e. a check for invented links |
| Cost / latency | Searches, LLM input and output tokens, search-API time, total time, tool errors |

**Manual check:** I spot-checked 10 signals (5 per backend) against their sources in `manual_review.csv`, marking each correct, wrong, stale or unverifiable. See *Accuracy spot-check*.

## Results

| Metric | Bright Data | Tavily |
|---|---|---|
| Valid JSON | 95% (19/20) | 100% |
| Companies with ≥1 recent signal | 90% | 95% |
| Total signals | 89 | 130 |
| Avg signals per company | 4.5 | 6.5 |
| Dated | 76% | 62% |
| **Recent (≤90 days)** | **72% (64 signals)** | **57% (74 signals)** |
| Grounded | 99% | 99% |
| Avg searches used | 3.9 | 3.8 |
| Avg LLM input tokens per company | 8,690 | 15,771 |
| Avg LLM output tokens per company | 1,322 | 1,635 |
| Median time per search | 12.7s (5.6–29.5) | 2.1s (1.4–2.7) |
| Median total time per company | 62.4s | 23.3s |
| Failed searches | 5 of 78 (6%) | 0 of 75 |

Bright Data's failed searches came in the Chobani, Cohere, Crusoe, Glean and Ramp runs. Each failed once, and in every case the agent recovered and still answered.

**Head-to-head on recent signals:** Tavily found more in 11 companies, Bright Data in 7, and 2 were ties.

**By segment (recent signals):**

| Segment | Bright Data | Tavily |
|---|---|---|
| large_tech | 13 | 15 |
| growth_startup | 35 | 44 |
| non_tech | 16 | 15 |

Tavily's coverage advantage comes almost entirely from growth startups. On non-tech brands the two were level.

**Companies with zero recent signals:** Bright Data had two, Allbirds and Clay. Tavily had one, Glean.

**The Clay failure was a formatting error, not a search failure.** The Bright Data Clay run did find 5 dated, recent, grounded signals: the $115M Series D, a tender offer, the Marketbridge partnership and two hiring signals. But the model left out one closing quote mark at the end of its JSON, so the parser rejected the whole answer. The tables above count it as a failure, exactly as measured. If it is repaired, Bright Data's totals become **69 recent signals (73% of 94)**, and the head-to-head becomes 10 companies for Tavily, 8 for Bright Data and 2 ties. That makes it a harness issue (fix: structured output or a JSON-repair retry), not a backend difference.

### Estimated cost per useful signal

| | Bright Data | Tavily |
|---|---|---|
| Search API, list price | $1.50 per 1K requests (PAYG) | $0.008 per credit (1 credit per basic search) |
| Search cost, full run | $0.12 | $0.60 |
| LLM cost, full run* | $0.61 | $0.96 |
| **Total, full run** | **$0.73** | **$1.56** |
| Per company | $0.036 | $0.078 |
| **Per recent signal** | **$0.011** | **$0.021** |

\*LLM cost is an estimate at the Claude Sonnet 5.5 list price ($2 per 1M input tokens, $10 per 1M output tokens), the model used in this eval. It uses the token counts measured in this run, and the ratio between backends holds at any per-token price. Anthropic’s Batch API halves the LLM price, which suits the scheduled, batch workload this positioning targets. Actual spend for this test was $0 on both search APIs because it fit inside the free tiers (Bright Data: 5K requests per month; Tavily: 1,000 credits per month).

**Why Bright Data is cheaper:** the search call itself costs about 5× less, and Google snippets are short, so the model reads about 45% fewer input tokens. At scale (for example, 10K accounts refreshed weekly), that gap compounds. **Why Tavily finds more:** its results carry longer, content-rich snippets, so each search gives the model more facts to extract. That also explains the lower share of dated and recent signals: more background and undated items get through.

## Observations from the side-by-side outputs

See `results/v1/side_by_side.md` for every company.

- **Each backend found things the other missed.**
  - Bright Data alone found ElevenLabs' first CRO hire and new Singapore office.
  - Tavily alone found the Allbirds rebrand, new CEO and Q2 earnings, Runway's Kinetix acquisition and its Solaris and Ads launches, Columbia Sportswear's 10-year GXO deal, and Peloton's FY26 results.
  - For a sales team, the union of the two is better than either one alone.
- **Bright Data surfaced more primary sources where they exist.** For Vercel, all 7 signals came from vercel.com blog and changelog pages and were dated. For Supabase it cited the PR Newswire release and Supabase's own blog. Tavily leaned more on aggregators (Tracxn, stockanalysis.com, Instagram, Digg), so its notes often said "verify before citing."
- **Both backends returned low-quality social sources** (Facebook pages, X posts, Instagram) with no dates. The agent mostly flagged these as lower confidence rather than dropping them.
- **Dates are the weak point for both.** Many Google results carry only relative dates ("2 days ago"), which the agent rightly left as null. Tavily often had no date at all.
- **Bright Data returned a Google redirect URL as a source** (Ramp: `google.com/goto?url=...`) instead of the publisher URL. It still counts as "grounded" because it came from the tool results, but a seller can't use it as a citation.
- **Ambiguous names needed qualifiers on both backends.** For Clay, Ramp and Runway, the agent added terms ("clay.com", "fintech", "AI video") to its queries to avoid results about clay the material, ramps or fashion runways. It managed this without help, but it costs part of a small search budget.
- **Both handled a hard case well.** For Vacasa, both explained that it is now owned by Casago and franchised out, and told the seller to target Casago and local operators. That is exactly the context a rep needs.

## Accuracy spot-check

I opened the source for 10 signals: 5 per backend, as matched pairs from the same five companies (Chobani, Columbia Sportswear, Rippling, Vacasa, Vercel). I marked each as correct, wrong, stale (older than 90 days) or unverifiable. Verdicts and notes are in `results/v1/manual_review.csv`.

| Backend | Correct | Wrong | Stale | Unverifiable |
|---|---|---|---|---|
| Bright Data | 5 / 5 | 0 | 0 | 0 |
| Tavily | 4 / 5 | 0 | 0 | 1 (LinkedIn job page wouldn't load) |

- **No wrong or stale signals on either backend.** Combined with 99% grounding, that suggests the agent's main failure mode is *missing* information, not inventing it.
- **"Undated" signals were actually recent.** Three of the checked signals had no date: Chobani (Tavily), Rippling (Bright Data) and Rippling (Tavily). In all three, the source page showed a publication date inside the window (13 Oct, 23 Sep and 15 Oct 2026). The date was on the page but not in the search snippet. So the "dated" and "recent" metrics above *understate* true recency for both backends. A page fetch on undated results, or a date field returned by the search API, would recover it.
- **Login-walled sources are a risk.** The one unverifiable signal cited a LinkedIn page a seller may not be able to open.
- Ten signals is a small sample. It checks for gross errors; it doesn't measure accuracy rates.

## Limitations

- **Small sample, single run.** 20 companies, run once. The model doesn't accept a temperature setting, so a re-run would give slightly different outputs. The differences above are directional, not statistically tested.
- **Bright Data defaults were not tuned.** I used synchronous requests, the Full JSON format, `num=10` trimmed to 5, and US/English. I did not test Light JSON, async mode, other parsers or zones. Some or much of the latency gap may be configuration.
- **Snippets only.** Page fetches were off (`--max-fetches 0`), so both backends were judged on search results alone. Bright Data's Web Unlocker and Tavily Extract are wired in but untested.
- **Tavily ran on basic depth and the general topic.** Advanced depth or the news topic could change its results.
- **Automated metrics are proxies.** "Grounded" checks that a URL came from the tool results, not that the claim is true. "Recent" depends on the date the agent assigned. The manual spot-check covers only 10 signals.
- **One run was redone.** My laptop slept during the Cohere Bright Data run, which inflated its time. I deleted that result and re-ran it. The re-run's time (about 100s) is in the tables.
- **Cost figures use list prices** and an assumed LLM token price. They are not a billing comparison.
- **The JSON parsing is strict.** One malformed answer (Clay on Bright Data) was scored as a total miss. The next version would use structured outputs or retry on a parse error.
- **Free tiers only,** as the brief required. Nothing in this test hit a free-tier limit.

## Implications

### Product

1. **Latency and variance are the first objection.** A 12.7s median, a 29.5s worst case and a 6% failure rate rule out interactive agents. If Light JSON or async closes the gap, that needs to be the default in agent-facing docs and SDKs.
2. **Return publisher URLs, not Google redirects,** and add a normalized absolute date field (convert "2 days ago" into a date). Agents need citations and dates more than they need ranking. The spot-check showed every undated signal checked was actually recent, with the date sitting on the page. A built-in "SERP + fetch top result for its date" option (SERP API plus Web Unlocker) would turn that into a measurable win.
3. **Disambiguation helpers for entity search.** A domain-anchored mode (a company plus `ramp.com` hint) would save the searches the agent spent disambiguating Clay, Ramp and Runway.
4. **Onboarding friction for developers on Windows.** The dashboard's Windows snippet runs only in cmd, not PowerShell. The bracketed key placeholder and the missing "Bearer" prefix each cost me a failed call.

### Marketing

1. **Segment:** builders of GTM and sales-intelligence agents (AI SDR tools, enrichment platforms, CRM copilots) that research thousands of accounts on a schedule. In that workload nobody waits on a single search, and cost per signal and precision decide the bill. This matches the "owned context compounds" thesis: research once in batch, store it, and refresh it.
2. **Positioning to test:** *"The cheapest dated, primary-source signal for account research at scale"* rather than "the fastest search API for agents." The evidence supports roughly 45% lower cost per useful signal and higher precision, with honest latency caveats.
3. **Proof assets:** publish this eval harness as an open benchmark builders can run on their own account lists. Credibility in this segment comes from reproducible numbers, not claims.
4. **Objections to prepare for:** "too slow for my agent" (answer: batch architecture plus async), "Tavily gives me more per call" (answer: more tokens and more undated items; compare on cost per recent signal), and "Google snippets are too thin" (answer: pair SERP with Web Unlocker fetches on the top results).

## Reproduce

```
python run_eval.py --backends brightdata tavily --run-id v1
python summarize.py --run-id v1
```

Raw outputs for every company and backend are in `results/v1/`.
