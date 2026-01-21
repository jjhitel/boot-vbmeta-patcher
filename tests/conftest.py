import math
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Optional
from unittest.mock import patch

import py7zr
import pytest
import requests
from ltbox import downloader, i18n

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../bin")))

QFIL_URL = "http://zsk-cdn.lenovows.com/%E7%9F%A5%E8%AF%86%E5%BA%93/Flash_tool_image/TB322_ZUXOS_1.5.10.063_Tool.7z"
QFIL_PW = os.environ.get("TEST_QFIL_PASSWORD")

CACHE_DIR = Path(__file__).parent / "data"
ARCHIVE = CACHE_DIR / "qfil_archive.7z"
EXTRACT_DIR = CACHE_DIR / "extracted"
URL_RECORD_FILE = CACHE_DIR / "url.txt"
PART_SUFFIX = ".part"
DEFAULT_SEGMENTS = 4
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def _download_stream(
    url: str,
    dest_path: Path,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    on_progress: Optional[Callable[[int], None]] = None,
) -> None:
    with requests.get(url, stream=True, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    if on_progress:
                        on_progress(len(chunk))


def _download_range(
    url: str,
    start: int,
    end: int,
    dest_path: Path,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    on_progress: Optional[Callable[[int], None]] = None,
) -> None:
    range_headers = {"Range": f"bytes={start}-{end}"}
    if headers:
        range_headers.update(headers)

    with requests.get(
        url, stream=True, headers=range_headers, timeout=timeout
    ) as response:
        response.raise_for_status()
        if response.status_code not in (200, 206):
            raise RuntimeError(f"Unexpected status code: {response.status_code}")
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    if on_progress:
                        on_progress(len(chunk))


def _render_progress(downloaded: int, total_size: int, start_time: float) -> str:
    elapsed = max(time.monotonic() - start_time, 1e-6)
    speed = downloaded / elapsed
    eta_seconds = (total_size - downloaded) / speed if speed > 0 else 0
    percent = (downloaded / total_size) * 100 if total_size else 0
    return (
        f"\rDownloading... {percent:6.2f}% "
        f"({downloaded / (1024**2):.2f} MB / {total_size / (1024**2):.2f} MB) "
        f"Speed: {speed / (1024**2):.2f} MB/s "
        f"ETA: {eta_seconds:,.0f}s"
    )


def download_with_ranges(
    url: str,
    dest_path: Path,
    segments: int = DEFAULT_SEGMENTS,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> None:
    head = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
    head.raise_for_status()
    total_size = int(head.headers.get("Content-Length", "0"))
    accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
    downloaded = 0
    download_lock = threading.Lock()
    start_time = time.monotonic()
    stop_event = threading.Event()

    def report_progress() -> None:
        last_output = ""
        while not stop_event.is_set():
            with download_lock:
                current = downloaded
            if total_size:
                output = _render_progress(current, total_size, start_time)
                if output != last_output:
                    print(output, end="", flush=True)
                    last_output = output
            time.sleep(0.5)

    def on_progress(bytes_count: int) -> None:
        nonlocal downloaded
        with download_lock:
            downloaded += bytes_count

    if total_size <= 0 or not accept_ranges or segments <= 1:
        reporter = threading.Thread(target=report_progress, daemon=True)
        reporter.start()
        try:
            _download_stream(
                url,
                dest_path,
                headers=headers,
                timeout=timeout,
                on_progress=on_progress,
            )
        finally:
            stop_event.set()
            reporter.join()
            if total_size:
                print(_render_progress(downloaded, total_size, start_time), flush=True)
        return

    part_paths = []
    part_size = math.ceil(total_size / segments)

    try:
        reporter = threading.Thread(target=report_progress, daemon=True)
        reporter.start()
        with ThreadPoolExecutor(max_workers=segments) as executor:
            futures = []
            for idx in range(segments):
                start = idx * part_size
                end = min(start + part_size - 1, total_size - 1)
                part_path = dest_path.with_suffix(
                    f"{dest_path.suffix}{PART_SUFFIX}{idx}"
                )
                part_paths.append(part_path)
                futures.append(
                    executor.submit(
                        _download_range,
                        url,
                        start,
                        end,
                        part_path,
                        headers,
                        timeout,
                        on_progress,
                    )
                )

            for future in as_completed(futures):
                future.result()

        with open(dest_path, "wb") as output:
            for part_path in part_paths:
                with open(part_path, "rb") as part:
                    shutil.copyfileobj(part, output)

    except Exception:
        if dest_path.exists():
            dest_path.unlink()
        raise
    finally:
        stop_event.set()
        reporter.join()
        if total_size:
            print(_render_progress(downloaded, total_size, start_time), flush=True)
        for part_path in part_paths:
            if part_path.exists():
                part_path.unlink()


@pytest.fixture(scope="session", autouse=True)
def setup_language():
    i18n.load_lang("en")


@pytest.fixture(scope="session", autouse=True)
def setup_external_tools():
    print("\n[INFO] Setting up external tools for integration tests...", flush=True)
    try:
        downloader.ensure_avb_tools()
    except Exception as e:
        print(f"\n[WARN] Failed to setup tools: {e}", flush=True)


@pytest.fixture(autouse=True)
def mock_python_executable():
    with patch("ltbox.constants.PYTHON_EXE", sys.executable):
        yield


@pytest.fixture(scope="module")
def fw_pkg(tmp_path_factory):
    if not QFIL_PW:
        pytest.skip("TEST_QFIL_PASSWORD not set")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cached_url = ""
    if URL_RECORD_FILE.exists():
        try:
            cached_url = URL_RECORD_FILE.read_text("utf-8").strip()
        except Exception:
            pass

    if cached_url != QFIL_URL:
        print("\n[INFO] URL Changed or Cache missing. Cleaning up...", flush=True)
        if CACHE_DIR.exists():
            if ARCHIVE.exists():
                ARCHIVE.unlink()
            if EXTRACT_DIR.exists():
                shutil.rmtree(EXTRACT_DIR)
            if URL_RECORD_FILE.exists():
                URL_RECORD_FILE.unlink()

        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not ARCHIVE.exists() or ARCHIVE.stat().st_size == 0:
        print("\n[INFO] Starting download...", flush=True)
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }

            download_with_ranges(
                QFIL_URL,
                ARCHIVE,
                segments=DEFAULT_SEGMENTS,
                headers=headers,
            )
            print(
                f"\n[INFO] Download Complete! Size: {ARCHIVE.stat().st_size / (1024**3):.2f} GB",
                flush=True,
            )

            URL_RECORD_FILE.write_text(QFIL_URL, encoding="utf-8")

        except Exception as e:
            if ARCHIVE.exists():
                ARCHIVE.unlink()
            pytest.fail(f"Download failed: {e}")

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        "vbmeta.img",
        "boot.img",
        "vendor_boot.img",
        "rawprogram_unsparse0.xml",
        "rawprogram_save_persist_unsparse0.xml",
    ]

    cached_map = {}
    missing_targets = False
    for t in targets:
        found = list(EXTRACT_DIR.rglob(t))
        if found:
            cached_map[t] = found[0]
        else:
            missing_targets = True
            break

    if not missing_targets and cached_url == QFIL_URL:
        print("\n[INFO] Using cached extracted files.", flush=True)
        return cached_map

    print("\n[INFO] Extracting archive...", flush=True)
    try:
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR)
        EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

        with py7zr.SevenZipFile(ARCHIVE, mode="r", password=QFIL_PW) as z:
            all_f = z.getnames()
            to_ext = [
                f
                for f in all_f
                if os.path.basename(f.replace("\\", "/")) in targets
                and "/image/" in f.replace("\\", "/")
            ]

            if not to_ext:
                pytest.fail("Targets not found in archive")
            z.extract(path=EXTRACT_DIR, targets=to_ext)

            mapped = {}
            for t in targets:
                for p in EXTRACT_DIR.rglob(t):
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
        "EDL_LOADER_FILE": tmp_path / "loader.elf",
    }
    for d in dirs.values():
        if d.suffix:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.touch()
        else:
            d.mkdir(parents=True, exist_ok=True)

    with patch.multiple("ltbox.constants", **dirs):
        yield dirs
