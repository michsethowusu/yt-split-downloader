"""Filesystem layout shared by the resolver and the worker.

Both sides agree on this structure::

    <root>/
        queue/<video_id>.url     # direct media URL, awaiting download
        videos/<video_id>.mp4    # finished downloads
        failed/<video_id>.url    # URLs that expired / failed validation
        archive.txt              # "youtube <id>" lines, yt-dlp compatible
        logs/
        state.json               # small bookkeeping file
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Layout:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser()

    @property
    def queue(self) -> Path:
        return self.root / "queue"

    @property
    def videos(self) -> Path:
        return self.root / "videos"

    @property
    def failed(self) -> Path:
        return self.root / "failed"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def archive(self) -> Path:
        return self.root / "archive.txt"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    def ensure(self) -> Layout:
        for directory in (self.root, self.queue, self.videos, self.failed, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def read_archive(self) -> set[str]:
        ids: set[str] = set()
        if self.archive.exists():
            for line in self.archive.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    ids.add(parts[-1])
        return ids

    def append_archive(self, video_id: str) -> None:
        with open(self.archive, "a") as fh:
            fh.write(f"youtube {video_id}\n")

    def read_state(self) -> dict:
        if self.state.exists():
            try:
                return json.loads(self.state.read_text())
            except (ValueError, OSError):
                return {}
        return {}

    def write_state(self, data: dict) -> None:
        tmp = self.state.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.state)
