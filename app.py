import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from pipeline import collector, metrics as metrics_pipeline, llm_analysis, reports

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
load_dotenv()
Path("data/reports").mkdir(parents=True, exist_ok=True)
st.set_page_config(
    page_title="Dev Performance Tracker",
    layout="wide",
    page_icon="📊",
)


# ---------------------------------------------------------------------------
# Helper: Review Network Figure
# ---------------------------------------------------------------------------
def _build_review_network_fig(network: list, by_developer: dict) -> go.Figure:
    """Build a directed graph visualization for the review network."""
    devs = [d for d, info in by_developer.items() if not info.get("is_bot")]
    if not devs or not network:
        return None

    n = len(devs)
    pos = {
        dev: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i, dev in enumerate(devs)
    }

    fig = go.Figure()

    # Draw edges as lines
    max_count = max(e["count"] for e in network) if network else 1
    for edge in network:
        frm, to = edge["from"], edge["to"]
        if frm not in pos or to not in pos:
            continue
        x0, y0 = pos[frm]
        x1, y1 = pos[to]
        width = 1 + 4 * edge["count"] / max_count
        fig.add_trace(
            go.Scatter(
                x=[x0, x1, None],
                y=[y0, y1, None],
                mode="lines",
                line=dict(width=width, color="rgba(100,149,237,0.6)"),
                hoverinfo="none",
                showlegend=False,
            )
        )

    # Draw nodes
    node_x = [pos[d][0] for d in devs]
    node_y = [pos[d][1] for d in devs]
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            marker=dict(size=30, color="steelblue"),
            text=devs,
            textposition="top center",
            hoverinfo="text",
            showlegend=False,
        )
    )

    fig.update_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=450,
        margin=dict(l=20, r=20, t=20, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("📊 Dev Performance\nTracker")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Pipeline Steps",
    [
        "1. Data Collection",
        "2. Process Data",
        "3. LLM Analysis",
        "4. Reports",
    ],
)
st.sidebar.markdown("---")
st.sidebar.markdown("**Data Status**")
for label, path in [
    ("pr_raw.json", "data/pr_raw.json"),
    ("metrics.json", "data/metrics.json"),
    ("llm_analysis.json", "data/llm_analysis.json"),
    ("reports/", "data/reports"),
]:
    exists = Path(path).exists() and (
        Path(path).is_file() or any(Path(path).glob("*.md"))
    )
    st.sidebar.markdown(f"{'✓' if exists else '—'} `{label}`")


