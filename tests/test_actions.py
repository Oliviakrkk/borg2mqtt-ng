"""Unit tests for borg2mqtt.actions.

No real file-system config is read (config parsing is mocked), and no real
MQTT connections are made. `generate()` tests use pytest's tmp_path fixture
to write a plain example file in an isolated temp directory.
"""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from borg2mqtt import actions
from borg2mqtt.repo import MQTTSettings, Repository

# --------------------------------------------------------------------------- #
# parse()
# --------------------------------------------------------------------------- #


def _args(
    operation: str = "update",
    name: str | None = None,
    verbose: int = 0,
    config: str = "config.yml",
) -> Namespace:
    return Namespace(operation=operation, name=name, verbose=verbose, config=config)


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_returns_repos_and_mqtt(mock_open: MagicMock, mock_safe_load: MagicMock):
    mock_safe_load.return_value = {
        "mqtt": {"host": "broker", "port": 1884},
        "repos": [{"repo": "user@host:/path", "name": "Repo1"}],
    }

    repos, mqtt = actions.parse(_args())

    assert isinstance(mqtt, MQTTSettings)
    assert mqtt.host == "broker"
    assert mqtt.port == 1884
    assert len(repos) == 1
    assert isinstance(repos[0], Repository)
    assert repos[0].name == "Repo1"


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_defaults_mqtt_when_missing(mock_open, mock_safe_load):
    mock_safe_load.return_value = {"repos": [{"repo": "user@host:/path"}]}

    _repos, mqtt = actions.parse(_args())

    assert mqtt == MQTTSettings()


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_raises_when_no_repos(mock_open, mock_safe_load):
    mock_safe_load.return_value = {"mqtt": {}}

    with pytest.raises(ValueError, match="didn't have any repos"):
        actions.parse(_args())


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_passes_verbose_to_repos(mock_open, mock_safe_load):
    mock_safe_load.return_value = {"repos": [{"repo": "user@host:/path"}]}

    repos, _ = actions.parse(_args(verbose=2))

    assert repos[0].verbose == 2


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_filters_repos_by_name_on_update(mock_open, mock_safe_load):
    mock_safe_load.return_value = {
        "repos": [
            {"repo": "user@host:/a", "name": "A"},
            {"repo": "user@host:/b", "name": "B"},
        ]
    }

    repos, _ = actions.parse(_args(operation="update", name="B"))

    assert len(repos) == 1
    assert repos[0].name == "B"


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_raises_when_named_repo_not_found(mock_open, mock_safe_load):
    mock_safe_load.return_value = {"repos": [{"repo": "user@host:/a", "name": "A"}]}

    with pytest.raises(ValueError, match="not found"):
        actions.parse(_args(operation="update", name="doesnotexist"))


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_does_not_filter_when_name_is_none(mock_open, mock_safe_load):
    mock_safe_load.return_value = {
        "repos": [
            {"repo": "user@host:/a", "name": "A"},
            {"repo": "user@host:/b", "name": "B"},
        ]
    }

    repos, _ = actions.parse(_args(operation="update", name=None))

    assert len(repos) == 2


@patch("borg2mqtt.actions.yaml.safe_load")
@patch("builtins.open")
def test_parse_does_not_filter_on_setup_operation(mock_open, mock_safe_load):
    mock_safe_load.return_value = {
        "repos": [
            {"repo": "user@host:/a", "name": "A"},
            {"repo": "user@host:/b", "name": "B"},
        ]
    }

    repos, _ = actions.parse(_args(operation="setup"))

    assert len(repos) == 2


# --------------------------------------------------------------------------- #
# generate()
# --------------------------------------------------------------------------- #


def test_generate_raises_if_file_exists(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("existing")

    with pytest.raises(ValueError, match="exists"):
        actions.generate(path)


def test_generate_creates_parent_directory_and_file(tmp_path):
    path = tmp_path / "nested" / "dir" / "config.yml"

    actions.generate(path)

    assert path.exists()
    assert path.read_text() == actions.EXAMPLE_CONFIG


def test_generate_writes_into_existing_directory(tmp_path):
    path = tmp_path / "config.yml"

    actions.generate(path)

    assert path.read_text() == actions.EXAMPLE_CONFIG


# --------------------------------------------------------------------------- #
# setup() / update() dispatchers
# --------------------------------------------------------------------------- #


def test_setup_calls_setup_on_each_repo():
    repo1, repo2 = MagicMock(), MagicMock()
    mqtt = MQTTSettings()

    actions.setup([repo1, repo2], mqtt)

    repo1.setup.assert_called_once_with(mqtt)
    repo2.setup.assert_called_once_with(mqtt)


def test_update_calls_update_on_each_repo():
    repo1, repo2 = MagicMock(), MagicMock()
    mqtt = MQTTSettings()

    actions.update([repo1, repo2], mqtt)

    repo1.update.assert_called_once_with(mqtt)
    repo2.update.assert_called_once_with(mqtt)


def test_setup_with_no_repos_does_nothing():
    actions.setup([], MQTTSettings())  # should not raise


def test_update_with_no_repos_does_nothing():
    actions.update([], MQTTSettings())  # should not raise
