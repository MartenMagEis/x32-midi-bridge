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


# ---- _bootstrap_from_example ----

def test_bootstrap_from_example_seeds_missing_file(tmp_path, capsys):
    example = tmp_path / "config.example.json"
    example.write_text('{"a": 1}', encoding="utf-8")
    real = tmp_path / "config.json"

    main._bootstrap_from_example(real, example)

    assert real.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")
    assert "nicht gefunden" in capsys.readouterr().out


def test_bootstrap_from_example_never_touches_an_existing_real_file(tmp_path):
    example = tmp_path / "config.example.json"
    example.write_text('{"a": 1}', encoding="utf-8")
    real = tmp_path / "config.json"
    real.write_text('{"a": 999, "custom": true}', encoding="utf-8")

    main._bootstrap_from_example(real, example)

    assert real.read_text(encoding="utf-8") == '{"a": 999, "custom": true}'


def test_bootstrap_from_example_is_a_noop_when_example_is_also_missing(tmp_path):
    example = tmp_path / "config.example.json"
    real = tmp_path / "config.json"

    main._bootstrap_from_example(real, example)  # must not raise

    assert not real.exists()
