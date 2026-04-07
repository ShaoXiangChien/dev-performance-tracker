"""
Script 3: Check your API rate limit status and estimate how many PRs you can fetch.
Run this first to understand your quota before running collect_pr_data.py.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO  = os.getenv("GITHUB_REPO")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def check():
    r = requests.get("https://api.github.com/rate_limit", headers=HEADERS)
    r.raise_for_status()
    data = r.json()

    core = data["resources"]["core"]
    remaining = core["remaining"]
    limit     = core["limit"]
    reset_ts  = core["reset"]

    import datetime
    reset_dt = datetime.datetime.fromtimestamp(reset_ts).strftime("%H:%M:%S")

    print(f"Rate limit:  {limit} req/hour")
    print(f"Remaining:   {remaining}")
    print(f"Resets at:   {reset_dt} local time")
    print()

    # Each PR in collect_pr_data.py costs ~4 API calls:
    #   1 list-PRs page (shared across 100 PRs)
    #   + reviews + review_comments + issue_comments per PR
    cost_per_pr = 3
    estimated_prs = remaining // cost_per_pr
    print(f"Estimated PRs you can process now: ~{estimated_prs}")
    print(f"(assumes {cost_per_pr} API calls per PR)")

    # Also confirm auth identity
    me = requests.get("https://api.github.com/user", headers=HEADERS).json()
    print(f"\nAuthenticated as: {me.get('login')} ({me.get('name')})")
    print(f"Plan: {me.get('plan', {}).get('name', 'unknown') if me.get('plan') else 'unknown'}")

    # Confirm repo access
    repo_r = requests.get(f"https://api.github.com/repos/{REPO}", headers=HEADERS)
    if repo_r.status_code == 200:
        repo = repo_r.json()
        print(f"\nRepo: {repo['full_name']}")
        print(f"  Private:      {repo['private']}")
        print(f"  Open PRs:     {repo['open_issues_count']} (issues+PRs combined)")
        print(f"  Default branch: {repo['default_branch']}")
    elif repo_r.status_code == 404:
        print(f"\nRepo '{REPO}' not found or no access.")
    else:
        print(f"\nRepo check failed: {repo_r.status_code}")


if __name__ == "__main__":
    check()
