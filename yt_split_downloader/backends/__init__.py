"""Backend registry and factory."""

from __future__ import annotations

from .base import Backend
from .local import LocalBackend
from .ssh import SshBackend

_BACKENDS = {
    "local": LocalBackend,
    "ssh": SshBackend,
}


def get_backend(cfg) -> Backend:
    kind = cfg.backend.type.lower()
    if kind == "modal":
        # imported lazily so the modal SDK is only required when actually used
        from .modal_backend import ModalBackend

        return ModalBackend(cfg)
    try:
        cls = _BACKENDS[kind]
    except KeyError:
        raise ValueError(f"unknown backend {kind!r}; choose one of: local, ssh, modal") from None
    return cls(cfg)


__all__ = ["Backend", "LocalBackend", "SshBackend", "get_backend"]
