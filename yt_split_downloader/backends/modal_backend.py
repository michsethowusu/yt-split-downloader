"""Modal backend: fan downloads out over serverless containers.

Modal containers run on datacenter IPs that YouTube's *website* blocks, but the
direct ``googlevideo`` URLs produced by the resolver are IP-agnostic, so the
containers can fetch them at high speed. Files land on a Modal Volume; use
``--fetch`` to copy them down to your machine (Modal Volumes are much smaller
than a full dataset).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..layout import Layout
from .base import Backend


class ModalBackend(Backend):
    name = "modal"
    stream = False

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        try:
            import modal
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "the modal backend needs the modal SDK: pip install 'yt-split-downloader[modal]'"
            ) from exc
        import modal

        self.modal = modal
        self.volume = modal.Volume.from_name(cfg.backend.modal_volume, create_if_missing=True)

    # -- lifecycle ---------------------------------------------------------
    def prepare(self) -> None:
        try:
            self.modal.Function.from_name(self.cfg.backend.modal_app, "download")
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                f"Modal app {self.cfg.backend.modal_app!r} not found. "
                f"Deploy it first: yt-split-downloader modal-deploy"
            ) from exc

    # -- queries -----------------------------------------------------------
    def remote_done(self) -> set[str]:
        ids: set[str] = set()
        try:
            entries = self.volume.listdir("videos", recursive=False)
        except Exception:
            entries = []
        for entry in entries:
            name = entry.path.rsplit("/", 1)[-1]
            if name.endswith(".mp4"):
                ids.add(Path(name).stem)
        return ids

    def remote_has_video(self, video_id: str) -> bool:
        return video_id in self.remote_done()

    # -- batch -------------------------------------------------------------
    def dispatch(self, urls: dict) -> None:
        fn = self.modal.Function.from_name(self.cfg.backend.modal_app, "download")
        dn = self.cfg.download
        payload = list(urls.items())
        print(f"Dispatching {len(payload)} downloads to Modal...", flush=True)
        handles = [
            fn.spawn(
                video_id,
                url,
                dn.connections,
                dn.user_agent,
                dn.timeout,
                dn.validate,
                dn.min_bytes,
            )
            for video_id, url in payload
        ]
        for handle in handles:
            try:
                handle.get()
            except Exception as exc:  # keep going on a single failure
                print(f"  a Modal download failed: {exc}", flush=True)

    def fetch_all(self, layout: Layout) -> None:
        layout.ensure()
        print("Fetching results from Modal Volume...", flush=True)
        try:
            videos = self.volume.listdir("videos", recursive=False)
        except Exception:
            videos = []
        for entry in videos:
            name = entry.path.rsplit("/", 1)[-1]
            if not name.endswith(".mp4"):
                continue
            dest = layout.videos / name
            if dest.exists():
                continue
            with open(dest, "wb") as out:
                shutil.copyfileobj(self.volume.read_file(f"videos/{name}"), out)
            layout.append_archive(Path(name).stem)
            print(f"  pulled {name}", flush=True)
