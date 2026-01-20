import sys
import os
import json
import pytest
from pathlib import Path
from ltbox import main

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

class TestApp:
    def test_imports(self):
        assert hasattr(main, "CommandRegistry")
        assert hasattr(main, "setup_console")

    def test_registry(self):
        reg = main.CommandRegistry()
        def dummy(): return "ok"
        reg.add("cmd", dummy, "Title", require_dev=False)
        c = reg.get("cmd")
        assert c["title"] == "Title"
        assert c["func"]() == "ok"

    def test_json_validity(self):
        d = Path(__file__).parent.parent / "bin/ltbox"
        files = list(d.rglob("*.json"))
        if not files: pytest.skip("No JSON")

        for f in files:
            with open(f, "r", encoding="utf-8") as fp:
                json.load(fp)

    def test_config_keys(self):
        p = Path(__file__).parent.parent / "bin/ltbox/config.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                c = json.load(f)
            assert "version" in c
