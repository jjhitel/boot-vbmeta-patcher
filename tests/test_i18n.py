import sys
import os
import re
import json
import pytest
from pathlib import Path

BASE = Path(__file__).parent.parent
SRC = BASE / "bin" / "ltbox"
LANG = SRC / "lang"

def get_src_keys():
    keys = set()
    pat = re.compile(r'get_string\s*\(\s*["\']([^"\']+)["\']\s*\)')
    for f in SRC.rglob("*.py"):
        try:
            keys.update(pat.findall(f.read_text(encoding="utf-8")))
        except Exception: pass
    return keys

def load_langs():
    d = {}
    if not LANG.exists(): return {}
    for f in LANG.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d[f.name] = set(json.load(fp).keys())
        except Exception: pytest.fail(f"Bad JSON {f.name}")
    return d

class TestI18n:
    @pytest.fixture(scope="class")
    def src_keys(self): return get_src_keys()

    @pytest.fixture(scope="class")
    def lang_map(self): return load_langs()

    def test_missing_keys(self, src_keys, lang_map):
        if not lang_map: pytest.skip("No lang files")
        for n, k in lang_map.items():
            missing = src_keys - k
            assert not missing, f"Missing in {n}: {missing}"

    def test_parity(self, lang_map):
        if not lang_map: pytest.skip("No lang files")
        base = "en.json" if "en.json" in lang_map else list(lang_map.keys())[0]
        base_k = lang_map[base]

        for n, k in lang_map.items():
            if n == base: continue
            diff = base_k - k
            assert not diff, f"{n} missing keys from {base}: {diff}"
