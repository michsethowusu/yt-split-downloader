"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG_NAME, Config, load_config, write_default_config
from .layout import Layout


def _apply_overrides(cfg: Config, args) -> Config:
    g, d, b = cfg.general, cfg.download, cfg.backend
    if getattr(args, "project_dir", None):
        g.project_dir = args.project_dir
    if getattr(args, "urls_file", None):
        g.urls_file = args.urls_file
    if getattr(args, "format", None):
        g.format = args.format
    if getattr(args, "cookies", None):
        g.cookies = args.cookies
    if getattr(args, "backend", None):
        b.type = args.backend
    if getattr(args, "host", None):
        b.host = args.host
    if getattr(args, "remote_dir", None):
        b.remote_dir = args.remote_dir
    if getattr(args, "local_dir", None):
        b.local_dir = args.local_dir
    if getattr(args, "workers", None):
        d.workers = args.workers
    if getattr(args, "connections", None):
        d.connections = args.connections
    return cfg


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yt-split-downloader",
        description="Resolve YouTube URLs on a trusted-IP host, download the bytes elsewhere.",
    )
    p.add_argument("-c", "--config", default=None, help=f"path to {CONFIG_NAME}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-p", "--project-dir")
        sp.add_argument("-u", "--urls-file")
        sp.add_argument("-f", "--format", dest="format")
        sp.add_argument("--cookies")
        sp.add_argument("--backend", choices=["local", "ssh", "modal"])
        sp.add_argument("--host")
        sp.add_argument("--remote-dir")
        sp.add_argument("--local-dir")
        sp.add_argument("-w", "--workers", type=int)
        sp.add_argument("-x", "--connections", type=int)

    sp_init = sub.add_parser("init", help="write a starter config and urls file")
    sp_init.add_argument("--force", action="store_true")
    sp_init.add_argument("--urls-file", default="urls.txt")

    sp_resolve = sub.add_parser("resolve", help="resolve ids and feed the downloader")
    common(sp_resolve)
    sp_resolve.add_argument("--once", action="store_true", help="one pass then exit")
    sp_resolve.add_argument("--fetch", action="store_true", help="modal: pull results down")

    sp_worker = sub.add_parser("worker", help="run a download worker on this machine")
    common(sp_worker)
    sp_worker.add_argument("--poll", type=int, default=None)
    sp_worker.add_argument("--once", action="store_true")

    sub.add_parser("ls", help="show queue / downloaded counts")

    sp_stop = sub.add_parser("stop", help="stop the remote (ssh) worker")
    common(sp_stop)

    sub.add_parser("modal-deploy", help="deploy the Modal app")
    return p


# ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    cfg_path = Path(args.config) if args.config else Path(CONFIG_NAME)
    if cfg_path.exists() and not args.force:
        print(f"{cfg_path} already exists (use --force to overwrite)")
    else:
        write_default_config(cfg_path)
        print(f"wrote {cfg_path}")
    urls = Path(args.urls_file)
    if not urls.exists():
        urls.write_text(
            "# One YouTube URL or 11-character video id per line.\n"
            "# https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        )
        print(f"wrote {urls}")
    return 0


def cmd_resolve(args) -> int:
    from .backends import get_backend
    from .resolver import run_batch, run_stream

    cfg = _apply_overrides(load_config(args.config), args)
    backend = get_backend(cfg)
    backend.prepare()
    if backend.stream:
        run_stream(cfg, backend, once=args.once)
    else:
        run_batch(cfg, backend, once=True, fetch=args.fetch)
    return 0


def cmd_worker(args) -> int:
    from .download_core import Worker, require_tools

    require_tools("aria2c", "ffprobe")
    cfg = _apply_overrides(load_config(args.config), args)
    root = Path(cfg.backend.local_dir or cfg.general.project_dir)
    layout = Layout(root).ensure()
    worker = Worker(
        queue_dir=layout.queue,
        videos_dir=layout.videos,
        archive_path=layout.archive,
        failed_dir=layout.failed,
        workers=cfg.download.workers,
        connections=cfg.download.connections,
        user_agent=cfg.download.user_agent,
        timeout=cfg.download.timeout,
        validate=cfg.download.validate,
        min_bytes=cfg.download.min_bytes,
    )
    worker.run(poll=args.poll or cfg.general.poll_interval, once=args.once)
    return 0


def cmd_ls(args) -> int:
    cfg = load_config(args.config)
    layout = Layout(cfg.backend.local_dir or cfg.general.project_dir)
    queued = len(list(layout.queue.glob("*.url"))) if layout.queue.exists() else 0
    videos = len(list(layout.videos.glob("*.mp4"))) if layout.videos.exists() else 0
    archived = len(layout.read_archive())
    try:
        from .backends import get_backend

        depth = get_backend(cfg).queue_depth()
        depth_str = str(depth)
    except Exception as exc:
        depth_str = f"n/a ({exc})"
    print(f"project : {layout.root}")
    print(f"queued  : {queued} local, {depth_str} remote")
    print(f"videos  : {videos} local")
    print(f"archive : {archived} ids")
    return 0


def cmd_stop(args) -> int:
    from .backends import get_backend

    cfg = _apply_overrides(load_config(args.config), args)
    backend = get_backend(cfg)
    stopper = getattr(backend, "stop_worker", None)
    if stopper is None:
        print(f"{backend.name} backend has no long-running worker to stop")
        return 0
    stopper()
    print("remote worker stopped")
    return 0


def cmd_modal_deploy(args) -> int:
    import subprocess

    here = Path(__file__).resolve().parent / "modal_app.py"
    return subprocess.call(["modal", "deploy", str(here)])


_COMMANDS = {
    "init": cmd_init,
    "resolve": cmd_resolve,
    "worker": cmd_worker,
    "ls": cmd_ls,
    "stop": cmd_stop,
    "modal-deploy": cmd_modal_deploy,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
