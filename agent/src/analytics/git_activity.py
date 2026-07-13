from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class GitCommit:
    sha: str
    authored_at: str
    author: str
    subject: str
    files_changed: int
    insertions: int
    deletions: int
    modules: list[str] = field(default_factory=list)
    test_files_changed: int = 0


@dataclass(frozen=True)
class GitRelease:
    tag: str
    sha: str
    created_at: str


@dataclass(frozen=True)
class GitActivity:
    commits: list[GitCommit]
    releases: list[GitRelease]
    warnings: list[str]


def _module_for(path: str) -> str:
    normalized = path.lower()
    table = (
        ("frontend/src/pages/scanner", "frontend/scanner"),
        ("frontend/src/components/analytics", "frontend/analytics"),
        ("frontend/src/pages/analytics", "frontend/analytics"),
        ("frontend/", "frontend/core"),
        ("agent/src/scanner/", "backend/scanner"),
        ("agent/src/analytics/", "backend/analytics"),
        ("agent/src/paper_trading/", "backend/paper-trading"),
        ("agent/", "backend/core"),
    )
    for prefix, module in table:
        if normalized.startswith(prefix):
            return module
    return path.split("/", 1)[0] or "root"


class GitActivityReader:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def _run(self, command: list[str]) -> str:
        return subprocess.run(
            command,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout

    def read_commits(self, since: datetime, limit: int = 200) -> list[GitCommit]:
        output = self._run([
            "git", "log", f"--since={since.isoformat()}", f"--max-count={limit}",
            "--date=iso-strict", "--pretty=format:%x1e%H%x1f%aI%x1f%an%x1f%s", "--numstat",
        ])
        commits: list[GitCommit] = []
        for raw in output.split("\x1e"):
            chunk = raw.strip()
            if not chunk:
                continue
            lines = chunk.splitlines()
            header = lines[0].split("\x1f")
            if len(header) != 4:
                continue
            files: list[str] = []
            insertions = deletions = 0
            for line in lines[1:]:
                parts = line.split("\t", 2)
                if len(parts) != 3:
                    continue
                added, removed, path = parts
                insertions += int(added) if added.isdigit() else 0
                deletions += int(removed) if removed.isdigit() else 0
                files.append(path)
            modules = sorted({_module_for(path) for path in files})
            test_files = sum(
                path.startswith(("tests/", "agent/tests/")) or "__tests__" in path
                for path in files
            )
            commits.append(GitCommit(
                sha=header[0], authored_at=header[1], author=header[2], subject=header[3],
                files_changed=len(files), insertions=insertions, deletions=deletions,
                modules=modules, test_files_changed=test_files,
            ))
        return commits

    def read_releases(self) -> list[GitRelease]:
        output = self._run([
            "git", "for-each-ref", "--sort=-creatordate",
            "--format=%(refname:short)%00%(objectname)%00%(creatordate:iso-strict)", "refs/tags",
        ])
        releases: list[GitRelease] = []
        for line in output.splitlines():
            parts = line.split("\x00")
            if len(parts) == 3 and re.fullmatch(r"v\d+\.\d+\.\d+", parts[0]):
                releases.append(GitRelease(tag=parts[0], sha=parts[1], created_at=parts[2]))
        return releases

    def read(self, since: datetime | None = None, limit: int = 200) -> GitActivity:
        since = since or datetime.now(timezone.utc) - timedelta(days=90)
        try:
            return GitActivity(
                commits=self.read_commits(since, limit),
                releases=self.read_releases(),
                warnings=[],
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return GitActivity(commits=[], releases=[], warnings=["git_unavailable"])
