"""Turn a run's raw outputs into comparison tables.

    python summarize.py --run-id v1

Writes to results/<run-id>/:
    summary.md          per-backend averages (the headline comparison)
    per_company.csv     one row per company x backend
    side_by_side.md     what each backend's agent reported, company by company (for reading)
    manual_review.csv   one row per signal, with a blank 'verdict' column for hand-checking accuracy

Automatic metrics (no human judgment needed):
    answered       agent returned valid JSON
    signals        number of signals reported
    dated %        signals that carry a date
    recent %       signals dated within the window (default 90 days) of the run date
    grounded %     signals whose source_url actually appeared in that run's tool results
                   (a low number means the model cited URLs it never saw)
    searches / fetches / tokens / time   cost and speed proxies
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import statistics


def norm(url):
    return (url or "").split("#")[0].rstrip("/").lower()


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def score(result, window_days):
    ans = result.get("answer") or {}
    signals = ans.get("signals") or []
    run_date = parse_date(result.get("run_date")) or dt.date.today()
    seen = {norm(u) for u in result.get("seen_urls", [])}
    dated = [s for s in signals if parse_date(s.get("date"))]
    recent = [s for s in dated if 0 <= (run_date - parse_date(s["date"])).days <= window_days]
    grounded = [s for s in signals if norm(s.get("source_url")) in seen]
    m = result.get("metrics", {})
    return {
        "company": result.get("company"),
        "segment": result.get("segment"),
        "backend": result.get("backend"),
        "answered": int(bool(result.get("answer"))),
        "signals": len(signals),
        "dated": len(dated),
        "recent": len(recent),
        "grounded": len(grounded),
        "searches": m.get("searches", 0),
        "fetches": m.get("fetches", 0),
        "input_tokens": m.get("input_tokens", 0),
        "output_tokens": m.get("output_tokens", 0),
        "wall_time_s": m.get("wall_time_s", 0),
        "search_api_time_s": m.get("search_api_time_s", 0),
        "tool_errors": m.get("tool_errors", 0) + (1 if result.get("fatal_error") else 0),
        "confidence": ans.get("overall_confidence"),
    }


def pct(num, den):
    return f"{100 * num / den:.0f}%" if den else "n/a"


def mean(values):
    values = list(values)
    return statistics.mean(values) if values else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--window-days", type=int, default=90)
    args = p.parse_args()
    root = os.path.join("results", args.run_id)

    rows, results = [], []
    for path in sorted(glob.glob(os.path.join(root, "*", "*.json"))):
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        results.append(r)
        rows.append(score(r, args.window_days))
    if not rows:
        raise SystemExit(f"No results found in {root}")

    backends = sorted({r["backend"] for r in rows})

    # --- per_company.csv
    with open(os.path.join(root, "per_company.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # --- summary.md
    lines = [f"# Run {args.run_id}: backend comparison", "",
             f"Window for 'recent': {args.window_days} days before the run date.", "",
             "| Metric | " + " | ".join(backends) + " |",
             "|---|" + "---|" * len(backends)]

    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(fn([r for r in rows if r["backend"] == b]) for b in backends) + " |")

    row("Companies run", lambda rs: str(len(rs)))
    row("Answered with valid JSON", lambda rs: pct(sum(r["answered"] for r in rs), len(rs)))
    row("Companies with >=1 recent signal", lambda rs: pct(sum(1 for r in rs if r["recent"] > 0), len(rs)))
    row("Avg signals per company", lambda rs: f"{mean(r['signals'] for r in rs):.1f}")
    row("Signals with a date", lambda rs: pct(sum(r["dated"] for r in rs), sum(r["signals"] for r in rs)))
    row("Signals dated in window (recent)", lambda rs: pct(sum(r["recent"] for r in rs), sum(r["signals"] for r in rs)))
    row("Signals grounded in tool results", lambda rs: pct(sum(r["grounded"] for r in rs), sum(r["signals"] for r in rs)))
    row("Avg searches per company", lambda rs: f"{mean(r['searches'] for r in rs):.1f}")
    row("Avg page fetches per company", lambda rs: f"{mean(r['fetches'] for r in rs):.1f}")
    row("Avg LLM input tokens", lambda rs: f"{mean(r['input_tokens'] for r in rs):,.0f}")
    row("Avg LLM output tokens", lambda rs: f"{mean(r['output_tokens'] for r in rs):,.0f}")
    row("Avg search API time (s)", lambda rs: f"{mean(r['search_api_time_s'] for r in rs):.1f}")
    row("Avg total time per company (s)", lambda rs: f"{mean(r['wall_time_s'] for r in rs):.1f}")
    row("Runs with tool errors", lambda rs: str(sum(1 for r in rs if r["tool_errors"])))

    segments = sorted({r["segment"] for r in rows if r["segment"]})
    if segments:
        lines += ["", "## Companies with >=1 recent signal, by segment", "",
                  "| Segment | " + " | ".join(backends) + " |", "|---|" + "---|" * len(backends)]
        for seg in segments:
            cells = []
            for b in backends:
                rs = [r for r in rows if r["backend"] == b and r["segment"] == seg]
                cells.append(pct(sum(1 for r in rs if r["recent"] > 0), len(rs)))
            lines.append(f"| {seg} | " + " | ".join(cells) + " |")

    with open(os.path.join(root, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # --- side_by_side.md and manual_review.csv
    by_company = {}
    for r in results:
        by_company.setdefault(r.get("company"), {})[r.get("backend")] = r
    sbs = [f"# Side-by-side outputs: {args.run_id}", ""]
    review_rows = []
    for company in sorted(by_company):
        sbs.append(f"## {company}")
        for b in backends:
            r = by_company[company].get(b)
            if not r:
                continue
            ans = r.get("answer") or {}
            queries = [t.get("query") for t in r.get("trace", []) if t.get("tool") == "web_search"]
            sbs.append(f"**{b}**: queries: {queries}")
            for i, s in enumerate(ans.get("signals") or []):
                sbs.append(f"- [{s.get('type')}] {s.get('date')}: {s.get('summary')} ({s.get('source_url')})")
                review_rows.append({"company": company, "backend": b, "signal_no": i + 1,
                                    "type": s.get("type"), "date": s.get("date"),
                                    "summary": s.get("summary"), "source_url": s.get("source_url"),
                                    "verdict (correct/wrong/stale/unverifiable)": "", "reviewer_note": ""})
            if not ans.get("signals"):
                sbs.append("- (no signals reported)")
            if ans.get("notes"):
                sbs.append(f"  - notes: {ans.get('notes')}")
            sbs.append("")
    with open(os.path.join(root, "side_by_side.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(sbs) + "\n")
    if review_rows:
        with open(os.path.join(root, "manual_review.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(review_rows[0].keys()))
            w.writeheader()
            w.writerows(review_rows)

    print("\n".join(lines))
    print(f"\nWrote summary.md, per_company.csv, side_by_side.md, manual_review.csv to {root}")


if __name__ == "__main__":
    main()
