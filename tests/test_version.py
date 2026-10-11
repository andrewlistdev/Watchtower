"""Keep the version in one place: these fail if a release bumps one spot but not the others."""

import re
from pathlib import Path

from watchtower import USER_AGENT, __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_compose_image_tag_matches():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert f"image: watchtower:{__version__}" in compose


def test_changelog_top_entry_matches():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    first = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    assert first == __version__


def test_user_agent():
    assert USER_AGENT == f"Watchtower/{__version__}"
