"""Equivalent to `meteo data generate-scale`; all options are shared."""

import sys

from meteo_bridge.cli import app

if __name__ == "__main__":
    app(args=["data", "generate-scale", *sys.argv[1:]])
