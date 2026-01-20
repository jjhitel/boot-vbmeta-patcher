import json
import sys
from pathlib import Path
from typing import List, Tuple

APP_DIR = Path(__file__).parent.resolve()
LANG_DIR = APP_DIR / "lang"

_lang_data = {}
_fallback_data = {}


def get_available_languages() -> List[Tuple[str, str]]:
    if not LANG_DIR.is_dir():
        raise RuntimeError(f"Language directory not found: {LANG_DIR}")

    lang_files = sorted(list(LANG_DIR.glob("*.json")))
    if not lang_files:
        raise RuntimeError(f"No language files (*.json) found in: {LANG_DIR}")

    languages = []
    for f in lang_files:
        lang_code = f.stem
        try:
            with open(f, "r", encoding="utf-8") as lang_file:
                temp_lang = json.load(lang_file)
                lang_name = temp_lang.get("lang_native_name", lang_code)
                languages.append((lang_code, lang_name))
        except Exception:
            languages.append((lang_code, lang_code))
    return languages


def load_lang(lang_code: str = "en"):
    global _lang_data, _fallback_data

    fallback_file = LANG_DIR / "en.json"
    if not _fallback_data and fallback_file.exists():
        try:
            with open(fallback_file, "r", encoding="utf-8") as f:
                _fallback_data = json.load(f)
        except Exception as e:
            print(f"[!] Failed to load fallback language en.json: {e}", file=sys.stderr)
            _fallback_data = {}

    if lang_code == "en" or not (LANG_DIR / f"{lang_code}.json").exists():
        _lang_data = _fallback_data
    else:
        lang_file = LANG_DIR / f"{lang_code}.json"
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                _lang_data = json.load(f)
        except Exception as e:
            print(
                f"[!] Failed to load language {lang_code}, using fallback: {e}",
                file=sys.stderr,
            )
            _lang_data = _fallback_data


def get_string(key: str, default: str = "") -> str:
    val = _lang_data.get(key, _fallback_data.get(key, default))
    if val:
        return val

    missing_key_format = _fallback_data.get("err_missing_key", "[{key}]")
    try:
        return missing_key_format.format(key=key)
    except KeyError:
        return f"[{key}]"
