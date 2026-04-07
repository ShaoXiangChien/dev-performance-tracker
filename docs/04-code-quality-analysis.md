# LLM-Powered Code Quality Analysis

## Motivation

AI-assisted coding tools are widely adopted and should be encouraged. The problem is not the tool — it's the absence of self-review. Developers sometimes submit AI-generated code without critically evaluating it for:

- Unnecessary complexity and verbosity
- Inconsistency with project conventions
- Dead code and orphaned definitions
- Resource efficiency (critical in firmware)

This analysis module uses an LLM to review PR diffs and produce structured quality assessments. It explicitly does **not** attempt to detect whether code was written by AI or by a human. It evaluates output quality regardless of origin.

## Data Input

For each PR, the analysis requires:

```
- PR title and body (scope context)
- File patches from the files endpoint (actual diff content)
- Existing review comments (to avoid duplicating feedback already given)
- Repository language / domain context (e.g., "firmware, C/C++, embedded Linux")
```

The `patch` field from `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` provides unified diff content for each changed file. This is the primary input for analysis.

### Collecting Patch Data

The current `collect_pr_data.py` must be updated to include the `patch` field in the files data. Each file object from the API includes:

```json
{
  "filename": "src/drivers/uart.c",
  "status": "modified",
  "additions": 45,
  "deletions": 12,
  "patch": "@@ -100,6 +100,20 @@ void uart_init(uart_config_t *config) {\n+    // ... actual diff lines ..."
}
```

## Analysis Dimensions

### Dimension 1: Conciseness

**What we're looking for:**

| Pattern | Description | Severity | Why it matters in firmware |
|---|---|---|---|
| Unnecessary abstraction | Functions/classes wrapping a single call, used only once | Medium | Extra call overhead, code size bloat |
| Code duplication | Copy-pasted logic with minor variations | Medium | Maintenance burden, binary size |
| Over-defensive coding | Try-catch / null-check for conditions that structurally cannot occur | Low-Medium | Code size, readability; in hot paths, also performance |
| Verbose comments | Comments restating what the code obviously does (e.g., `// increment counter` above `counter++`) | Low | Noise that hurts readability, often a sign of unreviewed AI output |
| Unused imports/includes | Headers or modules imported but never referenced | Low | Compilation time, potential namespace pollution |
| Reimplemented utilities | Hand-rolling something that an existing project utility or standard library already does | Medium | Maintenance burden, potential bugs vs. tested utility |

**LLM prompt structure:**

```
You are reviewing a code diff for a firmware project. Analyze the ADDED lines
(lines starting with +) for conciseness issues.

For each issue found, report:
- file: the filename
- line_context: the relevant code snippet (keep short)
- pattern: one of [unnecessary_abstraction, duplication, over_defensive,
           verbose_comments, unused_import, reimplemented_utility]
- description: one sentence explaining the issue
- suggestion: one sentence suggesting improvement
- severity: low / medium / high

If the code is concise and well-written, explicitly say so. Do not invent issues
that aren't there. False positives are worse than missed issues.

Context:
- Project domain: {domain_context}
- Files changed in this PR: {file_list}

Diff to analyze:
{patch_content}
```

### Dimension 2: Self-Review Signals

This is the key dimension for the AI-dumping concern. These patterns suggest the author submitted code without critically reading through it.

| Signal | Description | What it indicates |
|---|---|---|
| Orphaned code | Functions, variables, or type definitions that are defined but never called/used within the PR | Author didn't trace through the code paths |
| Style inconsistency | Mixed naming conventions (camelCase + snake_case), inconsistent indentation, different error handling patterns within the same PR | Code assembled from different sources without normalization |
| Contradictory logic | A flag is set but never checked, a variable is assigned then immediately overwritten, dead branches in conditionals | Author didn't walk through the logic |
| TODO / FIXME / HACK comments | Placeholder comments submitted in non-draft PRs | Author submitted unfinished work without flagging it |
| Inconsistency with PR description | PR body says one thing, code does another (e.g., "returns 404" but code returns 403) | Author didn't reconcile implementation with spec |
| Generic variable names | `data`, `result`, `temp`, `val` in non-trivial scopes | Often a sign of generated code that the author didn't rename for clarity |

