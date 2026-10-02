"""Configuration loading for yt-split-downloader.

A single TOML file (``yt-split-downloader.toml``) holds everything. Any value
can also be overridden on the command line. Environment variables of the form
``YTSD_*`` override the file, which is handy for CI or Modal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore

CONFIG_NAME = "yt-split-downloader.toml"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class GeneralConfig:
    urls_file: str = "urls.txt"
    project_dir: str = "yt-split-data"
    format: str = "bv*[protocol=https]"
    resolve_delay: float = 2.5
    batch: int = 40
    hwm: int = 80
    poll_interval: int = 20
    cookies: Optional[str] = None
    yt_dlp: str = "yt-dlp"


@dataclass
class DownloadConfig:
    workers: int = 5
    connections: int = 16
    user_agent: str = DEFAULT_USER_AGENT
    timeout: int = 3600
    validate: bool = True
    min_bytes: int = 65536


@dataclass
class BackendConfig:
    type: str = "ssh"  # ssh | local | modal
    host: Optional[str] = None
    remote_dir: Optional[str] = None
    local_dir: Optional[str] = None
    ssh_options: list[str] = field(default_factory=list)
    remote_python: str = "python3"
    tmux: bool = True
    modal_app: str = "yt-split-downloader"
    modal_volume: str = "yt-split-downloader"
    modal_timeout: int = 3600
    modal_max_containers: int = 20


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    backend: BackendConfig = field(default_factory=BackendConfig)
    path: Optional[Path] = None

    @property
    def project_dir(self) -> Path:
        return Path(self.general.project_dir).expanduser().resolve()

    @property
    def urls_file(self) -> Path:
        p = Path(self.general.urls_file).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)


def _apply(obj: Any, data: Optional[dict]) -> None:
    if not data:
        return
    valid = {f.name for f in fields(obj)}
    for key, value in data.items():
        if key in valid:
            setattr(obj, key, value)


_ENV_MAP = {
    "YTSD_PROJECT_DIR": ("general", "project_dir"),
    "YTSD_URLS_FILE": ("general", "urls_file"),
    "YTSD_FORMAT": ("general", "format"),
    "YTSD_COOKIES": ("general", "cookies"),
    "YTSD_BACKEND": ("backend", "type"),
    "YTSD_HOST": ("backend", "host"),
    "YTSD_REMOTE_DIR": ("backend", "remote_dir"),
    "YTSD_LOCAL_DIR": ("backend", "local_dir"),
}


def _apply_env(cfg: Config) -> None:
    sections = {"general": cfg.general, "backend": cfg.backend, "download": cfg.download}
    for env, (section, attr) in _ENV_MAP.items():
        value = os.environ.get(env)
        if value is not None:
            setattr(sections[section], attr, value)


def find_config(start: Optional[os.PathLike | str] = None) -> Optional[Path]:
    """Walk up from *start* (default cwd) looking for the config file."""
    base = Path(start or os.getcwd()).resolve()
    for directory in [base, *base.parents]:
        candidate = directory / CONFIG_NAME
        if candidate.exists():
            return candidate
    return None


def load_config(path: Optional[os.PathLike | str] = None) -> Config:
    """Load config from *path*, else search upward, then apply env overrides."""
    cfg = Config()
    chosen = Path(path).expanduser() if path is not None else find_config()
    if chosen is not None and Path(chosen).exists():
        cfg.path = Path(chosen).resolve()
        with open(cfg.path, "rb") as fh:
            raw = tomllib.load(fh)
        _apply(cfg.general, raw.get("general"))
        _apply(cfg.download, raw.get("download"))
        _apply(cfg.backend, raw.get("backend"))
    _apply_env(cfg)
    return cfg


DEFAULT_CONFIG_TOML = """\
# yt-split-downloader configuration
#
# resolve  -> run this on the machine whose IP YouTube trusts (your PC)
# worker   -> run this on the machine that should download the bytes
#             (a VPS, Modal, or the same PC)

[general]
urls_file = "urls.txt"          # one video URL or 11-char id per line
project_dir = "yt-split-data"   # where queue/, logs/ and state live
format = "bv*[protocol=https]"  # direct (non-HLS) best video; do not use bare bv*
resolve_delay = 2.5             # seconds between yt-dlp calls (be nice)
batch = 40                      # URLs resolved per pass
hwm = 80                        # pause resolving when the remote queue is this deep
poll_interval = 20              # seconds between passes
# cookies = "cookies.txt"       # optional, if some videos need sign-in

[download]
workers = 5                     # parallel aria2c processes
connections = 16                # aria2c connections per file
timeout = 3600                  # per-file timeout (seconds)
validate = true                 # ffprobe every download, reject non-media
min_bytes = 65536

[backend]
# type = "ssh" | "local" | "modal"
type = "ssh"

# --- ssh/VPS backend -------------------------------------------------------
host = "myserver"               # ssh alias or user@host
remote_dir = "/data/yt-split"   # project dir on the download machine
remote_python = "python3"
tmux = true                     # launch the remote worker inside tmux

# --- local backend (download on this same machine) -------------------------
# local_dir = "/data/yt-split"

# --- modal backend ---------------------------------------------------------
# type = "modal"
# modal_app = "yt-split-downloader"
# modal_volume = "yt-split-downloader"
"""


def write_default_config(path: os.PathLike | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML)
    return path
