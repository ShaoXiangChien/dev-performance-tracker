"""
pipeline/llm_analysis.py
LLM-powered analysis using Claude API.
- Review comment classification (works without diffs)
- Code quality scoring: conciseness, self-review, firmware concerns (requires diffs)
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

SKIPPED_NO_DIFF = {
    "score": None,
    "issues": [],
    "skipped_reason": "no_diff_available",
    "summary": None,
}

SKIPPED_NO_COMMENTS = {
    "classifications": [],
    "skipped_reason": "no_review_comments",
}


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text()


def _call_claude(client, model: str, prompt: str) -> tuple[str, dict]:
    """Returns (raw_text, usage_dict)."""
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}
    return msg.content[0].text, usage


def _parse_json_response(text: str):
    """Extract JSON from LLM response, tolerating markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)


def _classify_review_comments(client, model: str, pr: dict) -> tuple[dict, dict]:
    """Classify all review comments for a PR. Returns (result, usage)."""
    all_comments = pr.get("review_comments", []) + pr.get("issue_comments", [])
    non_trivial = [
        c for c in all_comments
        if len(c.get("body", "").strip()) > 10
    ]

    if not non_trivial:
        return SKIPPED_NO_COMMENTS.copy(), {"input": 0, "output": 0}

    comments_text = "\n".join(
        f"[{i}] {c['author']}: {c['body'][:500]}"
        for i, c in enumerate(non_trivial)
    )

    prompt = _load_prompt("review_classification").format_map({
        "pr_title": pr.get("title", ""),
        "pr_author": pr.get("author", ""),
        "comments": comments_text,
    })

    raw, usage = _call_claude(client, model, prompt)
    classifications_raw = _parse_json_response(raw)

    classifications = []
    for item in classifications_raw:
        idx = item.get("index", 0)
        if idx < len(non_trivial):
            c = non_trivial[idx]
            classifications.append({
                "body": c["body"][:300],
                "author": c["author"],
                "category": item.get("category", "question"),
                "reason": item.get("reason", ""),
            })

    return {"classifications": classifications, "skipped_reason": None}, usage


def _analyze_quality_dimension(
    client, model: str, pr: dict, dimension: str
) -> tuple[dict, dict]:
    """Run one quality dimension analysis against the diff."""
    files = pr.get("files", [])
    if not files:
        return SKIPPED_NO_DIFF.copy(), {"input": 0, "output": 0}

    diff_text = ""
    files_summary = []
    for f in files[:20]:  # cap at 20 files
        files_summary.append(f"{f['filename']} (+{f['additions']}/-{f['deletions']})")
        patch = f.get("patch", "")
        if patch:
            diff_text += f"\n--- {f['filename']} ---\n{patch[:2000]}\n"

    if not diff_text.strip():
        return SKIPPED_NO_DIFF.copy(), {"input": 0, "output": 0}

    format_args = {
        "pr_title": pr.get("title", ""),
        "pr_author": pr.get("author", ""),
        "pr_description": pr.get("body", "") or "",
        "files_summary": ", ".join(files_summary),
        "diff": diff_text[:8000],
    }

    prompt = _load_prompt(dimension).format_map(format_args)
    raw, usage = _call_claude(client, model, prompt)
    result = _parse_json_response(raw)
    result.setdefault("skipped_reason", None)
    return result, usage


def analyze_prs(
    prs: list,
    api_key: str,
    model: str = "claude-sonnet-4-6",
    enable_firmware: bool = True,
    progress_callback=None,
    output_path: str = "data/llm_analysis.json",
) -> dict:
    """
    Run LLM analysis on a list of PR dicts.
    Returns analysis dict and writes to output_path.

    progress_callback(current, total, pr_number, stage) — called during processing.
    """
    client = anthropic.Anthropic(api_key=api_key)
    total = len(prs)
    results = []
    total_tokens = {"input": 0, "output": 0}

    for i, pr in enumerate(prs, 1):
        num = pr.get("number", i)
        has_diff = bool(pr.get("files"))

        if progress_callback:
            progress_callback(i, total, num, "classifying reviews")

        # Review comment classification
        try:
            rc_result, rc_usage = _classify_review_comments(client, model, pr)
        except Exception as e:
            rc_result = {"classifications": [], "skipped_reason": f"error: {e}"}
            rc_usage = {"input": 0, "output": 0}

        total_tokens["input"] += rc_usage["input"]
        total_tokens["output"] += rc_usage["output"]
        pr_tokens = {"input": rc_usage["input"], "output": rc_usage["output"]}

        # Code quality dimensions (only if diffs present)
        quality = {}
        dimensions = ["conciseness", "self_review"]
        if enable_firmware:
            dimensions.append("firmware_concerns")

        for dim in dimensions:
            if progress_callback:
                progress_callback(i, total, num, f"analyzing {dim}")
            try:
                dim_result, dim_usage = _analyze_quality_dimension(client, model, pr, dim)
            except Exception as e:
                dim_result = {**SKIPPED_NO_DIFF, "skipped_reason": f"error: {e}"}
                dim_usage = {"input": 0, "output": 0}

            quality[dim] = dim_result
            total_tokens["input"] += dim_usage["input"]
            total_tokens["output"] += dim_usage["output"]
            pr_tokens["input"] += dim_usage["input"]
            pr_tokens["output"] += dim_usage["output"]

        record = {
            "pr_number": num,
            "pr_title": pr.get("title", ""),
            "author": pr.get("author", ""),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "has_diff": has_diff,
            "review_classifications": rc_result.get("classifications", []),
            "conciseness": quality.get("conciseness", SKIPPED_NO_DIFF.copy()),
            "self_review": quality.get("self_review", SKIPPED_NO_DIFF.copy()),
            "firmware_concerns": quality.get(
                "firmware_concerns",
                {**SKIPPED_NO_DIFF, "skipped_reason": "disabled"} if not enable_firmware
                else SKIPPED_NO_DIFF.copy(),
            ),
            "tokens_used": pr_tokens,
        }
        results.append(record)

    output = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "pr_count": len(results),
        "total_tokens": total_tokens,
        "results": results,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output


def load_analysis(path: str = "data/llm_analysis.json") -> dict:
    with open(path) as f:
        return json.load(f)