**LLM prompt structure:**

```
You are reviewing a code diff to assess whether the author appears to have
carefully self-reviewed the code before submitting.

You are NOT trying to detect AI-generated code. You are looking for signals
that the code was submitted without careful self-review, regardless of how
it was written.

For each signal found, report:
- signal_type: one of [orphaned_code, style_inconsistency, contradictory_logic,
               todo_submitted, description_mismatch, generic_names]
- location: file and relevant line context
- description: one sentence explaining what looks unreviewed
- confidence: low / medium / high (how confident are you this wasn't intentional?)

Be conservative. If something might be intentional, mark it low confidence.
Code that is clean and consistent should receive explicit positive acknowledgment.

PR title: {title}
PR description: {body}

Diff:
{patch_content}
```

### Dimension 3: Firmware-Specific Concerns

Applicable when the project is firmware, embedded systems, or performance-critical code. This dimension should be configurable — not every team needs it.

| Concern | Description | Impact |
|---|---|---|
| Unnecessary heap allocation | Using `malloc`/`new`/dynamic allocation where a stack variable or static buffer suffices | Memory fragmentation, allocation failure risk |
| Missing resource cleanup | Opening a handle/file/peripheral without corresponding close/release on all code paths | Resource leak in long-running embedded systems |
| Excessive stack usage | Large local arrays or struct copies in functions (especially in deep call chains) | Stack overflow in memory-constrained environments |
| Unnecessary dependency | Including a heavy header/library for a small utility that could be trivially inlined | Binary size bloat |
| Busy-wait patterns | Polling loops without yield/sleep in non-ISR context | CPU waste, power consumption |
| Non-atomic shared state access | Reading/writing shared state (globals, peripherals) without proper synchronization | Race conditions in interrupt/RTOS contexts |

**LLM prompt structure:**

```
You are a firmware code reviewer. Analyze the following diff for embedded systems
/ firmware-specific concerns.

Focus on:
1. Memory management: unnecessary heap allocation, missing frees, stack overflow risk
2. Resource management: unclosed handles, leaked peripherals
3. Performance: busy-waits, unnecessary copies, heavy dependencies
4. Concurrency: unprotected shared state, missing volatile/atomic qualifiers

For each concern, report:
- file and line context
- concern_type: one of [heap_allocation, resource_leak, stack_usage,
                unnecessary_dependency, busy_wait, shared_state]
- description: what the issue is
- severity: low / medium / high / critical
- suggestion: how to fix it

Do not flag patterns that are standard practice for the target platform.
Only flag things that are genuinely concerning for production firmware.

Target platform context: {platform_context}

Diff:
{patch_content}
```

## Output Schema

Each PR's quality analysis produces:

