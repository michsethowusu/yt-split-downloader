"""yt-split-downloader: split YouTube bulk downloads across two machines.

The insight is simple: YouTube blocks *datacenter* IPs from resolving videos,
but a machine with a trusted (usually residential) IP can turn a video id into
a direct ``googlevideo`` media URL with ``yt-dlp -g``. That URL can then be
fetched, at full speed, from a different machine -- a VPS, a Modal container,
or the same box.

``yt-split-downloader`` packages that split:

* ``resolve`` runs on the trusted-IP machine and writes ``<id>.url`` files.
* ``worker`` runs on the download machine and turns those URLs into ``.mp4``
  files with ``aria2c`` (multi-connection) and ``ffprobe`` validation.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
