import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    if not config_path.exists():
        example = config_path.parent / "config.json.example"
        raise FileNotFoundError(
            f"Config file not found at {config_path}.\n"
            f"Copy {example} to {config_path} and fill in your account details."
        )
    with open(config_path) as f:
        return json.load(f)


def get_accounts(config: Dict[str, Any]) -> Dict[str, Dict]:
    return config.get("accounts", {})


def get_credentials_dir(config: Dict[str, Any], base_dir: Path = DEFAULT_CONFIG_PATH.parent) -> Path:
    path = Path(config.get("credentials_dir", "./credentials"))
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def get_client_secret_path(config: Dict[str, Any]) -> Path:
    return get_credentials_dir(config) / "client_secret.json"
