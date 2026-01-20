import json
import os
from pathlib import Path
import pytest

BASE_DIR = Path(__file__).parent.parent / "bin/ltbox"

def get_json_files():
    return list(BASE_DIR.rglob("*.json"))

@pytest.mark.parametrize("json_file", get_json_files())
def test_json_syntax(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, (dict, list))

def test_config_required_keys():
    config_path = BASE_DIR / "config.json"
    if not config_path.exists():
        pytest.skip("config.json not found")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    required_keys = ["version", "magiskboot", "kernelsu-next"]
    for key in required_keys:
        assert key in config, f"Missing required key '{key}' in config.json"
