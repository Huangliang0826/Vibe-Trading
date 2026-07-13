from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .git_activity import GitCommit

STOP_WORDS = {"add", "update", "improve", "fix", "the", "a", "an", "to", "and"}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _title_keywords(subject: str) -> set[str]:
    title = re.sub(r"^(?:feat|fix|docs|test|refactor|chore|perf)(?:\([^)]*\))?:\s*", "", subject.lower())
    return {word for word in re.findall(r"[a-z0-9_-]+", title) if word not in STOP_WORDS}


def _label(subject: str) -> str:
    return re.sub(r"^(?:feat|fix|docs|test|refactor|chore|perf)(?:\([^)]*\))?:\s*", "", subject, flags=re.I)


@dataclass(frozen=True)
class FeatureGroup:
    label: str
    commit_shas: list[str]
    subjects: list[str]
    modules: list[str]
    started_at: str
    ended_at: str
    files_changed: int
    insertions: int
    deletions: int


def group_commits(commits: list[GitCommit]) -> list[FeatureGroup]:
    ordered = sorted(commits, key=lambda commit: _timestamp(commit.authored_at))
    buckets: list[list[GitCommit]] = []
    for commit in ordered:
        if buckets:
            previous = buckets[-1][-1]
            within_day = (_timestamp(commit.authored_at) - _timestamp(previous.authored_at)).total_seconds() <= 86400
            shared_module = bool(set(commit.modules) & set(previous.modules))
            shared_keyword = bool(_title_keywords(commit.subject) & _title_keywords(previous.subject))
            if within_day and shared_module and shared_keyword:
                buckets[-1].append(commit)
                continue
        buckets.append([commit])
    groups = []
    for bucket in buckets:
        newest = sorted(bucket, key=lambda commit: _timestamp(commit.authored_at), reverse=True)
        groups.append(FeatureGroup(
            label=_label(newest[0].subject),
            commit_shas=[commit.sha for commit in newest],
            subjects=[commit.subject for commit in newest],
            modules=sorted({module for commit in bucket for module in commit.modules}),
            started_at=min(commit.authored_at for commit in bucket),
            ended_at=max(commit.authored_at for commit in bucket),
            files_changed=sum(commit.files_changed for commit in bucket),
            insertions=sum(commit.insertions for commit in bucket),
            deletions=sum(commit.deletions for commit in bucket),
        ))
    return sorted(groups, key=lambda group: (len(group.commit_shas), group.ended_at), reverse=True)


def rank_module_churn(commits: list[GitCommit], days: int = 30) -> list[dict[str, int | str]]:
    del days
    totals: dict[str, dict[str, int | str]] = {}
    for commit in commits:
        for module in commit.modules or ["unknown"]:
            row = totals.setdefault(module, {"module": module, "files_changed": 0, "insertions": 0, "deletions": 0, "changed_lines": 0})
            row["files_changed"] = int(row["files_changed"]) + commit.files_changed
            row["insertions"] = int(row["insertions"]) + commit.insertions
            row["deletions"] = int(row["deletions"]) + commit.deletions
            row["changed_lines"] = int(row["changed_lines"]) + commit.insertions + commit.deletions
    return sorted(totals.values(), key=lambda row: int(row["changed_lines"]), reverse=True)