# ---------------------------------------------------------------------------
# Page 1: Data Collection
# ---------------------------------------------------------------------------
def page_collect():
    st.title("Step 1: Data Collection")
    st.markdown("Fetch PR data from GitHub API or upload a saved file.")

    # Check for existing pr_raw.json in project root (not in data/)
    root_raw = Path("pr_raw.json")
    if root_raw.exists() and not Path("data/pr_raw.json").exists():
        st.info("Found `pr_raw.json` in the project root. You can use this file directly.")
        if st.button("Use project root pr_raw.json"):
            import shutil
            shutil.copy("pr_raw.json", "data/pr_raw.json")
            st.session_state["raw_prs"] = json.loads(Path("pr_raw.json").read_text())
            st.rerun()

    # Auto-load from data/ on startup
    if "raw_prs" not in st.session_state and Path("data/pr_raw.json").exists():
        st.session_state["raw_prs"] = json.loads(Path("data/pr_raw.json").read_text())

    tab1, tab2 = st.tabs(["🌐 Fetch from GitHub API", "📁 Upload File"])

    # ------------------------------------------------------------------
    # Tab 1 - Fetch from GitHub API
    # ------------------------------------------------------------------
    with tab1:
        st.text_input(
            "GitHub Token",
            type="password",
            value=os.getenv("GITHUB_TOKEN", ""),
            key="gh_token",
        )
        st.text_input(
            "Repository (owner/repo)",
            value=os.getenv("GITHUB_REPO", ""),
            key="gh_repo",
        )
        col1, col2 = st.columns(2)
        with col1:
            days = st.slider("Days to look back", min_value=7, max_value=180, value=90, key="gh_days")
        with col2:
            max_prs = st.number_input(
                "Max PRs",
                min_value=10,
                max_value=500,
                value=200,
                step=10,
                key="gh_max_prs",
            )
        include_diffs = st.checkbox(
            "Include diff patches (required for code quality LLM analysis — ~2x API calls)",
            value=False,
            key="include_diffs",
        )
        st.info(
            "ℹ Diff patches enable code quality scoring (conciseness, self-review, firmware). "
            "Without them, only review comment classification runs."
        )

        if st.button("🚀 Fetch PRs", type="primary"):
            token = st.session_state.get("gh_token", "").strip()
            repo = st.session_state.get("gh_repo", "").strip()

            if not token:
                st.error("Please enter a GitHub Token.")
            elif not repo:
                st.error("Please enter a repository in the format owner/repo.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()

                def on_progress(current, total, msg):
                    if total and total > 0:
                        progress_bar.progress(current / total)
                    status_text.text(f"[{current}/{total}] {msg}")

                try:
                    prs = collector.collect(
                        token,
                        repo,
                        days,
                        max_prs,
                        include_diffs,
                        progress_callback=on_progress,
                    )
                    progress_bar.progress(1.0)
                    status_text.empty()
                    st.session_state["raw_prs"] = prs
                    st.success(f"Collected {len(prs)} PRs → saved to data/pr_raw.json")
                    st.rerun()
                except Exception as e:
                    st.error(f"Collection failed: {e}")

    # ------------------------------------------------------------------
    # Tab 2 - Upload File
    # ------------------------------------------------------------------
    with tab2:
        uploaded = st.file_uploader("Upload pr_raw.json", type=["json"])
        if uploaded:
            try:
                data = json.loads(uploaded.read())
                if (
                    isinstance(data, list)
                    and len(data) > 0
                    and "number" in data[0]
                    and "author" in data[0]
                ):
                    Path("data/pr_raw.json").write_text(json.dumps(data, indent=2))
                    st.session_state["raw_prs"] = data
                    st.success(f"Loaded {len(data)} PRs from uploaded file → saved to data/pr_raw.json")
                    st.rerun()
                else:
                    st.error(
                        "File does not look like a valid pr_raw.json. "
                        "Expected a JSON array of PR objects."
                    )
            except Exception as e:
                st.error(f"Failed to parse uploaded file: {e}")

    # ------------------------------------------------------------------
    # PR Preview
    # ------------------------------------------------------------------
    if "raw_prs" in st.session_state:
        prs = st.session_state["raw_prs"]
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total PRs", len(prs))
        col2.metric("Merged", sum(1 for p in prs if p.get("merged")))
        col3.metric("Authors", len(set(p["author"] for p in prs if "author" in p)))
        col4.metric("Has Diffs", "Yes" if any(p.get("files") for p in prs) else "No")

        st.subheader("PR Preview")
        df = pd.DataFrame(
            [
                {
                    "#": p.get("number", ""),
                    "Title": str(p.get("title", ""))[:60],
                    "Author": p.get("author", ""),
                    "Merged": "✓" if p.get("merged") else "✗",
                    "Additions": p.get("additions", 0),
                    "Deletions": p.get("deletions", 0),
                    "Cycle Time (h)": p.get("cycle_time_h"),
                    "Review Comments": len(p.get("review_comments", [])),
                }
                for p in prs
            ]
        )
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "⬇ Download pr_raw.json",
            data=json.dumps(prs, indent=2),
            file_name="pr_raw.json",
            mime="application/json",
        )


