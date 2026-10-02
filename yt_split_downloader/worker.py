"""Standalone worker entry point.

The SSH backend ships this file (plus ``download_core.py``) to the download
host and runs it with the plain system ``python3`` -- no pip install needed on
the remote side. It only depends on the standard library, ``aria2c`` and
``ffprobe``.

Usage on the remote host::

    python3 worker.py --root /data/yt-split --workers 5 --conn 16
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from download_core import DEFAULT_USER_AGENT, Worker, require_tools


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="yt-split-downloader remote worker")
    p.add_argument("--root", required=True, help="project dir containing queue/ and videos/")
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--connections", type=int, default=16, dest="connections")
    p.add_argument("--poll", type=int, default=20)
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--min-bytes", type=int, default=65536)
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--once", action="store_true", help="drain the queue then exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    require_tools("aria2c", "ffprobe")
    root = Path(args.root).expanduser()
    worker = Worker(
        queue_dir=root / "queue",
        videos_dir=root / "videos",
        archive_path=root / "archive.txt",
        failed_dir=root / "failed",
        workers=args.workers,
        connections=args.connections,
        user_agent=args.user_agent,
        timeout=args.timeout,
        validate=not args.no_validate,
        min_bytes=args.min_bytes,
    )
    worker.run(poll=args.poll, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
