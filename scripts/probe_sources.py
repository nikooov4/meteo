"""Bounded metadata discovery for the two explicitly selected public sources."""

import json
from pathlib import Path

import httpx

from meteo_bridge.resources import atomic_json

urls = {
    "ncar_list": "https://nsf-ncar-era5.s3.us-west-2.amazonaws.com/?list-type=2&prefix=e5.oper.fc.sfc.accumu/202301/&max-keys=1000",
    "dwd_list": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/historical/",
}

if __name__ == "__main__":
    root = Path("data/manifests/source-probes")
    root.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, url in urls.items():
        try:
            response = httpx.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            if len(response.content) > 4 * 2**20:
                raise ValueError("metadata size limit")
            (root / f"{name}.txt").write_bytes(response.content)
            report[name] = {"url": url, "status": response.status_code, "bytes": len(response.content)}
            if name == "ncar_list":
                import xml.etree.ElementTree as ET

                xml = ET.fromstring(response.content)
                print([e.text for e in xml.iter() if e.tag.endswith("Key") and "_tp." in (e.text or "")])
            else:
                import re

                print(re.findall(r'href="([^"]*RR_00(?:433|191)[^"]*)"', response.text)[:10])
        except Exception as exc:
            report[name] = {"url": url, "error": str(exc)}
    atomic_json(root / "probe.json", report)
    print(json.dumps(report, indent=2))
