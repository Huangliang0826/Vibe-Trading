import json

from src.analytics.version import read_app_version


def test_backend_reads_frontend_package_version(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    assert read_app_version(tmp_path) == "1.2.3"
