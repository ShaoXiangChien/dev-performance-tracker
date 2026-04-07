# Implementation Plan

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI / Scheduler                          │
│  (python commands to run collection, analysis, and reporting)   │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────┐ ┌────────────────┐ ┌────────────────────────┐
│  Data Collector   │ │  LLM Analyzer   │ │  Report Generator      │
│                   │ │                 │ │                        │
│  GitHub API →     │ │  Diffs →        │ │  Metrics + LLM output  │
│  pr_raw.json      │ │  quality.json   │ │  → markdown/HTML       │
│                   │ │                 │ │    reports             │
│  Quantitative     │ │  Comments →     │ │                        │
│  metrics →        │ │  classified.json│ │  Team report           │
│  pr_summary.json  │ │                 │ │  Individual reports    │
└──────────────────┘ └─────────────────┘ └────────────────────────┘
           │                  │                  │
           └──────────────────┼──────────────────┘
                              ▼
                    ┌───────────────────┐
                    │    Data Store      │
                    │  (JSON files or    │
                    │   SQLite for       │
                    │   historical data) │
                    └───────────────────┘
```

## Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Already started, user preference |
| GitHub API client | `requests` | Already working, sufficient for REST API |
| LLM | Anthropic Claude API (`anthropic` SDK) | Best reasoning for code review tasks |
| Data store (Phase 1) | JSON files | Simple, no dependencies, easy to inspect |
| Data store (Phase 2+) | SQLite | Needed for historical trend queries |
| Report output | Markdown → HTML | Readable as-is, convertible for web/email |
| CI integration (Phase 3) | GitHub Actions | Native to GitHub workflow |

## Phases

### Phase 1: Foundation (Data + Quantitative Metrics)

**Goal:** Complete the data collection pipeline and compute all non-LLM metrics.

**Tasks:**

1. **Update data collector to include diff patches**
   - Add `patch` field to files data in `pr_raw.json`
   - Add `body` field (PR description) to raw data
   - Handle large diffs: skip files > 10,000 lines, skip binary files
   - File: `collect_pr_data.py` (update existing)

2. **Add PR deduplication logic**
   - Detect PRs that share the same `head.ref` (branch name)
   - Keep only the final PR (latest `created_at`) for metric computation
   - Mark earlier ones as `is_reopen: true` in raw data

3. **Filter bots from developer metrics**
   - Detect bot accounts: username ends with `[bot]`, or `author_association` patterns
   - Exclude from author metrics, keep their review comments as data source for quality analysis
   - Configurable bot list in a config file

4. **Compute quantitative metrics**
   - A1: PR merge rate (with dedup)
   - A2: Cycle time distribution (p50/p75/p95)
   - A3: PR size distribution
   - A4: Net code change
   - B1: Review load
   - B3: Review turnaround (team-level)
   - B4: Review rounds
   - C1: Knowledge distribution
   - C2: Review network
   - C3: Review coverage
   - File: `compute_metrics.py` (new)

5. **Output: `metrics.json`**
   - Team-level metrics
   - Per-developer metrics
   - Per-PR metrics (for drill-down)

**Estimated API cost:** 0 (GitHub API only, no LLM)
**Estimated effort:** 2-3 sessions

---

### Phase 2: LLM Analysis

**Goal:** Add LLM-powered code quality analysis and review comment classification.

**Tasks:**

1. **Review comment classification (B2)**
   - Input: all review comments from `pr_raw.json`
   - LLM classifies each into: bug_catch / security / performance / architecture / test_gap / style_nit / question / praise
   - Batch processing: group comments by PR, send one prompt per PR
   - File: `analyze_reviews.py` (new)
   - Output: `review_classifications.json`

2. **PR code quality analysis (D1-D3)**
   - Input: diff patches from `pr_raw.json`
   - Three analysis dimensions: conciseness, self-review signals, firmware concerns
   - Per-file analysis, aggregated per-PR
   - Skip non-code files (markdown, config, lock files, images)
   - File: `analyze_quality.py` (new)
   - Output: `quality_analysis.json`

3. **Prompt engineering and calibration**
   - Write prompts for each analysis dimension (templates in `prompts/` directory)
   - Manual calibration: run on 10 sample PRs, compare LLM output with human judgment
   - Tune prompts until classification agreement > 85%
   - Document prompt versions for reproducibility

4. **Cost management**
   - Track token usage per analysis run
   - Configurable: choose model (sonnet/haiku) per dimension
   - Configurable: skip quality analysis for PRs below a size threshold (e.g., < 20 lines changed)
   - Estimated cost: ~$0.02-0.05 per PR with Sonnet, ~$5-10/month for a team of 10

**Estimated effort:** 3-4 sessions

---

### Phase 3: Reporting

**Goal:** Generate human-readable reports from metrics + LLM analysis.

**Tasks:**

1. **Team health report generator**
   - Input: `metrics.json` + `quality_analysis.json` + `review_classifications.json`
   - Output: markdown report following the template in 03-metrics-design.md
   - Configurable time window (sprint / week / month)
   - File: `generate_team_report.py` (new)

2. **Individual growth report generator**
   - Input: same data, filtered to one developer
   - Output: markdown report with personal metrics + growth trends
   - Requires historical data (compare current window to previous)
   - File: `generate_individual_report.py` (new)

3. **LLM narrative generation**
   - Use LLM to generate the "Growth Highlights" and "Suggested Actions" sections
   - Input: the quantitative trends + quality analysis trends for the time window
   - This is a summarization task, not analysis — cheaper and faster

4. **Historical data storage**
   - Move from flat JSON files to SQLite for trend queries
   - Schema: PRs table, metrics_snapshots table, quality_scores table
   - Migration script from existing JSON files
   - File: `store.py` (new)

**Estimated effort:** 2-3 sessions

---

### Phase 4: CI Integration (Optional)

**Goal:** Real-time quality feedback on PR submission.

**Tasks:**

1. **GitHub Action workflow**
   - Trigger: `pull_request` event (opened, synchronize)
   - Fetch diff from the PR (available directly in the action context)
   - Run conciseness + self-review analysis
   - Post results as a PR comment

2. **Comment formatting**
   - Non-threatening tone: "Here are some suggestions before review"
   - Collapsible sections for details
   - Clear distinction between severity levels
   - Link to team conventions doc where applicable

3. **Secret management**
   - Anthropic API key stored as GitHub secret
   - GitHub token available as `GITHUB_TOKEN` in actions

4. **Cost control**
   - Only analyze changed files > 10 lines
   - Rate limit: max 1 analysis per PR per hour (debounce rapid pushes)
   - Budget alert: stop if monthly spend exceeds threshold

**Estimated effort:** 2 sessions

---

## File Structure (Target)

```
dev-performance-tracker/
├── .env.example
├── .env                          # (gitignored)
├── requirements.txt
├── config.yaml                   # repo list, bot filters, model choice, thresholds
│
├── docs/
│   ├── 01-project-overview.md
│   ├── 02-available-data.md
│   ├── 03-metrics-design.md
│   ├── 04-code-quality-analysis.md
│   └── 05-implementation-plan.md
│
├── prompts/                      # LLM prompt templates (version-controlled)
│   ├── review_classification.txt
│   ├── conciseness_review.txt
│   ├── self_review_signals.txt
│   └── firmware_concerns.txt
│
├── src/
│   ├── collector.py              # GitHub API data collection
│   ├── metrics.py                # Quantitative metric computation
│   ├── analyze_reviews.py        # LLM review comment classification
│   ├── analyze_quality.py        # LLM code quality analysis
│   ├── report_team.py            # Team health report generation
│   ├── report_individual.py      # Individual growth report generation
│   └── store.py                  # Data persistence (JSON → SQLite)
│
├── data/                         # (gitignored)
│   ├── raw/                      # Raw API responses per run
│   ├── analysis/                 # LLM analysis outputs per run
│   └── reports/                  # Generated reports
│
├── explore_pr_fields.py          # (existing) API exploration script
├── explore_rate_limits.py        # (existing) Rate limit checker
└── collect_pr_data.py            # (existing) Will be refactored into src/collector.py
```

## Configuration

```yaml
# config.yaml
github:
  repos:
    - owner/repo-name
  lookback_days: 90
  max_prs_per_run: 500

