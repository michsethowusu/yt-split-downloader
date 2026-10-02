"""SSH backend: resolve on this machine, download on a VPS/server.

The remote needs only ``python3`` (stdlib), ``aria2c`` and ``ffprobe``. We ship
the worker (``worker.py`` + ``download_core.py``) to ``<remote>/.ytsd/`` with
rsync, then launch it inside tmux. Queued URLs are pushed with rsync, finished
videos are pulled back with rsync.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..layout import Layout
from .base import Backend

SESSION = "ytsd_worker"


class SshBackend(Backend):
    name = "ssh"
    stream = True

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        if not cfg.backend.host or not cfg.backend.remote_dir:
            raise ValueError("ssh backend requires backend.host and backend.remote_dir")
        self.host = cfg.backend.host
        self.remote = cfg.backend.remote_dir.rstrip("/")
        self.python = cfg.backend.remote_python
        self.ssh_opts = list(cfg.backend.ssh_options)

    # -- plumbing ----------------------------------------------------------
    def _ssh(self, command: str, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = ["ssh", *self.ssh_opts, self.host, command]
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=False,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )

    def _rsync(self, src: str, dst: str, ignore_existing: bool = False) -> None:
        cmd = ["rsync", "-az"]
        if ignore_existing:
            cmd.append("--ignore-existing")
        cmd += ["-e", "ssh " + " ".join(self.ssh_opts), src, dst]
        subprocess.run(cmd, check=True)

    # -- lifecycle ---------------------------------------------------------
    def prepare(self) -> None:
        if shutil.which("ssh") is None or shutil.which("rsync") is None:
            raise RuntimeError("ssh and rsync must be installed locally")
        dirs = " ".join(
            f"{self.remote}/{name}" for name in ("queue", "videos", "failed", "logs", ".ytsd")
        )
        self._ssh(f"mkdir -p {dirs}", capture=True)
        here = Path(__file__).resolve().parent.parent
        self._rsync(str(here / "download_core.py"), f"{self.host}:{self.remote}/.ytsd/")
        self._rsync(str(here / "worker.py"), f"{self.host}:{self.remote}/.ytsd/")

    def remote_done(self) -> set[str]:
        result = self._ssh(
            f"cat {self.remote}/archive.txt 2>/dev/null; ls -1 {self.remote}/videos 2>/dev/null"
        )
        ids: set[str] = set()
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("youtube "):
                ids.add(line.split()[-1])
            elif line.endswith(".mp4"):
                ids.add(Path(line).stem)
        return ids

    def remote_has_video(self, video_id: str) -> bool:
        result = self._ssh(f"test -f {self.remote}/videos/{video_id}.mp4")
        return result.returncode == 0

    def queue_depth(self) -> int:
        result = self._ssh(f"ls -1 {self.remote}/queue/*.url 2>/dev/null | wc -l")
        try:
            return int((result.stdout or "0").strip())
        except ValueError:
            return 0

    # -- streaming ---------------------------------------------------------
    def sync_queue(self, local_queue: Path) -> None:
        self._rsync(f"{local_queue}/", f"{self.host}:{self.remote}/queue/")

    def ensure_worker(self) -> None:
        running = self._ssh(f"tmux has-session -t {SESSION} 2>/dev/null").returncode == 0
        if running:
            return
        command = (
            f"cd {self.remote}/.ytsd && exec {self.python} worker.py "
            f"--root {self.remote} --workers {self.cfg.download.workers} "
            f"--connections {self.cfg.download.connections} "
            f"--poll {self.cfg.general.poll_interval} >> {self.remote}/logs/worker.log 2>&1"
        )
        if self.cfg.backend.tmux:
            self._ssh(f"tmux new-session -d -s {SESSION} {command!r}", capture=True)
        else:
            self._ssh(f"nohup sh -c {command!r} >/dev/null 2>&1 &", capture=True)

    def pull_results(self, layout: Layout) -> None:
        layout.ensure()
        self._rsync(f"{self.host}:{self.remote}/videos/", f"{layout.videos}/", ignore_existing=True)
        result = self._ssh(f"cat {self.remote}/archive.txt 2>/dev/null")
        remote_ids = {
            line.split()[-1]
            for line in (result.stdout or "").splitlines()
            if line.startswith("youtube ")
        }
        known = layout.read_archive()
        with open(layout.archive, "a") as fh:
            fh.writelines(f"youtube {video_id}\n" for video_id in sorted(remote_ids - known))

    def stop_worker(self) -> None:
        self._ssh(f"tmux kill-session -t {SESSION} 2>/dev/null", capture=True)

    def close(self) -> None:
        # Leave the worker running between resolver passes.
        return
