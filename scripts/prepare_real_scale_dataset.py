import sys

from meteo_bridge.cli import app

if __name__ == "__main__":
    app(args=["data", "prepare-real-scale", *sys.argv[1:]])
