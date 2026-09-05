from __future__ import annotations

import datetime
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pprint import pprint
from typing import TYPE_CHECKING, Any, Literal, cast

from paho.mqtt import publish
from slugify import slugify

from .const import APP_NAME, UNITS

if TYPE_CHECKING:
    from paho.mqtt.publish import TLSParameter


@dataclass
class MQTTSettings:
    host: str = "localhost"
    port: int = 1883
    user: str = ""
    password: str = ""
    tls: bool = False
    ca_certs: str = ""
    certfile: str = ""
    keyfile: str = ""
    insecure: bool = False

    def tls_params(self) -> TLSParameter | None:
        """Build the tls kwarg for paho's publish functions, or None if disabled"""

        if not self.tls:
            return None

        params: dict[str, Any] = {}
        if self.ca_certs:
            params["ca_certs"] = self.ca_certs
        if self.certfile:
            params["certfile"] = self.certfile
        if self.keyfile:
            params["keyfile"] = self.keyfile
        if self.insecure:
            params["insecure"] = True
        return cast("TLSParameter", params)


@dataclass
class Repository:
    repo: str
    key: str = ""
    rsh: str = ""
    verbose: int = 0
    name: str | None = None
    units: str = "GB"

    def __post_init__(self):
        # Clean up arguments
        if self.units not in UNITS:
            raise ValueError(f"Unknown units {self.units} were used")

        # Parse name
        if self.name is None:
            self.name = self.repo

        # Make state topics
        self.slug = slugify(self.name, separator="_")
        self.state_topic = f"borg/{self.slug}/state"
        self.check_topic = f"borg/{self.slug}/check"
        self.result_topic = f"borg/{self.slug}/result"

    def _ask_borg(self, command: Literal["info", "list"], target: str | None = None):
        """Poll borg for a response"""

        env = os.environ.copy()
        env["BORG_PASSPHRASE"] = self.key

        # Get info about all repos
        arguments = [
            "borg",
            command,
            target if target is not None else self.repo,
            "--json",
        ]

        if self.rsh != "":
            env["BORG_RSH"] = self.rsh

        if self.verbose >= 2:
            print(f"[{APP_NAME}][{self.name}] Running {' '.join(arguments)}")

        result = subprocess.run(arguments, stdout=subprocess.PIPE, env=env, check=False)
        result = json.loads(result.stdout)

        if self.verbose >= 3:
            print(f"[{APP_NAME}][{self.name}] Got back")
            pprint(result)

        return result

    def _publish(self, mqtt: MQTTSettings, topic: str, payload: dict[str, Any]):
        """Publish a retained JSON payload to a topic"""

        publish.single(
            topic,
            payload=json.dumps(payload),
            hostname=mqtt.host,
            port=mqtt.port,
            auth={"username": mqtt.user, "password": mqtt.password},
            tls=mqtt.tls_params(),
            retain=True,
        )

    def _get_updates(self):
        """Ask borg for information and parse the results"""

        # Ask borg for all info
        repo_info = self._ask_borg("info")
        repo_list = self._ask_borg("list")

        date_format_code = "%Y-%m-%dT%H:%M:%S.%f"

        # Parse through it all
        scale = UNITS[self.units]
        cache_stats = repo_info["cache"]["stats"]
        info = {
            "location": repo_info["repository"]["location"],
            "id": repo_info["repository"]["id"],
            "chunks_unique": cache_stats["total_unique_chunks"],
            "chunks_total": cache_stats["total_chunks"],
            "size_dedup": round(float(cache_stats["unique_size"]) * scale, 8),
            "size_dedup_comp": round(
                float(cache_stats["unique_csize"]) * scale,
                8,
            ),
            "size_og": round(float(cache_stats["total_size"]) * scale, 8),
            "size_og_comp": round(float(cache_stats["total_csize"]) * scale, 8),
            "num_backups": len(repo_list["archives"]),
            # Time is returned in local time,
            # but is missing the timezone offset on the stamp
            # HA needs timestamp in ISO 8601 format with timezone
            "most_recent": datetime.datetime.strptime(
                repo_list["repository"]["last_modified"], date_format_code
            )
            .astimezone()
            .isoformat(),
        }

        if repo_list["archives"]:
            last_archive_name = repo_list["archives"][-1]["name"]
            archive_info = self._ask_borg(
                "info", target=f"{self.repo}::{last_archive_name}"
            )
            archive = archive_info["archives"][0]
            archive_stats = archive["stats"]
            info.update(
                {
                    "last_backup_name": archive["name"],
                    "last_backup_start": datetime.datetime.strptime(
                        archive["start"], date_format_code
                    )
                    .astimezone()
                    .isoformat(),
                    "last_backup_end": datetime.datetime.strptime(
                        archive["end"], date_format_code
                    )
                    .astimezone()
                    .isoformat(),
                    "last_backup_duration": round(archive["duration"], 2),
                    "last_backup_files": archive_stats["nfiles"],
                    "last_backup_size_og": round(
                        float(archive_stats["original_size"]) * scale, 8
                    ),
                    "last_backup_size_comp": round(
                        float(archive_stats["compressed_size"]) * scale, 8
                    ),
                    "last_backup_size_dedup": round(
                        float(archive_stats["deduplicated_size"]) * scale, 8
                    ),
                }
            )

        return info

    def _run_check(self):
        """Run `borg check` against the repository and parse the results"""

        env = os.environ.copy()
        env["BORG_PASSPHRASE"] = self.key

        arguments = ["borg", "check", self.repo]

        if self.rsh != "":
            env["BORG_RSH"] = self.rsh

        if self.verbose >= 2:
            print(f"[{APP_NAME}][{self.name}] Running {' '.join(arguments)}")

        start = datetime.datetime.now().astimezone()
        result = subprocess.run(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            check=False,
        )
        end = datetime.datetime.now().astimezone()

        if self.verbose >= 3:
            print(f"[{APP_NAME}][{self.name}] Check output:")
            print(result.stdout.decode(errors="replace"))

        # borg's exit codes: 0 = success, 1 = warning, anything else = error
        state = {0: "ok", 1: "warning"}.get(result.returncode, "error")

        return {
            "check_state": state,
            "check_timestamp": end.isoformat(),
            "check_duration": round((end - start).total_seconds(), 2),
        }

    def update(self, mqtt: MQTTSettings):
        """Send all updated info over MQTT"""

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Getting update information")

        info = self._get_updates()

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Sending MQTT update")

        if self.verbose >= 2:
            print(
                f"[{APP_NAME}][{self.name}] Payload for send to MQTT: {json.dumps(info)}"
            )

        self._publish(mqtt, self.state_topic, info)

    def check(self, mqtt: MQTTSettings):
        """Run `borg check` and send the result over MQTT"""

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Running consistency check")

        info = self._run_check()

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Sending MQTT check result")

        if self.verbose >= 2:
            print(
                f"[{APP_NAME}][{self.name}] Payload for send to MQTT: {json.dumps(info)}"
            )

        self._publish(mqtt, self.check_topic, info)

    def report_status(self, mqtt: MQTTSettings, status_dir: Path) -> bool:
        """Look for a pending backup-result file (dropped by a borgmatic hook)
        belonging to this repo and publish it over MQTT.

        Files are matched by their `repository` field rather than filename, so
        this doesn't depend on how borgmatic's `{repository_label}` happens to
        be quoted/escaped on disk. Malformed files are renamed to `.invalid`
        so they don't get retried forever; matched files are removed once
        published.
        """

        if not status_dir.is_dir():
            return False

        for status_file in sorted(status_dir.glob("*.json")):
            try:
                with open(status_file) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                if self.verbose >= 1:
                    print(
                        f"[{APP_NAME}][{self.name}] Ignoring unreadable status "
                        f"file {status_file}: {e}"
                    )
                status_file.rename(status_file.with_suffix(".invalid"))
                continue

            if data.get("repository") != self.name:
                continue

            result = {
                "last_result": data.get("status", "unknown"),
                "last_result_error": data.get("error", ""),
                "last_result_timestamp": data.get("timestamp", ""),
            }

            if self.verbose >= 1:
                print(
                    f"[{APP_NAME}][{self.name}] Publishing backup result "
                    f"from {status_file}"
                )
            if self.verbose >= 2:
                print(
                    f"[{APP_NAME}][{self.name}] Payload for send to MQTT: "
                    f"{json.dumps(result)}"
                )

            self._publish(mqtt, self.result_topic, result)
            status_file.unlink()
            return True

        return False

    def setup(self, mqtt: MQTTSettings):
        """Send MQTT autodiscovery message"""

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Getting setup information")

        # Get all information from repository
        info = self._get_updates()

        # Things unique to each sensor
        payload_unique = {
            "chunks_total": {"name": "Chunks Total"},
            "chunks_unique": {"name": "Chunks Unique"},
            "location": {"name": "Location", "enabled_by_default": False},
            "id": {"name": "ID", "enabled_by_default": False},
            "most_recent": {"name": "Timestamp", "device_class": "timestamp"},
            "num_backups": {"name": "Total Backups"},
            "size_dedup": {
                "name": "Dedup Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "size_dedup_comp": {
                "name": "Dedup Compressed Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "size_og": {
                "name": "Original Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "size_og_comp": {
                "name": "Original Compressed Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "last_backup_name": {"name": "Last Backup Name"},
            "last_backup_start": {
                "name": "Last Backup Start",
                "device_class": "timestamp",
            },
            "last_backup_end": {
                "name": "Last Backup End",
                "device_class": "timestamp",
            },
            "last_backup_duration": {
                "name": "Last Backup Duration",
                "device_class": "duration",
                "unit_of_meas": "s",
            },
            "last_backup_files": {"name": "Last Backup Files"},
            "last_backup_size_og": {
                "name": "Last Backup Original Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "last_backup_size_comp": {
                "name": "Last Backup Compressed Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
            "last_backup_size_dedup": {
                "name": "Last Backup Deduplicated Size",
                "device_class": "data_size",
                "unit_of_meas": self.units,
            },
        }

        # `borg check` sensors are published to their own state topic, since
        # checks are run independently (and much less often) than updates
        check_payload_unique = {
            "check_state": {"name": "Check State"},
            "check_timestamp": {"name": "Check Timestamp", "device_class": "timestamp"},
            "check_duration": {
                "name": "Check Duration",
                "device_class": "duration",
                "unit_of_meas": "s",
            },
        }

        # Reports the real pass/fail outcome of the last borgmatic run itself
        # (as opposed to `last_backup_*` above, which only reflects whatever
        # archive already exists in the repo). Populated by `report-status`
        # from a file dropped by a borgmatic command hook.
        result_payload_unique = {
            "last_result": {"name": "Last Backup Result"},
            "last_result_error": {
                "name": "Last Backup Error",
                "enabled_by_default": False,
            },
            "last_result_timestamp": {
                "name": "Last Backup Result Timestamp",
                "device_class": "timestamp",
            },
        }

        device = {
            "identifiers": [info["id"]],
            "name": self.name,
            "model": "Borg Repository",
            "manufacturer": "Borg",
        }

        if self.verbose >= 1:
            print(f"[{APP_NAME}][{self.name}] Sending MQTT setup msgs")

        # Check and result sensors are always set up (a check/backup may not
        # have run yet), update sensors only exist if `info` actually
        # produced them
        keys_to_setup = (
            list(info) + list(check_payload_unique) + list(result_payload_unique)
        )
        payload_unique = {
            **payload_unique,
            **check_payload_unique,
            **result_payload_unique,
        }

        for key in keys_to_setup:
            unique = payload_unique[key]
            if key in check_payload_unique:
                state_topic = self.check_topic
            elif key in result_payload_unique:
                state_topic = self.result_topic
            else:
                state_topic = self.state_topic
            topic = f"homeassistant/sensor/{self.slug}/{key}/config"
            payload = {**unique, "state_topic": state_topic, "device": device}
            payload["default_entity_id"] = f"{self.slug}_{key}"
            payload["unique_id"] = f"{self.slug}_{key}"
            payload["value_template"] = f"{{{{value_json.{key}}}}}"

            self._publish(mqtt, topic, payload)
