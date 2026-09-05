import argparse
import os
from pathlib import Path

from platformdirs import user_config_dir

from . import actions
from .const import APP_NAME

__version__ = "0.2.1"


def run_borg2mqtt():
    parser = argparse.ArgumentParser(
        prog="borg2mqtt",
        description="Send borg repository settings over mqtt",
    )
    default_path = Path(user_config_dir(APP_NAME)) / "config.yml"
    parser.add_argument(
        "-c",
        "--config",
        default=default_path,
        type=Path,
        help="Path to load/save a configuration file. \
                Defaults to $HOME/.config/borg2mqtt/config.yml.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Verbose output. Repeat 1-3 times for varying levels.",
    )

    subparsers = parser.add_subparsers(
        help="Type of operation to perform", dest="operation"
    )

    # ------------------------- Generate configuration file ------------------------- #
    subparsers.add_parser(
        "generate",
        help="Generate sample config file, or make config file from borgmatic config.",
    )

    # ------------------------- Setup Device in HA ------------------------- #
    setup = subparsers.add_parser(
        "setup", help="Send autodiscovery Home Assistant MQTT messages."
    )
    setup.set_defaults(func=actions.setup)

    # ------------------------- Send MQTT sensor messages ------------------------- #
    update = subparsers.add_parser(
        "update", help="Send MQTT message with updated borg repo information."
    )
    update.set_defaults(func=actions.update)
    update.add_argument(
        "-n",
        "--name",
        default=None,
        type=str,
        help="Name of repo in configuration files. \
                 Default runs all of them.",
    )

    # ------------------------- Run borg check ------------------------- #
    check = subparsers.add_parser(
        "check",
        help="Run `borg check` and send the result as an MQTT message.",
    )
    check.set_defaults(func=actions.check)
    check.add_argument(
        "-n",
        "--name",
        default=None,
        type=str,
        help="Name of repo in configuration files. \
                 Default runs all of them.",
    )

    # ------------------------- Report real backup pass/fail status ------------------------- #
    report_status = subparsers.add_parser(
        "report-status",
        help="Read pending backup result files (dropped by a borgmatic "
        "command hook) and publish them to MQTT.",
    )
    report_status.add_argument(
        "-d",
        "--status-dir",
        default=Path(os.environ.get("BORG2MQTT_STATUS_DIR", "/shared/status")),
        type=Path,
        help="Directory to look for backup result JSON files in. \
                Defaults to $BORG2MQTT_STATUS_DIR or /shared/status.",
    )

    # ------------------------- Print configured check schedule ------------------------- #
    subparsers.add_parser(
        "schedule",
        help="Print the configured cron schedule for `check` "
        "(used by the Docker entrypoint).",
    )

    args = parser.parse_args()

    if args.operation == "generate":
        actions.generate(args.config)
    elif args.operation == "schedule":
        print(actions.get_check_cron(args.config))
    elif args.operation == "report-status":
        repos, mqtt = actions.parse(args)
        actions.report_status(repos, mqtt, args.status_dir)
    else:
        repos, mqtt = actions.parse(args)
        args.func(repos, mqtt)


if __name__ == "__main__":
    run_borg2mqtt()
