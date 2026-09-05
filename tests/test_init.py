"""Unit tests for borg2mqtt.run_borg2mqtt (CLI entrypoint).

All calls into `actions` are mocked, so no real config file is read/written
and no real MQTT/borg command ever runs.
"""

from unittest.mock import MagicMock, patch

import pytest

from borg2mqtt import run_borg2mqtt


@patch("borg2mqtt.actions.generate")
def test_generate_operation_calls_actions_generate(mock_generate, monkeypatch):
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "generate"])

    run_borg2mqtt()

    mock_generate.assert_called_once()


@patch("borg2mqtt.actions.parse")
def test_setup_operation_calls_func_with_parsed_repos_and_mqtt(mock_parse, monkeypatch):
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "setup"])
    repos, mqtt = MagicMock(), MagicMock()
    mock_parse.return_value = (repos, mqtt)

    with patch("borg2mqtt.actions.setup") as mock_setup:
        run_borg2mqtt()

    mock_parse.assert_called_once()
    mock_setup.assert_called_once_with(repos, mqtt)


@patch("borg2mqtt.actions.parse")
def test_update_operation_calls_func_with_parsed_repos_and_mqtt(
    mock_parse, monkeypatch
):
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "update", "--name", "MyRepo"])
    repos, mqtt = MagicMock(), MagicMock()
    mock_parse.return_value = (repos, mqtt)

    with patch("borg2mqtt.actions.update") as mock_update:
        run_borg2mqtt()

    args = mock_parse.call_args.args[0]
    assert args.name == "MyRepo"
    mock_update.assert_called_once_with(repos, mqtt)


def test_update_name_defaults_to_none(monkeypatch):
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "update"])

    with (
        patch("borg2mqtt.actions.parse") as mock_parse,
        patch("borg2mqtt.actions.update"),
    ):
        mock_parse.return_value = (MagicMock(), MagicMock())
        run_borg2mqtt()

        args = mock_parse.call_args.args[0]
        assert args.name is None


def test_verbose_flag_counts_occurrences(monkeypatch):
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "-vv", "setup"])

    with (
        patch("borg2mqtt.actions.parse") as mock_parse,
        patch("borg2mqtt.actions.setup"),
    ):
        mock_parse.return_value = (MagicMock(), MagicMock())
        run_borg2mqtt()

        args = mock_parse.call_args.args[0]
        assert args.verbose == 2


def test_custom_config_path_is_used(monkeypatch, tmp_path):
    config_path = tmp_path / "custom.yml"
    monkeypatch.setattr("sys.argv", ["borg2mqtt", "-c", str(config_path), "setup"])

    with (
        patch("borg2mqtt.actions.parse") as mock_parse,
        patch("borg2mqtt.actions.setup"),
    ):
        mock_parse.return_value = (MagicMock(), MagicMock())
        run_borg2mqtt()

        args = mock_parse.call_args.args[0]
        assert str(args.config) == str(config_path)


def test_no_operation_calls_parse_but_fails_dispatching_func(monkeypatch):
    """With no subcommand, argparse leaves operation=None, so the code still goes
    through the actions.parse() branch, but there is no args.func to dispatch to."""
    monkeypatch.setattr("sys.argv", ["borg2mqtt"])

    with patch("borg2mqtt.actions.parse") as mock_parse:
        mock_parse.return_value = (MagicMock(), MagicMock())
        with pytest.raises(AttributeError):
            # There's no args.func set when no subcommand is given,
            # so accessing it raises - confirming no real action is dispatched.
            run_borg2mqtt()
        mock_parse.assert_called_once()
