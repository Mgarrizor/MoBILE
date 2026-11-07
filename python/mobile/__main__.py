"""Command line; `mobile help` describes it."""

import argparse
import os
import shutil
import sys

from .config import Config, ConfigError, example_config
from .help import TEXT
from .runner import Runner
from .setup import load_setup

REQUIRED_TOOLS = ("make", "gfortran", "nf-config", "nc-config")


def _pairs(items, convert):
    return {key: convert(value) for key, value in (item.split("=", 1) for item in items)}


def _exit_if_tools_missing():
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        sys.exit(f"Not found, but needed to compile MoBILE: {', '.join(missing)}. See `mobile help`.")


def _run(args, config):
    config = config.with_params(**_pairs(args.set, float)).with_run(**_pairs(args.run, int))
    result = Runner(config).run(args.name, on_progress=lambda event: print(event.message, flush=True))
    print(f"{result.status}: {result.run_dir}")
    if not result.ok:
        print(result.log_tail())
    sys.exit(0 if result.ok else 1)


def main():
    parser = argparse.ArgumentParser(prog="mobile", description="Run or explore MoBILE. See `mobile help`.")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("help", help="how to use this package")

    example = commands.add_parser("example", help="write a copy of the example configuration")
    example.add_argument("destination", help="file to write")

    run = commands.add_parser("run", help="run the model once")
    run.add_argument("config", nargs="?", help="YAML configuration file (default: the bundled example)")
    run.add_argument("--set", nargs="*", default=[], metavar="NAME=VALUE", help="&CONST parameter, in the units of the model, instead of its compiled default")
    run.add_argument("--run", nargs="*", default=[], metavar="NAME=VALUE", help="run setting, e.g. seed=1")
    run.add_argument("--name", help="run folder name (default: date and random suffix)")

    app = commands.add_parser("gui", aliases=["app"], help="open the GUI in your browser")
    app.add_argument("config", nargs="?", help="start from a YAML configuration file (default: the settings used last, or the bundled example)")
    app.add_argument("--port", type=int, default=8000, help="first port to try (default: %(default)s)")
    app.add_argument("--no-browser", action="store_true", help="do not open a browser window")

    args = parser.parse_args()

    if args.command in (None, "help"):
        print(TEXT, end="")
        return
    if args.command == "example":
        shutil.copy(example_config(), args.destination)
        print(f"Wrote {args.destination}")
        return

    _exit_if_tools_missing()
    try:
        if args.command in ("gui", "app"):
            from .app import launch

            # The GUI is set up in its Setup panel: it starts where it was left
            config = Config.load(args.config) if args.config else load_setup(os.environ.get("MOBILE")) or Config.load()
            launch(config, port=args.port, browser=not args.no_browser)
            return
        config = Config.load(args.config)
        _run(args, config)
    except ConfigError as error:
        sys.exit(f"Configuration error:\n{error}")


if __name__ == "__main__":
    main()
