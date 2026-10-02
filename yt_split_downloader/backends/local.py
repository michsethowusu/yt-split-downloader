"""Local backend: resolve and download on the same machine.

Useful when the box running the resolver has both a trusted IP *and* enough
disk/bandwidth -- or simply to test the tool. The worker runs in a background
thread inside the resolver process.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..layout import Layout
from .base import Backend


class LocalBackend(Backend):
    name = "local"
    stream = True

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        target = cfg.backend.local_dir or cfg.general.project_dir
        self.layout = Layout(Path(target)).ensure()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def prepare(self) -> None:
        from ..download_core import require_tools

        require_tools("aria2c", "ffprobe")

    def remote_done(self) -> set[str]:
        ids = self.layout.read_archive()
        if self.layout.videos.exists():
            ids |= {p.stem for p in self.layout.videos.glob("*.mp4")}
        return ids

    def remote_has_video(self, video_id: str) -> bool:
        return (self.layout.videos / f"{video_id}.mp4").exists()

    def queue_depth(self) -> int:
        return len(list(self.layout.queue.glob("*.url")))

    def sync_queue(self, local_queue: Path) -> None:
        # The resolver writes straight into this layout's queue already.
        return

    def ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        from ..download_core import Worker

        worker = Worker(
            queue_dir=self.layout.queue,
            videos_dir=self.layout.videos,
            archive_path=self.layout.archive,
            failed_dir=self.layout.failed,
            workers=self.cfg.download.workers,
            connections=self.cfg.download.connections,
            user_agent=self.cfg.download.user_agent,
            timeout=self.cfg.download.timeout,
            validate=self.cfg.download.validate,
            min_bytes=self.cfg.download.min_bytes,
        )
        self._thread = threading.Thread(
            target=worker.run,
            kwargs={"poll": self.cfg.general.poll_interval},
            daemon=True,
        )
        self._thread.start()

    def pull_results(self, layout) -> None:
        return

    def close(self) -> None:
        self._stop.set()