# ---------------------------------------------------------------------------
# Page 2: Process Data
# ---------------------------------------------------------------------------
def page_metrics():
    st.title("Step 2: Process Data")
    st.markdown("Compute quantitative metrics from raw PR data.")

    # Auto-load
    if "raw_prs" not in st.session_state:
        if Path("data/pr_raw.json").exists():
            st.session_state["raw_prs"] = json.loads(Path("data/pr_raw.json").read_text())
        else:
            st.warning("No PR data found. Go to **Step 1: Data Collection** first.")
            return

    if "metrics" not in st.session_state and Path("data/metrics.json").exists():
        st.session_state["metrics"] = json.loads(Path("data/metrics.json").read_text())

    if st.button("⚙️ Compute & Save Metrics", type="primary"):
        with st.spinner("Computing metrics..."):
            result = metrics_pipeline.compute(st.session_state["raw_prs"])
            st.session_state["metrics"] = result
        st.success("Metrics computed and saved to data/metrics.json")
        st.rerun()

    if "metrics" not in st.session_state:
        st.info("Click the button above to compute metrics from the loaded PR data.")
        return

    metrics_data = st.session_state["metrics"]
    by_dev = metrics_data.get("by_developer", {})
    team = metrics_data.get("team", {})

    # ------------------------------------------------------------------
    # Top-level KPI row
    # ------------------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total PRs", metrics_data.get("pr_count", "—"))
    col2.metric("Merged PRs", metrics_data.get("merged_count", "—"))
    review_coverage = team.get("review_coverage_pct")
    col3.metric(
        "Review Coverage %",
        f"{review_coverage:.1f}%" if review_coverage is not None else "—",
    )
    median_ct = team.get("cycle_time_p50")
    col4.metric(
        "Median Cycle Time",
        f"{median_ct:.1f}h" if median_ct is not None else "—",
    )

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📦 Delivery", "👁 Review", "🤝 Collaboration"])

    # ------------------------------------------------------------------
    # Tab 1 - Delivery
    # ------------------------------------------------------------------
    with tab1:
        # Cycle time box plot
        ct_rows = []
        for p in metrics_data.get("by_pr", []):
            if p.get("cycle_time_h") and not by_dev.get(p.get("author", ""), {}).get("is_bot"):
                ct_rows.append(
                    {"Developer": p["author"], "Cycle Time (h)": p["cycle_time_h"]}
                )
        df_ct = pd.DataFrame(ct_rows)
        if not df_ct.empty:
            fig = px.box(
                df_ct,
                x="Developer",
                y="Cycle Time (h)",
                points="all",
                title="Cycle Time Distribution by Developer",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "⚠️ Cycle time includes review wait time. High values often reflect reviewer "
                "availability or PR complexity — not author pace."
            )
        else:
            st.info("No cycle time data available.")

        # PR size distribution stacked bar
        rows = []
        for dev, d in by_dev.items():
            if not d.get("is_bot"):
                for bucket, count in d.get("size_buckets", {}).items():
                    rows.append({"Developer": dev, "Size": bucket, "Count": count})
        df_size = pd.DataFrame(rows)
        if not df_size.empty:
            fig = px.bar(
                df_size,
                x="Developer",
                y="Count",
                color="Size",
                color_discrete_map={
                    "S": "#2ecc71",
                    "M": "#3498db",
                    "L": "#e67e22",
                    "XL": "#e74c3c",
                },
                category_orders={"Size": ["S", "M", "L", "XL"]},
                title="PR Size Distribution by Developer",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No PR size distribution data available.")

        # Delivery summary table
        summary_rows = []
        for dev, d in by_dev.items():
            if not d.get("is_bot") and d.get("prs_authored", 0) > 0:
                authored = d.get("prs_authored", 0)
                merged = d.get("prs_merged", 0)
                merge_rate = f"{merged / authored * 100:.0f}%" if authored > 0 else "—"
                avg_ct = d.get("avg_cycle_time_h")
                net_lines = d.get("net_lines", 0)
                summary_rows.append(
                    {
                        "Developer": dev,
                        "PRs Authored": authored,
                        "Merged": merged,
                        "Merge Rate": merge_rate,
                        "Avg Cycle Time (h)": f"{avg_ct:.1f}" if avg_ct is not None else "—",
                        "Net Lines": net_lines,
                    }
                )
        if summary_rows:
            st.subheader("Delivery Summary")
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    # ------------------------------------------------------------------
    # Tab 2 - Review
    # ------------------------------------------------------------------
    with tab2:
        review_coverage = team.get("review_coverage_pct")
        if review_coverage is not None:
            st.metric("Team Review Coverage", f"{review_coverage:.1f}%")

        # Review load horizontal bar
        review_rows = [
            {
                "Developer": dev,
                "PRs Reviewed": d.get("unique_prs_reviewed", 0),
                "Comments Given": d.get("review_comments_given", 0),
            }
            for dev, d in by_dev.items()
            if not d.get("is_bot")
        ]
        df_rv = pd.DataFrame(review_rows).sort_values("PRs Reviewed", ascending=True)
        if not df_rv.empty:
            df_rv_melted = df_rv.melt(
                id_vars="Developer",
                value_vars=["PRs Reviewed", "Comments Given"],
                var_name="Metric",
                value_name="Count",
            )
            fig = px.bar(
                df_rv_melted,
                y="Developer",
                x="Count",
                color="Metric",
                orientation="h",
                barmode="group",
                title="Review Load by Developer",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No review load data available.")

        # First review lag histogram
        lag_values = [
            p["first_review_lag_h"]
            for p in metrics_data.get("by_pr", [])
            if p.get("first_review_lag_h") is not None
        ]
        if lag_values:
            df_lag = pd.DataFrame({"First Review Lag (h)": lag_values})
            fig = px.histogram(
                df_lag,
                x="First Review Lag (h)",
                nbins=30,
                title="First Review Lag Distribution",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No first review lag data available.")

        # Unreviewed merged PRs
        unreviewed = [
            p
            for p in metrics_data.get("by_pr", [])
            if p.get("merged") and not p.get("human_reviewers")
        ]
        if unreviewed:
            st.subheader("Unreviewed Merged PRs")
            df_unreviewed = pd.DataFrame(
                [
                    {
                        "#": p.get("number", ""),
                        "Title": str(p.get("title", ""))[:60],
                        "Author": p.get("author", ""),
                        "Cycle Time (h)": p.get("cycle_time_h"),
                    }
                    for p in unreviewed
                ]
            )
            st.dataframe(df_unreviewed, use_container_width=True)

        st.caption(
            "Review turnaround is shown team-wide only. Slow reviews may reflect timezone, "
            "PTO, or PR complexity — not individual performance."
        )

    # ------------------------------------------------------------------
    # Tab 3 - Collaboration
    # ------------------------------------------------------------------
    with tab3:
        network = team.get("review_network", [])
        if network:
            fig = _build_review_network_fig(network, by_dev)
            if fig:
                st.subheader("Review Network")
                st.caption("Arrows show reviewer → author direction. Edge thickness = review count.")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Not enough data to render the review network.")
        else:
            st.info("No review network data available. Ensure PR data includes review comments.")

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    if "metrics" in st.session_state:
        st.download_button(
            "⬇ Download metrics.json",
            data=json.dumps(st.session_state["metrics"], indent=2),
            file_name="metrics.json",
            mime="application/json",
        )


# ---------------------------------------------------------------------------
# Page 3: LLM Analysis
# ---------------------------------------------------------------------------
def page_llm():
    st.title("Step 3: LLM Analysis")
    st.markdown("Classify review comments and score code quality using OpenRouter.")

    # Auto-load
    if "raw_prs" not in st.session_state:
        if Path("data/pr_raw.json").exists():
            st.session_state["raw_prs"] = json.loads(Path("data/pr_raw.json").read_text())
        else:
            st.warning("No PR data found. Go to **Step 1** first.")
            return

    if "analysis" not in st.session_state and Path("data/llm_analysis.json").exists():
        st.session_state["analysis"] = json.loads(Path("data/llm_analysis.json").read_text())

    tab1, tab2 = st.tabs(["🤖 Run Analysis", "📂 Load Existing"])

    # ------------------------------------------------------------------
    # Tab 1 - Run Analysis
    # ------------------------------------------------------------------
    with tab1:
        st.text_input(
            "OpenRouter API Key",
            type="password",
            value=os.getenv("OPENROUTER_API_KEY", ""),
            key="anthropic_key",
        )
        st.selectbox(
            "Model",
            [
                "qwen/qwen3.6-plus:free",
                "deepseek/deepseek-r1:free",
                "google/gemma-3-27b-it:free",
                "meta-llama/llama-3.3-70b-instruct:free",
            ],
            key="llm_model",
        )
        st.caption(
            "All models above are free-tier on OpenRouter. "
            "Get your key at [openrouter.ai](https://openrouter.ai/keys)."
        )
        st.checkbox(
            "Enable firmware concerns analysis",
            value=True,
            key="enable_firmware",
        )

        prs = st.session_state["raw_prs"]
        n_prs = len(prs)
        st.info(f"Free-tier models have no cost. {n_prs} PRs queued for analysis.")

        # Always show diff availability warning
        has_diffs = any(p.get("files") for p in prs)
        if not has_diffs:
            st.warning(
                "⚠️ **Diff patches not available** in the loaded pr_raw.json. "
                "Code quality scores (conciseness, self-review, firmware concerns) will be **skipped**. "
                "Only **review comment classification** will run.\n\n"
                "To enable full code quality analysis, go back to Step 1 and re-collect with "
                "'Include diff patches' checked."
            )
            total_comments = sum(
                len(p.get("review_comments", [])) + len(p.get("issue_comments", []))
                for p in prs
            )
            st.info(
                f"💬 **{total_comments} review comments** across {len(prs)} PRs available for classification."
            )
        else:
            st.success("✓ Diff patches available — full code quality analysis enabled.")

        if st.button("🚀 Run LLM Analysis", type="primary"):
            if not st.session_state.get("anthropic_key"):
                st.error("Please enter an Anthropic API key.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                token_display = st.empty()

                def on_progress(current, total, pr_num, stage):
                    if total and total > 0:
                        progress_bar.progress(current / total)
                    status_text.text(f"[{current}/{total}] PR #{pr_num}: {stage}")

                try:
                    result = llm_analysis.analyze_prs(
                        st.session_state["raw_prs"],
                        api_key=st.session_state["anthropic_key"],
                        model=st.session_state["llm_model"],
                        enable_firmware=st.session_state["enable_firmware"],
                        progress_callback=on_progress,
                    )
                    st.session_state["analysis"] = result
                    progress_bar.progress(1.0)
                    status_text.empty()
                    total_tok = result.get("total_tokens", {})
                    tok_info = (
                        f" | Tokens: {total_tok.get('input', 0):,} in / {total_tok.get('output', 0):,} out"
                        if total_tok.get("input")
                        else ""
                    )
                    st.success(f"Analysis complete{tok_info} → saved to data/llm_analysis.json")
                    st.rerun()
                except Exception as e:
                    st.error(f"LLM analysis failed: {e}")

    # ------------------------------------------------------------------
    # Tab 2 - Load Existing
    # ------------------------------------------------------------------
    with tab2:
        uploaded = st.file_uploader(
            "Upload llm_analysis.json",
            type=["json"],
            key="upload_analysis",
        )
        if uploaded:
            try:
                data = json.loads(uploaded.read())
                st.session_state["analysis"] = data
                Path("data/llm_analysis.json").write_text(json.dumps(data, indent=2))
                st.success("Loaded analysis from uploaded file.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to parse uploaded file: {e}")

        if Path("data/llm_analysis.json").exists():
            if st.button("Load from data/llm_analysis.json"):
                st.session_state["analysis"] = json.loads(
                    Path("data/llm_analysis.json").read_text()
                )
                st.rerun()

    # ------------------------------------------------------------------
    # Results section
    # ------------------------------------------------------------------
    if "analysis" not in st.session_state:
        return

    analysis = st.session_state["analysis"]
    st.markdown("---")
    st.subheader("Analysis Results")

    # Review Comment Classification stacked bar
    rows = []
    for r in analysis.get("results", []):
        for c in r.get("review_classifications", []):
            rows.append({"Reviewer": c.get("author", ""), "Category": c.get("category", "")})
    if rows:
        df = pd.DataFrame(rows)
        counts = df.groupby(["Reviewer", "Category"]).size().reset_index(name="Count")
        fig = px.bar(
            counts,
            x="Reviewer",
            y="Count",
            color="Category",
            title="Review Comment Categories by Reviewer",
            category_orders={
                "Category": [
                    "bug_catch",
                    "security",
                    "performance",
                    "architecture",
                    "test_gap",
                    "style",
                    "question",
                    "praise",
                ]
            },
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No review classification data available.")

    # Code Quality Scores summary
    st.subheader("Code Quality Score Averages")
    results = analysis.get("results", [])

    def _avg_score(key):
        vals = [
            r[key]["score"]
            for r in results
            if r.get(key) and r[key].get("score") is not None
        ]
        return sum(vals) / len(vals) if vals else None

    conc_avg = _avg_score("conciseness")
    sr_avg = _avg_score("self_review")
    fw_avg = _avg_score("firmware_concerns")

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Avg Conciseness",
        f"{conc_avg:.1f}/10" if conc_avg is not None else "—",
        help="Average conciseness score across all PRs with diff patches.",
    )
    col2.metric(
        "Avg Self-Review",
        f"{sr_avg:.1f}/10" if sr_avg is not None else "—",
        help="Average self-review score across all PRs with diff patches.",
    )
    col3.metric(
        "Avg Firmware Concerns",
        f"{fw_avg:.1f}/10" if fw_avg is not None else "—",
        help="Average firmware concerns score across all PRs with diff patches.",
    )

    # Per-PR Details
    st.subheader("Per-PR Details")
    for r in analysis.get("results", []):
        pr_num = r.get("pr_number", "?")
        pr_title = r.get("pr_title", "")
        with st.expander(f"PR #{pr_num}: {str(pr_title)[:60]}"):
            col1, col2, col3 = st.columns(3)
            conc = r.get("conciseness") or {}
            sr = r.get("self_review") or {}
            fw = r.get("firmware_concerns") or {}
            col1.metric("Conciseness", conc.get("score") or "—")
            col2.metric("Self-Review", sr.get("score") or "—")
            col3.metric("Firmware", fw.get("score") or "—")
            if r.get("review_classifications"):
                df = pd.DataFrame(r["review_classifications"])
                available_cols = [c for c in ["author", "category", "body"] if c in df.columns]
                if available_cols:
                    rename_map = {"author": "Reviewer", "category": "Category", "body": "Comment"}
                    st.dataframe(
                        df[available_cols].rename(columns=rename_map),
                        use_container_width=True,
                    )

    # Download
    st.download_button(
        "⬇ Download llm_analysis.json",
        data=json.dumps(analysis, indent=2),
        file_name="llm_analysis.json",
        mime="application/json",
    )


# ---------------------------------------------------------------------------
# Page 4: Reports
# ---------------------------------------------------------------------------
def page_reports():
    st.title("Step 4: Reports")
    st.markdown("Generate and view team health and individual growth reports.")

    # Dependency check
    has_metrics = "metrics" in st.session_state or Path("data/metrics.json").exists()
    has_analysis = "analysis" in st.session_state or Path("data/llm_analysis.json").exists()

    if not has_metrics:
        st.error("Missing required data:")
        st.markdown("- ❌ **metrics.json** — Go to Step 2 and compute metrics first")
        st.markdown(f"- {'✓' if has_analysis else '⚠'} **llm_analysis.json** — Optional (Step 3)")
        return

    # Load into session state if not already there
    if "metrics" not in st.session_state:
        st.session_state["metrics"] = json.loads(Path("data/metrics.json").read_text())
    if "analysis" not in st.session_state and Path("data/llm_analysis.json").exists():
        st.session_state["analysis"] = json.loads(Path("data/llm_analysis.json").read_text())

    tab1, tab2 = st.tabs(["🏢 Team Health Report", "👤 Individual Reports"])

    # ------------------------------------------------------------------
    # Tab 1 - Team Health
    # ------------------------------------------------------------------
    with tab1:
        if st.button("📝 Generate Team Report", type="primary"):
            with st.spinner("Generating..."):
                report_text = reports.generate_team_report(
                    st.session_state["metrics"],
                    st.session_state.get("analysis"),
                )
                reports.save_report(report_text, "data/reports/team_health.md")
                st.session_state["team_report"] = report_text
            st.success("Report saved to data/reports/team_health.md")

        # Auto-load if exists
        if "team_report" not in st.session_state and Path("data/reports/team_health.md").exists():
            st.session_state["team_report"] = Path("data/reports/team_health.md").read_text()

        if "team_report" in st.session_state:
            st.markdown("---")
            st.markdown(st.session_state["team_report"])
            st.download_button(
                "⬇ Download team_health.md",
                data=st.session_state["team_report"],
                file_name="team_health.md",
                mime="text/markdown",
            )

    # ------------------------------------------------------------------
    # Tab 2 - Individual Reports
    # ------------------------------------------------------------------
    with tab2:
        by_developer = st.session_state["metrics"].get("by_developer", {})
        dev_list = sorted(
            [
                dev
                for dev, d in by_developer.items()
                if not d.get("is_bot") and d.get("prs_authored", 0) > 0
            ]
        )

        if not dev_list:
            st.info("No developers with authored PRs found.")
            return

        selected_dev = st.selectbox("Select Developer", dev_list)

        if st.button("📝 Generate Individual Report", type="primary"):
            with st.spinner("Generating..."):
                report_text = reports.generate_individual_report(
                    selected_dev,
                    st.session_state["metrics"],
                    st.session_state.get("analysis"),
                )
                safe_name = (
                    selected_dev.replace("/", "_").replace("[", "").replace("]", "")
                )
                report_path = f"data/reports/individual_{safe_name}.md"
                reports.save_report(report_text, report_path)
                st.session_state[f"ind_report_{selected_dev}"] = report_text
            st.success(f"Report saved to {report_path}")

        report_key = f"ind_report_{selected_dev}"
        safe_name = selected_dev.replace("/", "_").replace("[", "").replace("]", "")
        report_path = f"data/reports/individual_{safe_name}.md"

        if report_key not in st.session_state and Path(report_path).exists():
            st.session_state[report_key] = Path(report_path).read_text()

        if report_key in st.session_state:
            st.markdown("---")
            col_report, col_charts = st.columns([3, 2])

            with col_report:
                st.markdown(st.session_state[report_key])

            with col_charts:
                # Review feedback category breakdown for this developer
                if "analysis" in st.session_state:
                    results = st.session_state["analysis"].get("results", [])
                    dev_results = [r for r in results if r.get("author") == selected_dev]
                    cats = []
                    for r in dev_results:
                        for c in r.get("review_classifications", []):
                            cats.append(c.get("category", ""))
                    if cats:
                        cat_counts = Counter(cats)
                        fig = px.pie(
                            values=list(cat_counts.values()),
                            names=list(cat_counts.keys()),
                            title=f"Review feedback received by {selected_dev}",
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No review classifications available for this developer.")
                else:
                    st.info("Run LLM Analysis (Step 3) to see review feedback breakdown.")

            st.download_button(
                f"⬇ Download {selected_dev}_report.md",
                data=st.session_state[report_key],
                file_name=f"individual_{safe_name}.md",
                mime="text/markdown",
            )


# ---------------------------------------------------------------------------
# Page routing
# ---------------------------------------------------------------------------
if page == "1. Data Collection":
    page_collect()
elif page == "2. Process Data":
    page_metrics()
elif page == "3. LLM Analysis":
    page_llm()
elif page == "4. Reports":
    page_reports()
