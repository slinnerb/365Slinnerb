"""Auto-update via GitHub Releases.

To enable auto-updates:
  1. Create a GitHub account (free) and a public repo to host releases.
  2. Edit the two constants below: GITHUB_OWNER and GITHUB_REPO.
  3. Bump VERSION whenever you ship a new build.
  4. See RELEASING.md for the per-release workflow.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import requests

# ============================================================
#  CONFIGURE THESE for your GitHub Releases
# ============================================================
GITHUB_OWNER = "slinnerb"
GITHUB_REPO = "365Slinnerb"
ASSET_PATTERN = re.compile(r"^MLB-Stats-Viewer.*\.exe$", re.IGNORECASE)

# Bump this every release. Tag your GitHub release as "v" + this string,
# e.g. VERSION = "1.0.1"  →  git tag v1.0.1
VERSION = "1.0.4"
# ============================================================


def is_frozen() -> bool:
    """True when running as a packaged PyInstaller .exe (not from source)."""
    return getattr(sys, "frozen", False)


def running_exe_path() -> Path | None:
    """Absolute path to the currently running .exe — or None when in dev mode."""
    if is_frozen():
        return Path(sys.executable).resolve()
    return None


def parse_version(s: str) -> tuple[int, ...]:
    """Strip leading 'v' and parse into a comparable tuple of ints."""
    s = (s or "").lstrip("vV").strip()
    parts = re.split(r"[.\-+]", s)
    nums: list[int] = []
    for p in parts:
        m = re.match(r"(\d+)", p)
        if not m:
            break
        nums.append(int(m.group(1)))
    return tuple(nums) if nums else (0,)


def check_for_update(timeout: int = 10) -> dict[str, Any]:
    """Query the GitHub Releases API and compare against the local VERSION.

    Returns a dict with:
        status:        'update_available' | 'no_update' | 'error' | 'not_configured'
        current:       current VERSION
        latest:        latest release tag (if found)
        download_url:  asset .exe URL (if found)
        notes:         release body text (if any)
        message:       human-readable detail (always present)
    """
    if GITHUB_OWNER.startswith("YOUR_"):
        return {
            "status": "not_configured",
            "current": VERSION,
            "message": (
                "Update server not configured. Open updater.py and set "
                "GITHUB_OWNER and GITHUB_REPO to your GitHub repository, then "
                "rebuild and publish a release. See RELEASING.md for steps."
            ),
        }

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    try:
        r = requests.get(
            url, timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code == 404:
            return {
                "status": "no_update", "current": VERSION,
                "message": "No releases published in the GitHub repo yet.",
            }
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {
            "status": "error", "current": VERSION,
            "message": f"Couldn't reach update server: {e}",
        }

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return {
            "status": "error", "current": VERSION,
            "message": "Latest release is missing a tag.",
        }

    download_url = None
    for asset in data.get("assets", []):
        if ASSET_PATTERN.match(asset.get("name", "")):
            download_url = asset.get("browser_download_url")
            break

    latest_t = parse_version(tag)
    current_t = parse_version(VERSION)

    if latest_t <= current_t:
        return {
            "status": "no_update", "current": VERSION, "latest": tag,
            "message": f"You're on the latest version (v{VERSION}).",
        }

    if not download_url:
        return {
            "status": "error", "current": VERSION, "latest": tag,
            "message": (
                f"Release {tag} exists, but no .exe matching the expected "
                "name was attached to it."
            ),
        }

    return {
        "status": "update_available",
        "current": VERSION,
        "latest": tag,
        "download_url": download_url,
        "notes": (data.get("body") or "").strip(),
        "message": f"Update available: v{VERSION} → {tag}",
    }


def download_update(
    url: str,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    timeout: int = 60,
) -> None:
    """Download an .exe asset to `dest`. Reports progress(bytes_done, total)."""
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)


_UPDATER_BAT = r"""@echo off
setlocal
REM Give the parent app a moment to exit.
ping 127.0.0.1 -n 2 >nul

set TARGET={target}
set NEW={new}
set TRIES=0

:try
del /f /q "%TARGET%" >nul 2>&1
if exist "%TARGET%" (
  set /a TRIES+=1
  if %TRIES% lss 25 (
    ping 127.0.0.1 -n 2 >nul
    goto try
  )
  echo Could not replace the running file. The new version was saved at:
  echo   %NEW%
  pause
  goto launch_new
)
move /y "%NEW%" "%TARGET%" >nul 2>&1
if exist "%TARGET%" (
  start "" "%TARGET%"
  goto cleanup
)

:launch_new
start "" "%NEW%"

:cleanup
(goto) 2>nul & del "%~f0"
"""


def install_and_restart(new_exe: Path) -> None:
    """Replace the running .exe with `new_exe`, restart, and exit this process.

    Only meaningful when running as a packaged .exe. The actual swap is done by
    a small batch script that runs detached, waits for this process to exit,
    swaps the files, launches the new one, then deletes itself.
    """
    target = running_exe_path()
    if target is None:
        raise RuntimeError(
            "install_and_restart only works in the packaged .exe build."
        )

    new = new_exe.resolve()
    bat_path = target.parent / "_update.bat"
    bat_path.write_text(
        _UPDATER_BAT.format(target=str(target), new=str(new)),
        encoding="ascii",
    )

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    sys.exit(0)
