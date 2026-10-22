import re
import tomllib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def test_visual_studio_links_resolve_without_duplicates():
    solution = (ROOT / "MeteoBridge.sln").read_text(encoding="utf8")
    links = re.findall(r"^\s+(.+?) = \1$", solution, re.MULTILINE)
    files = [link.strip() for link in links if not link.strip().startswith("{") and "|" not in link]
    assert len(files) == len(set(files))
    assert len(files) >= 15
    for relative in files:
        assert (ROOT / relative.replace("\\", "/")).is_file(), relative
    assert "Research archive" not in solution
    assert not any("research" in path for path in files)
    for path in ["web/map_viewer.html", "web/archive_viewer.html", "web/assets/land.json",
                 "scripts/setup_runtime.ps1", "tests/test_project_layout.py"]:
        assert path.replace("/", "\\") in files


def test_csharp_assets_and_runtime_do_not_depend_on_research():
    project = ROOT / "dotnet/MeteoBridge.Era5"
    document = ElementTree.parse(project / "MeteoBridge.Era5.csproj")
    for content in document.findall(".//Content"):
        source = content.attrib["Include"]
        assert "research" not in source and ".venv" not in source
        if source.startswith("../../web/"):
            assert list(project.glob(source)), source
    for filename in ["Program.cs", "NativeNetCdf.cs"]:
        code = (project / filename).read_text(encoding="utf8")
        assert '".venv"' not in code
        assert '"pyproject.toml"' not in code
        assert '"research"' not in code


def test_development_tools_do_not_require_the_removed_application():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf8"))
    assert config["tool"]["uv"]["package"] is False
    assert config["tool"]["pytest"]["ini_options"] == {"testpaths": ["tests"]}
    assert "scripts" not in config["project"]
    assert "build-system" not in config
    assert not (ROOT / "research").exists()
    launcher = (ROOT / "start_app.ps1").read_text(encoding="utf8")
    assert "research" not in launcher and "$Python" not in launcher
