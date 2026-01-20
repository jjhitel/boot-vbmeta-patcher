import os
import sys
import shutil
import pytest
import requests
import py7zr
import time
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin')))

QFIL_URL = "http://zsk-cdn.lenovows.com/%E7%9F%A5%E8%AF%86%E5%BA%93/Flash_tool_image/TB322_ZUXOS_1.5.10.063_Tool.7z"
QFIL_PW = os.environ.get("TEST_QFIL_PASSWORD")
CACHE_DIR = Path(__file__).parent / "data"
ARCHIVE = CACHE_DIR / "qfil_archive.7z"

@pytest.fixture(autouse=True)
def mock_python_executable():
    with patch("ltbox.constants.PYTHON_EXE", sys.executable):
        yield

@pytest.fixture(scope="module")
def fw_pkg(tmp_path_factory):
    if not QFIL_PW:
        pytest.skip("TEST_QFIL_PASSWORD not set")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not ARCHIVE.exists() or ARCHIVE.stat().st_size == 0:
        print(f"\n[INFO] Starting download...", flush=True)
        try:
            with requests.get(QFIL_URL, stream=True) as r:
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                print(f"[INFO] Size: {total / (1024**3):.2f} GB", flush=True)

                with open(ARCHIVE, 'wb') as f:
                    down = 0
                    last_print = 0
                    start = time.time()
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            down += len(chunk)
                            if down - last_print > 100 * 1024 * 1024:
                                elap = time.time() - start
                                speed = (down / (1024**2)) / elap if elap > 0 else 0
                                per = (down / total) * 100 if total else 0
                                print(f"[DOWN] {per:.1f}% - {speed:.1f} MB/s", flush=True)
                                last_print = down

        except Exception as e:
            if ARCHIVE.exists(): ARCHIVE.unlink()
            pytest.fail(f"Download failed: {e}")

    extract_dir = tmp_path_factory.mktemp("pkg")
    targets = ["vbmeta.img", "boot.img", "vendor_boot.img",
               "rawprogram_unsparse0.xml", "rawprogram_save_persist_unsparse0.xml"]

    try:
        print("[INFO] Extracting...", flush=True)
        with py7zr.SevenZipFile(ARCHIVE, mode='r', password=QFIL_PW) as z:
            all_f = z.getnames()
            to_ext = [f for f in all_f if os.path.basename(f.replace("\\", "/")) in targets and "/image/" in f.replace("\\", "/")]

            if not to_ext: pytest.fail("Targets not found")
            z.extract(path=extract_dir, targets=to_ext)

            mapped = {}
            for t in targets:
                for p in extract_dir.rglob(t):
                    mapped[t] = p
                    break
            return mapped
    except Exception as e:
        pytest.fail(f"Extraction failed: {e}")

@pytest.fixture
def mock_env(tmp_path):
    dirs = {
        "IMAGE_DIR": tmp_path / "image",
        "OUTPUT_DP_DIR": tmp_path / "output_dp",
        "OUTPUT_DIR": tmp_path / "output",
        "OUTPUT_ANTI_ROLLBACK_DIR": tmp_path / "output_arb",
        "OUTPUT_XML_DIR": tmp_path / "output_xml",
        "EDL_LOADER_FILE": tmp_path / "loader.elf"
    }
    for d in dirs.values():
        if d.suffix:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.touch()
        else:
            d.mkdir(parents=True, exist_ok=True)

    with patch.multiple("ltbox.constants", **dirs):
        yield dirs
