import pytest

import main


def test_load_json_or_exit_returns_parsed_content_for_valid_file(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert main._load_json_or_exit(path) == {"a": 1}


def test_load_json_or_exit_exits_cleanly_for_missing_file(tmp_path, capsys):
    path = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as exc_info:
        main._load_json_or_exit(path)
    assert exc_info.value.code == 1
    assert "nicht gefunden" in capsys.readouterr().err


def test_load_json_or_exit_exits_cleanly_for_malformed_json(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main._load_json_or_exit(path)
    assert exc_info.value.code == 1
    assert "ungültiges JSON" in capsys.readouterr().err
