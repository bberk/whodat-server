"""Tests for the workflow scripts (``scripts/ship.sh`` and ``scripts/merge.sh``).

Each test drives the real script inside a throwaway git repository with a stub ``gh`` first on
``PATH``, so the gate logic runs against synthetic ``gh pr view --json`` payloads and nothing ever
touches GitHub. Covers AC-WF-07, AC-WF-08, AC-WF-09, AC-WF-13, AC-WF-15, and AC-WF-23.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIP = REPO_ROOT / "scripts" / "ship.sh"
MERGE = REPO_ROOT / "scripts" / "merge.sh"
CLEANUP = REPO_ROOT / "scripts" / "cleanup.sh"
WORK_BRANCH = "agent/test-task"
BOT_NAME = "brads-bots[bot]"
BOT_EMAIL = "344180581+brads-bots[bot]@users.noreply.github.com"

# Stub `gh`: log every call, answer `pr view` from a canned payload, and fail loudly on `pr create`
# so a script that tries to open a pull request is caught by the assertion and by the exit code.
STUB_GH = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$GH_LOG"
if [[ "${1:-}" == "pr" && "${2:-}" == "view" ]]; then
  if [[ "$*" == *"--json url"* ]]; then
    printf '%s\\n' "$GH_PR_URL"
    exit 0
  fi
  cat "$GH_PR_JSON"
  exit "${GH_VIEW_EXIT:-0}"
fi
if [[ "${1:-}" == "pr" && "${2:-}" == "create" ]]; then
  echo "stub gh: 'pr create' must never be called" >&2
  exit 1
fi
if [[ "${1:-}" == "pr" && "${2:-}" == "list" ]]; then
  cat "$GH_PR_LIST_JSON"
  exit "${GH_LIST_EXIT:-0}"
fi
exit 0
"""


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    """Run git in ``repo`` and return its stdout."""
    result = subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout


