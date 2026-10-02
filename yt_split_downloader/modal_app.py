"""Modal application for yt-split-downloader.

Deploy with::

    modal deploy yt_split_downloader/modal_app.py

Then use the ``modal`` backend from the resolver. Each queued URL is downloaded
in its own container (bounded by ``max_containers``) and written to the shared
Volume at ``videos/<id>.mp4``.
"""

from __future__ import annotations

import modal

from yt_split_downloader.download_core import DEFAULT_USER_AGENT, download_one, require_tools

APP_NAME = "yt-split-downloader"
VOLUME_NAME = "yt-split-downloader"
MOUNT = "/data"

app = modal.App(APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("aria2", "ffmpeg")
    .add_local_python_source("yt_split_downloader")
)

volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.function(
    image=image,
    volumes={MOUNT: volume},
    timeout=3600,
    max_containers=20,
)
def download(
    video_id: str,
    url: str,
    connections: int = 16,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 3600,
    validate: bool = True,
    min_bytes: int = 65536,
) -> dict:
    from pathlib import Path

    require_tools("aria2c", "ffprobe")
    videos_dir = Path(MOUNT) / "videos"
    ok, detail = download_one(
        url,
        video_id,
        videos_dir,
        connections=connections,
        user_agent=user_agent,
        timeout=timeout,
        validate=validate,
        min_bytes=min_bytes,
    )
    if ok:
        volume.commit()
    return {"id": video_id, "ok": ok, "detail": detail}


@app.local_entrypoint()
def main(video_id: str, url: str) -> None:
    print(download.remote(video_id, url))
