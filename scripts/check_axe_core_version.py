from pathlib import Path
import os
import requests
import logging
import tomllib


TOML_PATH = Path(os.getcwd()) / "pyproject.toml"


def axe_core_update_required() -> bool:
    """Check the axe-core version in the repository."""

    # Check axe-core version
    url = "https://api.github.com/repos/dequelabs/axe-core/releases/latest"
    response = requests.get(url)
    if response.status_code == 200:
        latest_version = str(response.json()["tag_name"])
        logging.info(f"Latest axe-core version: {latest_version}")
    else:
        logging.error("Failed to fetch the latest axe-core version from GitHub.")

    with open(TOML_PATH, "rb") as f:
        toml_data = tomllib.load(f)
    
    toml_version = toml_data["project"]["version"]
    
    current_version = str(f"v{toml_version}" if "-" not in toml_version else f"v{toml_version.split('-')[0]}")
    logging.info(f"Current axe-core version: {current_version}")
    
    result = current_version != latest_version
    logging.info(f"Update required: {result}")

    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as gho:
            gho.write(f"update_required={current_version != latest_version}\n")
            gho.write(f"axe_core_version={latest_version.replace('v', '')}\n")
            gho.write(f"package_version={current_version.replace('v', '')}")

    return result


if __name__ == "__main__":
    print(axe_core_update_required())
