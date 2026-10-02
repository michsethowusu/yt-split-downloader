"""Resolver: the half that must run on a trusted (non-datacenter) IP.

YouTube serves the *web/API* endpoints behind an IP-reputation gate, so a VPS
or a Modal container often cannot list formats or start an extractor. But a
normal desktop connection can. This module turns video ids into direct media
URLs with ``yt-dlp -g`` and drops them in the queue for a worker elsewhere.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from .config import Config
from .layout import Layout

ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")
BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

RETRY_AFTER = 6 * 3600  # direct URLs expire in ~6h; retry resolves after that


# ---------------------------------------------------------------------------
# input parsing
# ---------------------------------------------------------------------------
def extract_id(line: str) -> Optional[str]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if BARE_ID_RE.match(line):
        return line
    m = ID_RE.search(line)
    return m.group(1) if m else None


def read_ids(urls_file: Path) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    if not Path(urls_file).exists():
        return ids
    for line in Path(urls_file).read_text(errors="replace").splitlines():
        vid = extract_id(line)
        if vid and vid not in seen:
            seen.add(vid)
            ids.append(vid)
    return ids


class AttemptStore:
    """Remember when each id was last attempted so failures are retried later."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.data: dict[str, float] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (ValueError, OSError):
                self.data = {}

    def due(self, video_id: str) -> bool:
        ts = self.data.get(video_id)
        return ts is None or (time.time() - ts) > RETRY_AFTER

    def mark(self, video_id: str) -> None:
        self.data[video_id] = time.time()

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        tmp.replace(self.path)


# ---------------------------------------------------------------------------
# the actual resolution
# ---------------------------------------------------------------------------
def resolve_video(
    video_id: str,
    fmt: str = "bv*[protocol=https]",
    cookies: Optional[str] = None,
    yt_dlp: str = "yt-dlp",
    timeout: int = 120,
) -> tuple[Optional[str], str]:
    """Return ``(url, detail)`` for a single video.

    ``-g`` prints the direct URL(s) instead of downloading. We keep the first
    ``http`` line (video-only selection, so there is normally exactly one).
    """
    cmd = [yt_dlp, "-f", fmt, "-g", "--no-warnings", "--no-playlist"]
    if cookies:
        cmd += ["--cookies", str(cookies)]
    cmd.append(f"https://www.youtube.com/watch?v={video_id}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None, f"{yt_dlp!r} not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "yt-dlp timed out"

    if result.returncode != 0:
        return None, (result.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line, "ok"
    return None, "no URL returned"


def _log(message: str) -> None:
    print(f"[{time.strftime('%F %T')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# streaming resolver (local / ssh backends)
# ---------------------------------------------------------------------------
def run_stream(cfg: Config, backend, once: bool = False) -> None:
    layout = Layout(cfg.project_dir).ensure()
    attempts = AttemptStore(layout.root / "attempts.json")
    ids = read_ids(cfg.urls_file)
    if not ids:
        _log(f"no video ids found in {cfg.urls_file}")
        return
    _log(f"resolver started: {len(ids)} ids, backend={backend.name}, format={cfg.general.format}")

    while True:
        resolved = 0
        try:
            done = layout.read_archive() | backend.remote_done()
            depth = backend.queue_depth()
            if depth >= cfg.general.hwm:
                _log(f"queue depth {depth} >= high-water mark {cfg.general.hwm}; pausing")
            else:
                for video_id in ids:
                    if resolved >= cfg.general.batch or backend.queue_depth() >= cfg.general.hwm:
                        break
                    if video_id in done:
                        continue
                    if not attempts.due(video_id):
                        continue
                    url, detail = resolve_video(
                        video_id,
                        cfg.general.format,
                        cookies=cfg.general.cookies,
                        yt_dlp=cfg.general.yt_dlp,
                    )
                    attempts.mark(video_id)
                    if url:
                        (layout.queue / f"{video_id}.url").write_text(url)
                        _log(f"resolved {video_id}")
                    else:
                        _log(f"no URL for {video_id}: {detail}")
                    resolved += 1
                    attempts.save()
                    time.sleep(cfg.general.resolve_delay)
        finally:
            if resolved:
                backend.sync_queue(layout.queue)
            backend.ensure_worker()
            backend.pull_results(layout)

        if once:
            break
        time.sleep(cfg.general.poll_interval)

    backend.close()


# ---------------------------------------------------------------------------
# batch resolver (modal backend)
# ---------------------------------------------------------------------------
def run_batch(cfg: Config, backend, once: bool = True, fetch: bool = False) -> None:
    layout = Layout(cfg.project_dir).ensure()
    attempts = AttemptStore(layout.root / "attempts.json")
    ids = read_ids(cfg.urls_file)
    if not ids:
        _log(f"no video ids found in {cfg.urls_file}")
        return
    _log(f"batch resolver: {len(ids)} ids, backend={backend.name}")

    done = layout.read_archive() | backend.remote_done()
    todo = [i for i in ids if i not in done and attempts.due(i)]

    batch_urls: dict[str, str] = {}
    for video_id in todo:
        url, detail = resolve_video(
            video_id,
            cfg.general.format,
            cookies=cfg.general.cookies,
            yt_dlp=cfg.general.yt_dlp,
        )
        attempts.mark(video_id)
        if url:
            batch_urls[video_id] = url
            _log(f"resolved {video_id}")
        else:
            _log(f"no URL for {video_id}: {detail}")
        if len(batch_urls) >= cfg.general.batch:
            break
        time.sleep(cfg.general.resolve_delay)
    attempts.save()

    if batch_urls:
        backend.dispatch(batch_urls)
    else:
        _log("nothing to dispatch")

    if fetch:
        backend.fetch_all(layout)
    backend.close()
