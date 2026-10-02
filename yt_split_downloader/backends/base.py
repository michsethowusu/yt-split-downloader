"""Backend interface.

A backend is the "other half": it moves queued URLs to wherever the download
happens, keeps a worker alive there, and brings results back. Three are
provided:

* :class:`~yt_split_downloader.backends.local.LocalBackend` - same machine
* :class:`~yt_split_downloader.backends.ssh.SshBackend` - a VPS / server over SSH
* :class:`~yt_split_downloader.backends.modal_backend.ModalBackend` - Modal containers

``stream`` backends (local/ssh) support the long-running ``run`` loop. Modal is
a ``batch`` backend: it is invoked once per batch and fans the downloads out.
"""

from __future__ import annotations

from pathlib import Path


class Backend:
    name = "base"
    stream = True

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # -- lifecycle ---------------------------------------------------------
    def prepare(self) -> None:
        """Validate prerequisites (binaries, credentials, network)."""

    def close(self) -> None:
        """Release resources. Does not have to stop a running worker."""

    # -- queries -----------------------------------------------------------
    def remote_done(self) -> set[str]:
        """Ids already downloaded on the download side."""
        return set()

    def remote_has_video(self, video_id: str) -> bool:
        return False

    def queue_depth(self) -> int:
        return 0

    # -- streaming mode ----------------------------------------------------
    def sync_queue(self, local_queue: Path) -> None:
        """Push ``<id>.url`` files to the download side."""

    def ensure_worker(self) -> None:
        """Start the download worker if it is not already running."""

    def pull_results(self, layout) -> None:
        """Bring finished videos and archive back to ``layout``."""

    # -- batch mode --------------------------------------------------------
    def dispatch(self, urls: dict) -> None:
        raise NotImplementedError

    def fetch_all(self, layout) -> None:
        pass
