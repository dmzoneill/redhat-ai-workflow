#!/usr/bin/env python3
"""Test peer repository discovery and cloning per the verification plan."""
import json
import os
import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.stats.collector import DataCollector

# Skip known huge repos that timeout (e.g. ansible/awx is 500MB+)
SKIP_REPOS = {"ansible/awx", "ansible/ansible"}


def main():
    roster_path = Path.home() / ".config/aa-workflow/performance/org/org_roster.json"
    if not roster_path.exists():
        print(f"ERROR: Roster not found at {roster_path}")
        return 1

    with open(roster_path) as f:
        data = json.load(f)

    # Get 5 peers with gitlab_username from roster
    peers = []
    for level, plist in data.get("peers", {}).items():
        for p in plist:
            if p.get("gitlab_username"):
                peers.append(p)
            if len(peers) >= 5:
                break
        if len(peers) >= 5:
            break

    print("=== Step 1: 5 peers with gitlab_username ===\n")
    for p in peers:
        print(
            f"  {p['username']} gl={p.get('gitlab_username','')} gh={p.get('github_username','')} git_author={p.get('git_author','')}"
        )

    # Initialize collector
    c = DataCollector()
    c.strategy_index = {}
    c.hierarchy_cache = {}

    # Step 6: Check SSH first
    print("\n=== Step 6: SSH connectivity test ===\n")
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-T",
            "git@gitlab.cee.redhat.com",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    print(f"SSH test: rc={result.returncode}")
    if result.stderr:
        print(f"  stderr: {result.stderr[:300]}")
    if result.returncode not in (0, 1):  # 1 = success for git (rejects shell)
        print("  WARNING: SSH may have issues (rc 0 or 1 is normal for git)")

    # Results table
    results = []

    for peer in peers:
        gl_user = peer.get("gitlab_username", "")
        gh_user = peer.get("github_username", "")
        git_author = peer.get("git_author", "")
        username = peer.get("username", "")

        print(f"\n=== Peer: {username} (gl={gl_user}, gh={gh_user}) ===\n")

        # Step 2: GitLab cache
        gl_mrs = 0
        gl_paths = set()
        try:
            gl_cache = c.get_gitlab_cache(2026, 1, username_override=gl_user)
            gl_mrs = len(gl_cache.get("mrs_authored", []))
            for mr in gl_cache.get("mrs_authored", []):
                p = mr.get("gitlab_path", "")
                if p:
                    gl_paths.add(p)
            print(f"  GitLab: {gl_mrs} MRs in {len(gl_paths)} repos")
            if gl_paths:
                print(
                    f"  Repos: {sorted(gl_paths)[:5]}{'...' if len(gl_paths) > 5 else ''}"
                )
        except Exception as e:
            print(f"  GitLab cache error: {e}")

        # Step 2b: GitHub cache
        gh_paths = set()
        gh_prs = 0
        try:
            gh_cache = c.get_github_cache(2026, 1, username_override=gh_user)
            gh_prs = len(gh_cache.get("prs_authored", []))
            for pr in gh_cache.get("prs_authored", []):
                repo = (pr.get("repository") or {}).get("nameWithOwner", "")
                if repo:
                    gh_paths.add(f"github:{repo}")
            print(f"  GitHub: {gh_prs} PRs in {len(gh_paths)} repos")
        except Exception as e:
            print(f"  GitHub cache error: {e}")

        # Combine paths, skip huge repos, cap at 5
        all_paths = gl_paths | gh_paths
        filtered = [
            p
            for p in all_paths
            if not (p.startswith("github:") and p.replace("github:", "") in SKIP_REPOS)
        ]
        peer_paths = filtered[:5]
        print(f"  Combined unique repos (capped 5, skipped huge): {peer_paths}")

        # Step 3: discover_peer_repos
        repos_cloned = 0
        clone_errors = []
        if peer_paths:
            try:
                c.discover_peer_repos(peer_paths)
                # Count what was cloned (we can't easily count per-peer, so we check cache dir)
                repos_cloned = len(peer_paths)  # Best effort
            except Exception as e:
                clone_errors.append(str(e))
                print(f"  discover_peer_repos error: {e}")

        # Step 4: git log on cloned repos
        commits_found = 0
        repos = c.get_config_repos(include_cached=True)
        for repo in repos:
            for author in [git_author, f"{username}@redhat.com"]:
                try:
                    out = subprocess.check_output(
                        [
                            "git",
                            "-C",
                            repo["path"],
                            "log",
                            "--all",
                            f"--author={author}",
                            "--oneline",
                            "-5",
                        ],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                    if out.strip():
                        n = len(out.strip().splitlines())
                        commits_found += n
                        print(f"  {repo['name']}: {n} commits (author={author})")
                        break
                except Exception:
                    pass

        results.append(
            {
                "peer": username,
                "gl_mrs": gl_mrs,
                "unique_repos": len(gl_paths) + len(gh_paths),
                "repos_cloned": len(peer_paths),
                "commits_found": commits_found,
                "clone_errors": clone_errors,
            }
        )

    # Summary table
    print("\n" + "=" * 80)
    print(
        "=== REPORT: peer | gitlab MRs | unique repos | repos cloned | git commits found ==="
    )
    print("=" * 80)
    for r in results:
        err_str = f" (errors: {r['clone_errors']})" if r["clone_errors"] else ""
        print(
            f"  {r['peer']:12} | {r['gl_mrs']:10} | {r['unique_repos']:12} | {r['repos_cloned']:13} | {r['commits_found']:18}{err_str}"
        )

    # Repo cache directory
    cache_dir = Path.home() / ".config/aa-workflow/performance/repo-cache"
    print(f"\n=== Repo-cache directory: {cache_dir} ===")
    if cache_dir.exists():
        for d in sorted(cache_dir.iterdir()):
            if d.is_dir():
                size_kb = (
                    sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) // 1024
                )
                print(f"  {d.name}: {size_kb}KB")
    else:
        print("  (does not exist)")

    # Any errors
    all_errors = [e for r in results for e in r["clone_errors"]]
    if all_errors:
        print("\n=== Errors encountered ===")
        for e in all_errors:
            print(f"  {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
