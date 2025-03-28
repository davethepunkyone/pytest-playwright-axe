import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import requests
import logging
from src.pytest_playwright_axe import __version__ as package_version


def axe_core_update_required() -> bool:
    """Check the axe-core version in the repository."""
    url = "https://api.github.com/repos/dequelabs/axe-core/releases/latest"
    response = requests.get(url)
    if response.status_code == 200:
        latest_version = response.json()["tag_name"]
        logging.info(f"Latest axe-core version: {latest_version}")
    else:
        logging.error("Failed to fetch the latest axe-core version from GitHub.")
    
    current_version = f"v{package_version}" if "-" not in package_version else f"v{package_version.split('-')[0]}"
    logging.info(f"Current axe-core version: {current_version}")
    
    return current_version != latest_version


if __name__ == "__main__":
    print(axe_core_update_required())
