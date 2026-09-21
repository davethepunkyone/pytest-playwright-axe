"""Update the pytest-playwright minimum to the release from 12 months ago."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
PYPI_URL = "https://pypi.org/pypi/pytest-playwright/json"
DEPENDENCY_PATTERN = re.compile(r"pytest-playwright>=([0-9][^\"\s)]*)")
README_DEPENDENCY_PATTERN = re.compile(
    r"(?P<prefix>pytest-playwright`\]\([^)]*\)\s+>=)(?P<version>[0-9][^\s)]*)"
)


def twelve_months_ago(today: date) -> date:
    """Return the same calendar date in the previous year."""

    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def version_key(version: str) -> tuple[int, ...]:
    """Return a sortable key for the numeric pytest-playwright versions."""

    return tuple(int(part) for part in version.split("."))


def supported_version(as_of: date) -> str:
    """Find the newest release uploaded on or before the compatibility date."""

    with urlopen(PYPI_URL, timeout=30) as response:
        metadata = json.load(response)

    candidates: list[tuple[tuple[int, ...], str]] = []
    for version, files in metadata["releases"].items():
        try:
            parsed_version = version_key(version)
        except ValueError:
            continue

        upload_dates = [
            datetime.fromisoformat(
                file["upload_time_iso_8601"].replace("Z", "+00:00")
            ).date()
            for file in files
            if file.get("upload_time_iso_8601")
        ]
        if upload_dates and min(upload_dates) <= as_of:
            candidates.append((parsed_version, version))

    if not candidates:
        raise RuntimeError(f"No pytest-playwright release found by {as_of}")

    return max(candidates)[1]


def update_file(path: Path, version: str) -> bool:
    """Update a pytest-playwright minimum in a text file."""

    contents = path.read_text(encoding="utf-8")
    updated = DEPENDENCY_PATTERN.sub(f"pytest-playwright>={version}", contents)
    updated = README_DEPENDENCY_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{version}", updated
    )
    if updated == contents:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    compatibility_date = twelve_months_ago(datetime.now(timezone.utc).date())
    version = supported_version(compatibility_date)
    paths = (
        ROOT / "pyproject.toml",
        ROOT / "README.md",
    )
    changed_paths = [path for path in paths if update_file(path, version)]
    print(
        f"pytest-playwright minimum for {compatibility_date}: >={version}"
    )
    print(
        "Updated: "
        + ", ".join(str(path.relative_to(ROOT)) for path in changed_paths)
    )


if __name__ == "__main__":
    main()