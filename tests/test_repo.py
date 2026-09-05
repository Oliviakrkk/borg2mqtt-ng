"""Unit tests for borg2mqtt.repo.

All subprocess calls to `borg` and all MQTT network activity are mocked;
no real command is executed and no real connection is made.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from borg2mqtt.repo import MQTTSettings, Repository


# --------------------------------------------------------------------------- #
# MQTTSettings
# --------------------------------------------------------------------------- #


def test_mqtt_settings_defaults():
    settings = MQTTSettings()

    assert settings.host == "localhost"
    assert settings.port == 1883
    assert settings.user == ""
    assert settings.password == ""


def test_mqtt_settings_custom_values():
    settings = MQTTSettings(host="broker.example.com", port=8883, user="u", password="p")

    assert settings.host == "broker.example.com"
    assert settings.port == 8883
    assert settings.user == "u"
    assert settings.password == "p"


# --------------------------------------------------------------------------- #
# Repository.__post_init__
# --------------------------------------------------------------------------- #


def test_repository_defaults_name_to_repo():
    repo = Repository(repo="user@host:/path/to/backup")

    assert repo.name == "user@host:/path/to/backup"


def test_repository_uses_explicit_name():
    repo = Repository(repo="user@host:/path/to/backup", name="My Backup")

    assert repo.name == "My Backup"


def test_repository_slug_and_state_topic_from_name():
    repo = Repository(repo="user@host:/path/to/backup", name="My Cool Backup!")

    assert repo.slug == "my_cool_backup"
    assert repo.state_topic == f"borg/{repo.slug}/state"


def test_repository_invalid_units_raises():
    with pytest.raises(ValueError, match="Unknown units"):
        Repository(repo="user@host:/path", units="XB")


@pytest.mark.parametrize("units", ["kB", "MB", "GB", "TB"])
def test_repository_valid_units_accepted(units):
    repo = Repository(repo="user@host:/path", units=units)

    assert repo.units == units


def test_repository_defaults():
    repo = Repository(repo="user@host:/path")

    assert repo.key == ""
    assert repo.rsh == ""
    assert repo.verbose == 0
    assert repo.units == "GB"


# --------------------------------------------------------------------------- #
# Repository._ask_borg
# --------------------------------------------------------------------------- #


@patch("borg2mqtt.repo.subprocess.run")
def test_ask_borg_runs_expected_command(mock_run):
    mock_run.return_value = MagicMock(stdout=b'{"ok": true}')
    repo = Repository(repo="user@host:/path", key="secret", verbose=0)

    result = repo._ask_borg("info")

    assert result == {"ok": True}
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["borg", "info", "user@host:/path", "--json"]
    assert kwargs["env"]["BORG_PASSPHRASE"] == "secret"
    assert "BORG_RSH" not in kwargs["env"]


@patch("borg2mqtt.repo.subprocess.run")
def test_ask_borg_sets_rsh_when_provided(mock_run):
    mock_run.return_value = MagicMock(stdout=b"{}")
    repo = Repository(repo="user@host:/path", rsh="ssh -p 2222")

    repo._ask_borg("list")

    _, kwargs = mock_run.call_args
    assert kwargs["env"]["BORG_RSH"] == "ssh -p 2222"


@patch("borg2mqtt.repo.subprocess.run")
def test_ask_borg_does_not_mutate_os_environ(mock_run):
    mock_run.return_value = MagicMock(stdout=b"{}")
    repo = Repository(repo="user@host:/path", key="secret")

    with patch.dict("os.environ", {}, clear=False):
        import os

        before = dict(os.environ)
        repo._ask_borg("info")
        assert os.environ == before


@patch("builtins.print")
@patch("borg2mqtt.repo.subprocess.run")
def test_ask_borg_verbose_prints_command_and_result(mock_run, mock_print):
    mock_run.return_value = MagicMock(stdout=b'{"a": 1}')
    repo = Repository(repo="user@host:/path", verbose=3)

    repo._ask_borg("info")

    assert mock_print.called


# --------------------------------------------------------------------------- #
# Repository._get_updates
# --------------------------------------------------------------------------- #


def _sample_borg_info():
    return {
        "repository": {"location": "user@host:/path", "id": "repo-id-123"},
        "cache": {
            "stats": {
                "total_unique_chunks": 10,
                "total_chunks": 20,
                "unique_size": 1_000_000_000,
                "unique_csize": 500_000_000,
                "total_size": 2_000_000_000,
                "total_csize": 900_000_000,
            }
        },
    }


def _sample_borg_list():
    return {
        "archives": [{"name": "a1"}, {"name": "a2"}],
        "repository": {"last_modified": "2024-01-15T10:30:00.123456"},
    }


@patch.object(Repository, "_ask_borg")
def test_get_updates_parses_info_and_list(mock_ask_borg):
    mock_ask_borg.side_effect = [_sample_borg_info(), _sample_borg_list()]
    repo = Repository(repo="user@host:/path", units="GB")

    info = repo._get_updates()

    assert info["location"] == "user@host:/path"
    assert info["id"] == "repo-id-123"
    assert info["chunks_unique"] == 10
    assert info["chunks_total"] == 20
    assert info["num_backups"] == 2
    assert info["size_dedup"] == pytest.approx(1.0)
    assert info["size_dedup_comp"] == pytest.approx(0.5)
    assert info["size_og"] == pytest.approx(2.0)
    assert info["size_og_comp"] == pytest.approx(0.9)
    assert info["most_recent"].startswith("2024-01-15T10:30:00.123456")


@patch.object(Repository, "_ask_borg")
def test_get_updates_calls_ask_borg_with_info_then_list(mock_ask_borg):
    mock_ask_borg.side_effect = [_sample_borg_info(), _sample_borg_list()]
    repo = Repository(repo="user@host:/path")

    repo._get_updates()

    assert mock_ask_borg.call_args_list[0].args == ("info",)
    assert mock_ask_borg.call_args_list[1].args == ("list",)


@patch.object(Repository, "_ask_borg")
def test_get_updates_units_scale_kb(mock_ask_borg):
    mock_ask_borg.side_effect = [_sample_borg_info(), _sample_borg_list()]
    repo = Repository(repo="user@host:/path", units="kB")

    info = repo._get_updates()

    assert info["size_dedup"] == pytest.approx(1_000_000.0)


# --------------------------------------------------------------------------- #
# Repository.update
# --------------------------------------------------------------------------- #


@patch("borg2mqtt.repo.publish.single")
@patch.object(Repository, "_get_updates")
def test_update_publishes_single_mqtt_message(mock_get_updates, mock_publish):
    mock_get_updates.return_value = {"num_backups": 3}
    repo = Repository(repo="user@host:/path", name="MyRepo")
    mqtt = MQTTSettings(host="mqtt.local", port=1884, user="bob", password="pw")

    repo.update(mqtt)

    mock_publish.assert_called_once()
    _, kwargs = mock_publish.call_args
    assert mock_publish.call_args.args[0] == repo.state_topic
    assert kwargs["payload"] == json.dumps({"num_backups": 3})
    assert kwargs["hostname"] == "mqtt.local"
    assert kwargs["port"] == 1884
    assert kwargs["auth"] == {"username": "bob", "password": "pw"}
    assert kwargs["retain"] is True


@patch("borg2mqtt.repo.publish.single")
@patch.object(Repository, "_get_updates")
def test_update_never_touches_network_directly(mock_get_updates, mock_publish):
    """Ensure update() only goes through the mocked publish.single, never a real socket."""
    mock_get_updates.return_value = {}
    repo = Repository(repo="user@host:/path")

    repo.update(MQTTSettings())

    mock_publish.assert_called_once()


# --------------------------------------------------------------------------- #
# Repository.setup
# --------------------------------------------------------------------------- #


@patch("borg2mqtt.repo.publish.single")
@patch.object(Repository, "_get_updates")
def test_setup_publishes_one_message_per_info_key(mock_get_updates, mock_publish):
    info = {
        "chunks_total": 5,
        "chunks_unique": 2,
        "location": "loc",
        "id": "repo-id",
        "most_recent": "2024-01-01T00:00:00+00:00",
        "num_backups": 1,
        "size_dedup": 1.0,
        "size_dedup_comp": 0.5,
        "size_og": 2.0,
        "size_og_comp": 1.0,
    }
    mock_get_updates.return_value = info
    repo = Repository(repo="user@host:/path", name="MyRepo")

    repo.setup(MQTTSettings())

    assert mock_publish.call_count == len(info)


@patch("borg2mqtt.repo.publish.single")
@patch.object(Repository, "_get_updates")
def test_setup_payload_contains_device_and_topic(mock_get_updates, mock_publish):
    info = {"num_backups": 1, "id": "repo-id"}
    # Only include keys present in payload_unique to avoid KeyError
    mock_get_updates.return_value = info
    repo = Repository(repo="user@host:/path", name="MyRepo")
    mqtt = MQTTSettings(host="broker", port=1883)

    repo.setup(mqtt)

    topics = [call.args[0] for call in mock_publish.call_args_list]
    assert f"homeassistant/sensor/{repo.slug}/num_backups/config" in topics
    assert f"homeassistant/sensor/{repo.slug}/id/config" in topics

    payloads = [json.loads(call.kwargs["payload"]) for call in mock_publish.call_args_list]
    for payload in payloads:
        assert payload["device"]["identifiers"] == ["repo-id"]
        assert payload["device"]["name"] == "MyRepo"
        assert payload["device"]["manufacturer"] == "Borg"
        assert payload["state_topic"] == repo.state_topic

    num_backups_payload = next(
        json.loads(call.kwargs["payload"])
        for call in mock_publish.call_args_list
        if call.args[0].endswith("/num_backups/config")
    )
    assert num_backups_payload["unique_id"] == f"{repo.slug}_num_backups"
    assert num_backups_payload["default_entity_id"] == f"{repo.slug}_num_backups"
    assert num_backups_payload["value_template"] == "{{value_json.num_backups}}"
    assert num_backups_payload["name"] == "Total Backups"


@patch("borg2mqtt.repo.publish.single")
@patch.object(Repository, "_get_updates")
def test_setup_size_sensors_include_unit_of_measure(mock_get_updates, mock_publish):
    mock_get_updates.return_value = {"size_dedup": 1.23, "id": "repo-id"}
    repo = Repository(repo="user@host:/path", units="TB")

    repo.setup(MQTTSettings())

    payload = next(
        json.loads(call.kwargs["payload"])
        for call in mock_publish.call_args_list
        if call.args[0].endswith("/size_dedup/config")
    )
    assert payload["unit_of_meas"] == "TB"
    assert payload["device_class"] == "data_size"
