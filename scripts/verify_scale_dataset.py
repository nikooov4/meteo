import sys

from meteo_bridge.cli import app

if __name__ == "__main__":
    app(args=["data", "verify-scale", *sys.argv[1:]])
