from src.analytics.development import group_commits, rank_module_churn
from src.analytics.git_activity import GitCommit


def commit(sha, authored_at, subject, modules):
    return GitCommit(sha, authored_at, "Test", subject, 2, 10, 3, modules, 1)


def test_grouping_requires_time_module_and_keyword_overlap():
    commits = [
        commit("a", "2026-07-13T10:00:00Z", "feat: add paper experiment API", ["paper-trading"]),
        commit("b", "2026-07-13T16:00:00Z", "feat: improve paper experiment UI", ["paper-trading"]),
        commit("c", "2026-07-14T17:00:00Z", "fix: paper experiment labels", ["paper-trading"]),
        commit("d", "2026-07-13T18:00:00Z", "feat: scanner trend", ["scanner"]),
    ]
    groups = group_commits(commits)
    assert groups[0].commit_shas == ["b", "a"]
    assert {tuple(group.commit_shas) for group in groups[1:]} == {("c",), ("d",)}


def test_churn_ranks_modules_by_changed_lines():
    commits = [commit("a", "2026-07-13T10:00:00Z", "feat: scanner", ["scanner"])]
    assert rank_module_churn(commits)[0]["changed_lines"] == 13