bots:
  # Accounts to exclude from developer metrics (but keep their review data)
  - "dependabot[bot]"
  - "renovate[bot]"
  - "copilot-pull-request-reviewer[bot]"
  - "Copilot"

analysis:
  llm_model: "claude-sonnet-4-6"       # or claude-haiku-4-5 for cost savings
  skip_files:
    - "*.lock"
    - "*.min.js"
    - "*.generated.*"
    - "package-lock.json"
    - "yarn.lock"
    - "poetry.lock"
  min_pr_size_for_quality_analysis: 20  # skip trivial PRs (< 20 lines changed)
  dimensions:
    conciseness: true
    self_review: true
    firmware_concerns: true             # set false for non-firmware teams

reporting:
  team_report_cadence: "weekly"         # or "sprint" with sprint_length_days
  individual_report_cadence: "monthly"
  domain_context: "Firmware / embedded systems, C and Python"
```

## Dependencies

```
# requirements.txt (Phase 2+)
requests==2.32.3
python-dotenv==1.0.1
anthropic>=0.42.0        # Claude API SDK
pyyaml>=6.0              # Config file parsing
jinja2>=3.1              # Report template rendering
```

## Risk & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| LLM hallucinating quality issues | False accusations of poor code quality | Conservative prompting ("if unsure, don't flag"), manual calibration on sample data, confidence scores on each issue |
| Manager weaponizing metrics | Developer morale damage, attrition | Individual reports go to the developer only. Team report shows aggregates. No ranked lists. Design principles enforced in report templates. |
| GitHub API rate limits | Incomplete data collection | Built-in rate limit handling (sleep and retry). Incremental collection (only fetch new PRs since last run). |
| LLM cost overrun | Budget surprise | Per-run cost tracking. Configurable model tier. Skip threshold for small PRs. Monthly budget cap. |
| Prompt drift across LLM model versions | Inconsistent scoring over time | Version-control prompts. Pin model version in config. Re-calibrate on model upgrade. |
| Small team size (< 5 devs) | Metrics become identifiable even in "team" reports | Minimum team size warning. For very small teams, focus on team-level metrics only and skip individual breakdowns. |
