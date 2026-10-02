"""Core download logic.

Deliberately standard-library only so this file can be copied verbatim onto a
bare download host (the SSH backend does exactly that). Everything shells out
to ``aria2c`` and ``ffprobe``.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ID_RE = re.compile(r"^([A-Za-z0-9_-]{11})")


def video_id_from_name(name: str) -> str:
    """Best-effort extraction of a YouTube id from a filename stem."""
    m = _ID_RE.match(Path(name).name)
    return m.group(1) if m else Path(name).stem


def require_tools(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        raise RuntimeError(f"required executable(s) not found on PATH: {', '.join(missing)}")


def _ffprobe_ok(path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def download_one(
    url: str,
    video_id: str,
    videos_dir: Path,
    connections: int = 16,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 3600,
    validate: bool = True,
    min_bytes: int = 65536,
) -> tuple[bool, str]:
    """Download *url* to ``videos_dir/<video_id>.mp4`` with aria2c.

    Returns ``(ok, detail)``. The temporary file is named ``.<id>.part.mp4`` so
    that any directory watcher ignores it while it is being written. This is
    the exact function reused by the CLI worker and by the Modal app.
    """
    videos_dir = Path(videos_dir)
    videos_dir.mkdir(parents=True, exist_ok=True)
    final = videos_dir / f"{video_id}.mp4"
    tmp = videos_dir / f".{video_id}.part.mp4"

    if final.exists() and final.stat().st_size >= min_bytes:
        return True, "exists"

    tmp.unlink(missing_ok=True)
    cmd = [
        "aria2c",
        "--dir",
        str(videos_dir),
        "-o",
        tmp.name,
        "-x",
        str(connections),
        "-s",
        str(connections),
        "-k",
        "1M",
        "--file-allocation=none",
        "--summary-interval=0",
        "--max-tries=5",
        "--retry-wait=5",
        "--allow-overwrite=true",
        "--header",
        f"User-Agent: {user_agent}",
        url,
    ]
    result = None
    with contextlib.suppress(subprocess.TimeoutExpired):
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    size = tmp.stat().st_size if tmp.exists() else 0
    ok = result is not None and result.returncode == 0 and size >= min_bytes
    detail = ""
    if ok and validate and not _ffprobe_ok(tmp):
        ok = False
        detail = "ffprobe rejected the file (not valid media)"
    if ok:
        os.replace(tmp, final)
        return True, f"{final.stat().st_size / 1e6:.1f} MB"
    tmp.unlink(missing_ok=True)
    if not detail:
        if result is None:
            detail = "download timed out"
        elif result.returncode != 0:
            blob = (result.stderr or b"") + (result.stdout or b"")
            detail = (
                blob.decode("utf-8", "replace").strip()[-300:]
                or f"aria2c exited {result.returncode}"
            )
        elif size < min_bytes:
            detail = f"file too small ({size} < {min_bytes} bytes)"
        else:
            detail = "aria2c failed"
    return False, detail


class Worker:
    """Watch a queue directory and download every ``*.url`` file in it."""

    def __init__(
        self,
        queue_dir: Path,
        videos_dir: Path,
        archive_path: Path,
        failed_dir: Path,
        workers: int = 5,
        connections: int = 16,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 3600,
        validate: bool = True,
        min_bytes: int = 65536,
    ) -> None:
        self.queue_dir = Path(queue_dir)
        self.videos_dir = Path(videos_dir)
        self.archive_path = Path(archive_path)
        self.failed_dir = Path(failed_dir)
        for d in (self.queue_dir, self.videos_dir, self.failed_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.workers = workers
        self.connections = connections
        self.user_agent = user_agent
        self.timeout = timeout
        self.validate = validate
        self.min_bytes = min_bytes

        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers)

    # -- helpers -----------------------------------------------------------
    def _archive_ids(self) -> set[str]:
        ids: set[str] = set()
        if self.archive_path.exists():
            for line in self.archive_path.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    ids.add(parts[-1])
        return ids

    def _finish(self, video_id: str, url_file: Path) -> None:
        url_file.unlink(missing_ok=True)
        self._inflight.discard(video_id)

    def _job(self, video_id: str, url: str, url_file: Path) -> None:
        ok, detail = download_one(
            url,
            video_id,
            self.videos_dir,
            connections=self.connections,
            user_agent=self.user_agent,
            timeout=self.timeout,
            validate=self.validate,
            min_bytes=self.min_bytes,
        )
        stamp = time.strftime("%F %T")
        if ok:
            with self._lock, open(self.archive_path, "a") as fh:
                fh.write(f"youtube {video_id}\n")
            self._finish(video_id, url_file)
            print(f"[{stamp}] OK   {video_id} ({detail})", flush=True)
        else:
            self._finish(video_id, url_file)
            print(f"[{stamp}] FAIL {video_id}: {detail}", flush=True)

    # -- public ------------------------------------------------------------
    def process_once(self) -> int:
        """Submit every ready URL. Returns the number submitted."""
        done = self._archive_ids()
        submitted = 0
        for url_file in sorted(self.queue_dir.glob("*.url")):
            video_id = url_file.stem
            if video_id in self._inflight:
                continue
            if video_id in done or (self.videos_dir / f"{video_id}.mp4").exists():
                url_file.unlink(missing_ok=True)
                continue
            if len(self._inflight) >= self.workers:
                break
            url = url_file.read_text().strip()
            if not url:
                url_file.unlink(missing_ok=True)
                continue
            self._inflight.add(video_id)
            self._pool.submit(self._job, video_id, url, url_file)
            submitted += 1
        return submitted

    def run(self, poll: int = 20, once: bool = False) -> None:
        print(
            f"Worker watching {self.queue_dir} "
            f"(workers={self.workers}, conn={self.connections}, poll={poll}s)",
            flush=True,
        )
        while True:
            submitted = self.process_once()
            if once and submitted == 0 and not self._inflight:
                break
            time.sleep(2 if submitted else poll)
        self._pool.shutdown(wait=True)
