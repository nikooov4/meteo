"""Equivalent to `meteo data generate-scale`; all options are shared."""

import sys

from meteo_bridge.cli import app

if __name__ == "__main__":
    args = sys.argv[1:]
    command = "generate-scale"
    if "--profile" in args:
        index = args.index("--profile")
        if index + 1 >= len(args) or args[index + 1] not in ("legacy-v1", "weather-bootstrap"):
            raise SystemExit("--profile must be legacy-v1 or weather-bootstrap")
        command = "generate-weather" if args[index + 1] == "weather-bootstrap" else command
        del args[index:index+2]
    app(args=["data", command, *args])
