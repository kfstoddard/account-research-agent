# Run v1: backend comparison

Window for 'recent': 90 days before the run date.

| Metric | brightdata | tavily |
|---|---|---|
| Companies run | 20 | 20 |
| Answered with valid JSON | 95% | 100% |
| Companies with >=1 recent signal | 90% | 95% |
| Avg signals per company | 4.5 | 6.5 |
| Signals with a date | 76% | 62% |
| Signals dated in window (recent) | 72% | 57% |
| Signals grounded in tool results | 99% | 99% |
| Avg searches per company | 3.9 | 3.8 |
| Avg page fetches per company | 0.0 | 0.0 |
| Avg LLM input tokens | 8,690 | 15,771 |
| Avg LLM output tokens | 1,322 | 1,635 |
| Avg search API time (s) | 59.8 | 7.8 |
| Avg total time per company (s) | 72.7 | 22.5 |
| Runs with tool errors | 5 | 0 |

## Companies with >=1 recent signal, by segment

| Segment | brightdata | tavily |
|---|---|---|
| growth_startup | 91% | 91% |
| large_tech | 100% | 100% |
| non_tech | 80% | 100% |
