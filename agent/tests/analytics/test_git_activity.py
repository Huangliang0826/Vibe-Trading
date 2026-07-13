import subprocess

from src.analytics.git_activity import GitActivityReader


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def test_reader_parses_commits_modules_and_release(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    path = tmp_path / "frontend/src/pages/Scanner.tsx"
    path.parent.mkdir(parents=True)
    path.write_text("export const scanner = 1;\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "feat: add scanner trend")
    second = tmp_path / "agent/src/scanner/core.py"
    second.parent.mkdir(parents=True)
    second.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fix: scanner metrics")
    _git(tmp_path, "tag", "v1.2.3")
    result = GitActivityReader(tmp_path).read()
    assert [commit.subject for commit in result.commits][:2] == ["fix: scanner metrics", "feat: add scanner trend"]
    assert {module for commit in result.commits for module in commit.modules} >= {"frontend/scanner", "backend/scanner"}
    assert result.releases[0].tag == "v1.2.3"


def test_non_repo_is_an_explicit_empty_result(tmp_path):
    result = GitActivityReader(tmp_path).read()
    assert result.commits == []
    assert result.warnings == ["git_unavailable"]
