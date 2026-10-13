import logging
import os
import tomllib
from pathlib import Path

import requests

TOML_PATH = Path(os.getcwd()) / "pyproject.toml"

logger = logging.getLogger(__name__)


def axe_core_update_required() -> bool:
    """Check the axe-core version in the repository."""

    # Check axe-core version
    url = "https://api.github.com/repos/dequelabs/axe-core/releases/latest"
    response = requests.get(url)
    if response.status_code == 200:
        latest_version = str(response.json()["tag_name"])
        logger.info(f"Latest axe-core version: {latest_version}")
    else:
        raise RuntimeError(
            f"Failed to fetch the latest axe-core version from GitHub (HTTP {response.status_code}).")

    with open(TOML_PATH, "rb") as f:
        toml_data = tomllib.load(f)

    toml_version = toml_data["project"]["version"]

    current_version = str(
        f"v{toml_version}" if ".post" not in toml_version else f"v{toml_version.split('.post')[0]}")
    logger.info(f"Current axe-core version: {current_version}")

    result = current_version != latest_version
    logger.info(f"Update required: {result}")

    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as gho:
            gho.write(f"update_required={current_version != latest_version}\n")
            gho.write(f"axe_core_version={latest_version.replace('v', '')}\n")
            gho.write(f"package_version={toml_version}\n")

    return result


if __name__ == "__main__":
    print(axe_core_update_required())
