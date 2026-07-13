"""Tests for the startup file-descriptor limit raise (api_server._raise_fd_limit)."""

from __future__ import annotations

import resource

import pytest

import api_server


@pytest.fixture(autouse=True)
def _restore_rlimit():
    original = resource.getrlimit(resource.RLIMIT_NOFILE)
    yield
    resource.setrlimit(resource.RLIMIT_NOFILE, original)


def test_raises_soft_limit_toward_target(monkeypatch):
    calls: list[tuple[int, int]] = []
    hard = 32768
    monkeypatch.setattr(resource, "getrlimit", lambda _which: (256, hard))
    monkeypatch.setattr(resource, "setrlimit", lambda _which, limits: calls.append(limits))

    api_server._raise_fd_limit(target=16384)

    assert calls == [(16384, hard)]


def test_does_not_lower_an_already_high_limit(monkeypatch):
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _which: (65536, 65536))
    monkeypatch.setattr(resource, "setrlimit", lambda _which, limits: calls.append(limits))

    api_server._raise_fd_limit(target=16384)

    assert calls == []  # already above target — no change


def test_clamps_target_to_the_hard_limit(monkeypatch):
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _which: (256, 4096))
    monkeypatch.setattr(resource, "setrlimit", lambda _which, limits: calls.append(limits))

    api_server._raise_fd_limit(target=16384)

    assert calls == [(4096, 4096)]  # cannot exceed the hard limit


def test_infinite_hard_limit_allows_full_target(monkeypatch):
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _which: (256, resource.RLIM_INFINITY))
    monkeypatch.setattr(resource, "setrlimit", lambda _which, limits: calls.append(limits))

    api_server._raise_fd_limit(target=16384)

    assert calls == [(16384, resource.RLIM_INFINITY)]


def test_setrlimit_failure_is_swallowed(monkeypatch, capsys):
    def boom(_which, _limits):
        raise OSError("denied")

    monkeypatch.setattr(resource, "getrlimit", lambda _which: (256, 65536))
    monkeypatch.setattr(resource, "setrlimit", boom)

    api_server._raise_fd_limit(target=16384)  # must not raise

    assert "could not raise RLIMIT_NOFILE" in capsys.readouterr().out