```json
{
  "pr_number": 13,
  "author": "dev_username",
  "analyzed_at": "2026-04-05T10:00:00Z",
  "file_count_analyzed": 6,
  "total_additions_analyzed": 757,

  "conciseness": {
    "score": 3,
    "issue_count": 4,
    "issues": [
      {
        "file": "app/services/wake_event_service.py",
        "line_context": "sync_redis.from_url(settings.REDIS_URL)",
        "pattern": "reimplemented_utility",
        "description": "New Redis client created per call instead of reusing a module-level connection pool.",
        "suggestion": "Create a module-level Redis client and reuse it across function calls.",
        "severity": "medium"
      }
    ]
  },

  "self_review": {
    "score": 3,
    "issue_count": 2,
    "issues": [
      {
        "signal_type": "description_mismatch",
        "location": "tests/api/test_wake_events.py:410",
        "description": "PR description states wrong-owner access returns 404, but test asserts 403.",
        "confidence": "high"
      },
      {
        "signal_type": "orphaned_code",
        "location": "app/workers/escalation_tasks.py:36",
        "description": "_save_job_c_id writes to Redis but the key is never read anywhere in the codebase.",
        "confidence": "medium"
      }
    ]
  },

  "firmware_concerns": {
    "score": 4,
    "issue_count": 1,
    "issues": [
      {
        "file": "app/workers/escalation_tasks.py",
        "concern_type": "resource_leak",
        "description": "Redis client created in function scope but not closed in error paths.",
        "severity": "medium",
        "suggestion": "Use a context manager or try-finally to ensure connection cleanup."
      }
    ]
  },

  "summary": "PR introduces a state machine for wake events with Celery scheduling. Key concerns: (1) Redis client lifecycle management — creating per-call clients instead of reusing a pool, (2) PR description and test assertions contradict each other on error codes, (3) One Redis key is written but never read, suggesting incomplete implementation or leftover code. Overall the logic is sound but the code would benefit from a self-review pass before submission."
}
```

## Scoring Methodology

Each dimension is scored 1-5:

| Score | Meaning |
|---|---|
| 5 | Clean — no issues found, code is well-crafted |
| 4 | Good — minor issues only (low severity) |
| 3 | Fair — some medium-severity issues that should be addressed |
| 2 | Needs improvement — multiple medium or high-severity issues |
| 1 | Poor — significant issues suggesting insufficient review before submission |

**Important:** Scores are calibrated per-dimension, not compared across dimensions. A conciseness score of 3 and a firmware score of 3 mean different things. Do not average them into a single "quality score" — composite scores lose meaning and invite misuse.

## Aggregation for Reporting

### Team-level (weekly/sprint)

```
- Average conciseness score across all PRs: 3.8
- PRs flagged (score ≤ 2 on any dimension): 2/12
- Most common conciseness pattern: "over_defensive" (appeared in 4 PRs)
- Most common self-review signal: "verbose_comments" (appeared in 3 PRs)
  → Suggested team action: discuss commenting conventions
```

### Individual-level (monthly, shown to developer only)

```
- Your average conciseness: 3.5 (team: 3.8)
- Your average self-review: 3.0 (team: 3.6)
- Recurring pattern: "generic_names" appeared in 3 of your 5 PRs
  → Suggestion: rename variables to reflect their domain purpose before submitting
- Improvement: no "orphaned_code" signals this month (was flagged twice last month) ✓
```

## LLM Selection and Cost

| Concern | Approach |
|---|---|
| **Model choice** | Claude Sonnet recommended for cost/quality balance. Opus for critical repos. Haiku for high-volume, low-stakes. |
| **Cost estimate** | ~2,000-5,000 input tokens per PR diff + ~500 output tokens per dimension. At 3 dimensions per PR: ~$0.01-0.05 per PR with Sonnet. For 200 PRs/month: ~$2-10/month. |
| **Consistency** | Use temperature 0 for scoring. Include 2-3 few-shot examples in each prompt for calibration. |
| **Context window** | Large PRs may exceed context limits. Strategy: analyze per-file, then aggregate. Skip binary files and lock files. |
| **Rate limiting** | Batch analysis: run nightly or on-demand, not on every PR push. For CI integration, run only on PR open/update events. |

## CI Integration (Optional, Phase 2)

For teams that want real-time feedback, the analysis can run as a GitHub Action:

```
PR opened/updated
    → GitHub Action triggers
    → Fetch diff from the PR
    → Run LLM analysis (conciseness + self-review)
    → Post results as a PR comment (like a bot reviewer)
    → Author can address issues before human review
```

Benefits:
- Issues caught before reviewer spends time
- Author gets feedback immediately, not in a monthly report
- Normalizes quality feedback (it's from the tool, not from a colleague criticizing them)
- Reviewer can focus on architecture/logic, not style/conciseness

This is the most impactful deployment mode for the "AI-dumped code" problem — the feedback loop is immediate, not retrospective.