def _run(
    script: Path, repo: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    """Run one of the workflow scripts with ``repo`` as the working directory."""
    return subprocess.run(
        ["bash", str(script), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def _gh_calls(env: dict[str, str]) -> list[str]:
    """Every ``gh`` invocation the stub has recorded, in order."""
    return Path(env["GH_LOG"]).read_text().splitlines()


def _pr_create_calls(env: dict[str, str]) -> list[str]:
    """Every attempt to open a pull request; must always be empty."""
    return [call for call in _gh_calls(env) if call.startswith("pr create")]


def _set_pr(env: dict[str, str], **payload: object) -> None:
    """Install the ``gh pr view --json ...`` payload the stub replays."""
    Path(env["GH_PR_JSON"]).write_text(json.dumps(payload))


def _open_pr(**overrides: object) -> dict[str, object]:
    """A payload for a PR that passes every gate, with individual fields overridable."""
    payload: dict[str, object] = {
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": "abc123",
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        "files": [{"path": "backend/src/app/api/main.py"}],
        "headRefName": WORK_BRANCH,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """An isolated environment: stub ``gh`` on PATH and git config disabled."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "gh"
    stub.write_text(STUB_GH)
    stub.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    payload = tmp_path / "pr.json"
    payload.write_text("{}")
    merged = tmp_path / "merged.json"
    merged.write_text("[]")
    # Git hooks export GIT_DIR and friends; drop them so the throwaway repos are not the real one.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "PATH": f"{stub_dir}{os.pathsep}{environment['PATH']}",
            "GH_LOG": str(log),
            "GH_PR_JSON": str(payload),
            "GH_PR_LIST_JSON": str(merged),
            "GH_PR_URL": "https://example.test/pr/7",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
            "BRADS_BOTS_TOKEN": "test-token",
        }
    )
    return environment


@pytest.fixture
def repo(tmp_path: Path, env: dict[str, str]) -> Path:
    """A throwaway repo with a bare ``origin`` and one commit on ``agent/test-task``."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(work)],
        check=True,
        capture_output=True,
        env=env,
    )
    _git(work, env, "remote", "add", "origin", str(origin))
    (work / "seed.txt").write_text("seed\n")
    _git(work, env, "add", "-A")
    _git(work, env, "commit", "-m", "Initial")
    _git(work, env, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(work, env, "checkout", "-b", WORK_BRANCH)
    return work


# --- scripts/ship.sh --------------------------------------------------------------------------


def test_AC_WF_07_ship_pushes_the_branch(repo: Path, env: dict[str, str]) -> None:
    result = _run(SHIP, repo, env)

    assert result.returncode == 0, result.stderr
    assert f"refs/heads/{WORK_BRANCH}" in _git(repo, env, "ls-remote", "--heads", "origin")
    assert _pr_create_calls(env) == [], "ship.sh must not open a pull request"


def test_AC_WF_07_ship_refuses_commits_not_authored_by_the_bot(
    repo: Path, env: dict[str, str]
) -> None:
    human = {**env, "GIT_AUTHOR_NAME": "Human", "GIT_AUTHOR_EMAIL": "human@example.test"}
    (repo / "change.txt").write_text("change\n")
    _git(repo, env, "add", "-A")
    _git(repo, human, "commit", "-m", "Human change")

    result = _run(SHIP, repo, env)

    assert result.returncode != 0
    assert "not authored by" in result.stderr
    assert f"refs/heads/{WORK_BRANCH}" not in _git(repo, env, "ls-remote", "--heads", "origin")


def test_AC_WF_07_ship_pushes_later_commits_to_the_same_branch(
    repo: Path, env: dict[str, str]
) -> None:
    _run(SHIP, repo, env)
    (repo / "more.txt").write_text("more\n")
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-m", "More")

    result = _run(SHIP, repo, env)

    assert result.returncode == 0, result.stderr
    pushed = _git(repo, env, "ls-remote", "--heads", "origin")
    assert pushed.count(f"refs/heads/{WORK_BRANCH}") == 1
    assert _pr_create_calls(env) == []


def test_AC_WF_07_a_commit_alone_pushes_nothing(repo: Path, env: dict[str, str]) -> None:
    """There is no post-commit hook: committing must never push behind the agent's back."""
    (repo / "more.txt").write_text("more\n")
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-m", "More")

    assert _git(repo, env, "ls-remote", "--heads", "origin") == ""


def test_AC_WF_07_the_removed_post_commit_mode_is_rejected(repo: Path, env: dict[str, str]) -> None:
    result = _run(SHIP, repo, env, "--post-commit")

    assert result.returncode == 64
    assert "usage" in result.stderr
    assert _git(repo, env, "ls-remote", "--heads", "origin") == ""


def test_AC_WF_07_the_hook_config_has_no_post_commit_stage() -> None:
    """Autoship is gone: no hook stage fires on commit to push or open a PR."""
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text()

    assert "post-commit" not in config
    assert "AGENT_AUTOSHIP" not in config


def test_AC_WF_08_ship_refuses_to_push_main(repo: Path, env: dict[str, str]) -> None:
    _git(repo, env, "checkout", "main")

    result = _run(SHIP, repo, env)

    assert result.returncode != 0
    assert "refusing to ship" in result.stderr
    assert _git(repo, env, "ls-remote", "--heads", "origin") == ""


def test_AC_WF_09_ready_marks_the_pr_ready_and_labels_it(repo: Path, env: dict[str, str]) -> None:
    result = _run(SHIP, repo, env, "--ready")

    assert result.returncode == 0, result.stderr
    calls = _gh_calls(env)
    assert any(call.startswith("pr ready ") for call in calls), calls
    assert any("pr edit" in call and "--add-label ready-for-review" in call for call in calls), (
        calls
    )
    assert _pr_create_calls(env) == [], calls
    assert result.stdout.strip().splitlines()[-1] == "https://example.test/pr/7"


def test_AC_WF_09_ready_fails_when_there_is_no_pull_request(
    repo: Path, env: dict[str, str]
) -> None:
    env["GH_VIEW_EXIT"] = "1"

    result = _run(SHIP, repo, env, "--ready")

    assert result.returncode != 0
    assert "no PR" in result.stderr
    assert not any(call.startswith(("pr ready", "pr edit")) for call in _gh_calls(env))


# --- scripts/merge.sh -------------------------------------------------------------------------


def _merge(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return _run(MERGE, repo, env, "7", *args)


def _assert_refused(
    result: subprocess.CompletedProcess[str], env: dict[str, str], needle: str
) -> None:
    assert result.returncode != 0
    assert needle in result.stderr, result.stderr
    assert not any(call.startswith("pr merge") for call in _gh_calls(env)), _gh_calls(env)


def test_AC_WF_13_merge_refuses_a_draft_pull_request(repo: Path, env: dict[str, str]) -> None:
    _set_pr(env, **_open_pr(isDraft=True))

    _assert_refused(_merge(repo, env), env, "still a draft")


def test_AC_WF_13_merge_refuses_a_pull_request_that_is_not_open(
    repo: Path, env: dict[str, str]
) -> None:
    _set_pr(env, **_open_pr(state="CLOSED"))

    _assert_refused(_merge(repo, env), env, "not open")


def test_AC_WF_13_merge_refuses_when_no_checks_have_reported(
    repo: Path, env: dict[str, str]
) -> None:
    _set_pr(env, **_open_pr(statusCheckRollup=[]))

    _assert_refused(_merge(repo, env), env, "no CI checks")


@pytest.mark.parametrize(
    "rollup",
    [
        pytest.param([{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}], id="failing"),
        pytest.param([{"conclusion": "SUCCESS"}, {"conclusion": ""}], id="pending"),
        pytest.param([{"conclusion": "CANCELLED"}], id="cancelled"),
    ],
)
def test_AC_WF_13_merge_refuses_pending_or_failing_checks(
    repo: Path, env: dict[str, str], rollup: list[dict[str, str]]
) -> None:
    _set_pr(env, **_open_pr(statusCheckRollup=rollup))

    _assert_refused(_merge(repo, env), env, "pending or failing")


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "SPEC.md",
        "ACCEPTANCE.md",
        "ARCHITECTURE.md",
        "scripts/merge.sh",
        ".github/workflows/ci.yml",
        ".opencode/pull-requests.md",
        ".pre-commit-config.yaml",
    ],
)
def test_AC_WF_15_merge_refuses_governance_changes_without_the_flag(
    repo: Path, env: dict[str, str], path: str
) -> None:
    _set_pr(env, **_open_pr(files=[{"path": path}]))

    result = _merge(repo, env)

    _assert_refused(result, env, "touches governance files")
    assert path in result.stderr


def test_AC_WF_15_merge_allows_governance_changes_with_the_flag(
    repo: Path, env: dict[str, str]
) -> None:
    _set_pr(env, **_open_pr(files=[{"path": "scripts/merge.sh"}]))

    result = _merge(repo, env, "--allow-governance")

    assert result.returncode == 0, result.stderr
    assert any(call.startswith("pr merge 7") for call in _gh_calls(env)), _gh_calls(env)


def test_AC_WF_13_merge_rebases_by_default_when_every_gate_passes(
    repo: Path, env: dict[str, str]
) -> None:
    _set_pr(env, **_open_pr())

    result = _merge(repo, env)

    assert result.returncode == 0, result.stderr
    calls = _gh_calls(env)
    assert any(call.startswith("pr merge 7") for call in calls), calls
    assert any("--rebase" in call and "--delete-branch" in call for call in calls), calls
    assert any("--match-head-commit abc123" in call for call in calls), calls
    assert not any("--squash" in call for call in calls), calls


def test_AC_WF_13_merge_squashes_when_asked(repo: Path, env: dict[str, str]) -> None:
    _set_pr(env, **_open_pr())

    result = _merge(repo, env, "--squash")

    assert result.returncode == 0, result.stderr
    calls = _gh_calls(env)
    assert any("--squash" in call and "--delete-branch" in call for call in calls), calls
    assert not any("--rebase" in call for call in calls), calls


def test_AC_WF_13_merge_refuses_merge_commits(repo: Path, env: dict[str, str]) -> None:
    _set_pr(env, **_open_pr())

    result = _merge(repo, env, "--merge")

    assert result.returncode == 64
    assert "linear" in result.stderr
    assert not any(call.startswith("pr merge") for call in _gh_calls(env))


def test_AC_WF_13_merge_rejects_an_unknown_option(repo: Path, env: dict[str, str]) -> None:
    _set_pr(env, **_open_pr())

    result = _merge(repo, env, "--yolo")

    assert result.returncode == 64
    assert "unknown option" in result.stderr
    assert not any(call.startswith("pr merge") for call in _gh_calls(env))


def test_AC_WF_15_merge_accepts_method_and_governance_flags_in_any_order(
    repo: Path, env: dict[str, str]
) -> None:
    _set_pr(env, **_open_pr(files=[{"path": "AGENTS.md"}]))

    result = _merge(repo, env, "--squash", "--allow-governance")

    assert result.returncode == 0, result.stderr
    calls = _gh_calls(env)
    assert any("--squash" in call and "--match-head-commit abc123" in call for call in calls), calls


# --- scripts/cleanup.sh -----------------------------------------------------------------------


def _set_merged_pr(env: dict[str, str], head_sha: str, number: int = 9) -> None:
    """Make the stub report one merged PR whose head commit is ``head_sha``."""
    Path(env["GH_PR_LIST_JSON"]).write_text(
        json.dumps(
            [{"number": number, "headRefOid": head_sha, "url": f"https://example.test/pr/{number}"}]
        )
    )


def _head(repo: Path, env: dict[str, str]) -> str:
    """The commit ``repo`` currently points at."""
    return _git(repo, env, "rev-parse", "HEAD").strip()


def _has_branch(repo: Path, env: dict[str, str], branch: str) -> bool:
    """Whether ``branch`` exists locally."""
    return branch in _git(repo, env, "branch", "--list", branch)


def test_AC_WF_23_cleanup_deletes_a_merged_branch(repo: Path, env: dict[str, str]) -> None:
    _git(repo, env, "branch", "agent/done")
    _set_merged_pr(env, _head(repo, env))

    result = _run(CLEANUP, repo, env, "agent/done")

    assert result.returncode == 0, result.stderr
    assert not _has_branch(repo, env, "agent/done")


def test_AC_WF_23_cleanup_keeps_a_branch_without_a_merged_pr(
    repo: Path, env: dict[str, str]
) -> None:
    _git(repo, env, "branch", "agent/wip")

    result = _run(CLEANUP, repo, env, "agent/wip")

    assert result.returncode == 0, result.stderr
    assert _has_branch(repo, env, "agent/wip")
    assert "no merged pull request" in result.stdout


def test_AC_WF_23_cleanup_keeps_a_branch_that_moved_after_the_merge(
    repo: Path, env: dict[str, str]
) -> None:
    _git(repo, env, "branch", "agent/moved")
    _set_merged_pr(env, "0" * 40)

    result = _run(CLEANUP, repo, env, "agent/moved")

    assert result.returncode == 0, result.stderr
    assert _has_branch(repo, env, "agent/moved")
    assert "commits the merge did not include" in result.stderr


def test_AC_WF_23_cleanup_keeps_the_current_branch(repo: Path, env: dict[str, str]) -> None:
    _set_merged_pr(env, _head(repo, env))

    result = _run(CLEANUP, repo, env, WORK_BRANCH)

    assert result.returncode == 0, result.stderr
    assert _has_branch(repo, env, WORK_BRANCH)
    assert "checked out here" in result.stdout


def test_AC_WF_23_cleanup_keeps_a_branch_when_github_cannot_be_queried(
    repo: Path, env: dict[str, str]
) -> None:
    env["GH_LIST_EXIT"] = "1"
    _git(repo, env, "branch", "agent/done")

    result = _run(CLEANUP, repo, env, "agent/done")

    assert result.returncode == 0, result.stderr
    assert _has_branch(repo, env, "agent/done")
    assert "could not query GitHub" in result.stderr


def test_AC_WF_23_cleanup_removes_the_worktree_of_a_merged_branch(
    repo: Path, env: dict[str, str]
) -> None:
    wt = repo.parent / "wt"
    _git(repo, env, "branch", "agent/done")
    _git(repo, env, "worktree", "add", str(wt), "agent/done")
    _set_merged_pr(env, _head(wt, env))

    result = _run(CLEANUP, repo, env, "agent/done")

    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    assert not _has_branch(repo, env, "agent/done")


def test_AC_WF_23_cleanup_keeps_a_dirty_worktree(repo: Path, env: dict[str, str]) -> None:
    wt = repo.parent / "wt"
    _git(repo, env, "branch", "agent/done")
    _git(repo, env, "worktree", "add", str(wt), "agent/done")
    _set_merged_pr(env, _head(wt, env))
    (wt / "scratch.txt").write_text("work in progress\n")

    result = _run(CLEANUP, repo, env, "agent/done")

    assert result.returncode == 0, result.stderr
    assert wt.exists()
    assert _has_branch(repo, env, "agent/done")
    assert "has changes" in result.stderr


def test_AC_WF_23_dry_run_changes_nothing(repo: Path, env: dict[str, str]) -> None:
    _git(repo, env, "branch", "agent/done")
    _set_merged_pr(env, _head(repo, env))

    result = _run(CLEANUP, repo, env, "--dry-run", "agent/done")

    assert result.returncode == 0, result.stderr
    assert "would delete agent/done" in result.stdout
    assert _has_branch(repo, env, "agent/done")


def test_AC_WF_23_no_arguments_considers_only_agent_branches(
    repo: Path, env: dict[str, str]
) -> None:
    _git(repo, env, "branch", "feature/other")
    _git(repo, env, "branch", "agent/done")
    _set_merged_pr(env, _head(repo, env))

    result = _run(CLEANUP, repo, env)

    assert result.returncode == 0, result.stderr
    assert _has_branch(repo, env, "feature/other")
    assert not _has_branch(repo, env, "agent/done")


def test_AC_WF_23_merge_cleans_up_a_branch_in_another_worktree(
    repo: Path, env: dict[str, str]
) -> None:
    wt = repo.parent / "wt"
    _git(repo, env, "branch", "agent/done")
    _git(repo, env, "worktree", "add", str(wt), "agent/done")
    _set_pr(env, **_open_pr(headRefName="agent/done"))
    _set_merged_pr(env, _head(wt, env))

    result = _merge(repo, env)

    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    assert not _has_branch(repo, env, "agent/done")
