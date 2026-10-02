# yt-split-downloader

Download large YouTube collections when the machine that *can* reach YouTube
is not the machine that *should* do the downloading.

YouTube gates its website/API behind IP reputation. A VPS or a serverless
container on a datacenter IP often cannot list formats or start an extractor,
even with cookies. But the media itself is served from `googlevideo.com`, which
is **not** IP-locked. So:

1. **resolve** on a machine with a trusted IP (your home/office PC):

   ```
   yt-dlp -f "bv*[protocol=https]" -g "https://www.youtube.com/watch?v=ID"
   ```

   This prints a direct `googlevideo.com` URL. No bytes are downloaded.

2. **download** that URL on the second machine (VPS / Modal / same PC) with
   `aria2c` (multi-connection), writing `videos/<id>.mp4`.

`yt-split-downloader` wires those two halves together with a queue, an archive,
retries, and `ffprobe` validation.

## Why `bv*[protocol=https]`

A bare `bv*` can resolve to an **HLS manifest**
(`manifest.googlevideo.com/.../hls_playlist/...`). `aria2c` then saves the tiny
playlist text as `.mp4`, producing a corrupt stub. Restricting the format to
progressive HTTPS (`[protocol=https]`) guarantees a real media URL.

## Install

```bash
pip install .            # local/ssh backends
pip install '.[modal]'   # adds the Modal SDK
```

Requirements:

* `yt-dlp` on the **resolver** host
* `aria2c` and `ffprobe` (ffmpeg) on the **download** host
* `ssh` + `rsync` locally for the `ssh` backend

## Quick start

```bash
yt-split-downloader init                 # writes config + urls.txt
# edit urls.txt and yt-split-downloader.toml
yt-split-downloader resolve             # runs forever; Ctrl-C to stop
```

`resolve` runs on the trusted-IP machine, watches `urls.txt`, resolves pending
ids, pushes `<id>.url` files to the download side, keeps its worker alive, and
pulls finished video files back.

## Backends

Pick one with `backend.type` (or `--backend`).

### `local`

Resolver and worker on the same machine. The worker runs in a background thread.

```toml
[backend]
type = "local"
local_dir = "/data/yt-split"
```

### `ssh` (VPS / server)

The remote host needs only `python3`, `aria2c` and `ffprobe`. `yt-split-downloader`
ships the worker to `<remote>/.ytsd/` with rsync and launches it in tmux. Queued
URLs and finished videos move over rsync.

```toml
[backend]
type = "ssh"
host = "myserver"              # ~/.ssh/config alias, or user@host
remote_dir = "/data/yt-split"
remote_python = "python3"
tmux = true
```

```bash
yt-split-downloader resolve
yt-split-downloader ls         # local + remote queue depth
yt-split-downloader stop       # kill the remote tmux worker
```

### `modal`

Fan downloads across serverless containers. Results land on a Modal Volume;
use `--fetch` to copy them to the resolver machine.

```bash
pip install '.[modal]'
yt-split-downloader modal-deploy          # deploy the app
yt-split-downloader resolve --fetch       # one batch, then pull results down
```

## Layout

```
project_dir/
    queue/<id>.url      direct media URLs awaiting download
    videos/<id>.mp4     finished downloads
    failed/<id>.url     unusable/expired URLs
    archive.txt         "youtube <id>" lines
    attempts.json       resolve back-off bookkeeping
    logs/
```

`archive.txt` is yt-dlp-compatible, so `yt-dlp --download-archive archive.txt`
will skip what has already been fetched.

## Commands

| command        | does |
|----------------|------|
| `init`         | write a starter config and `urls.txt` |
| `resolve`      | resolve ids and feed the downloader (long-running; `--once` for one pass) |
| `worker`       | run a download worker on this machine |
| `ls`           | show queue / downloaded counts |
| `stop`         | stop the remote (ssh) worker |
| `modal-deploy` | deploy the Modal app |

## Notes and gotchas

* Direct URLs carry an `expire` (~6 h). Resolve, then download promptly; the
  resolver retries an id automatically after 6 h if it never arrived.
* `aria2c -o /abs/path` is treated as *relative to `$HOME`*; this tool always
  uses `--dir <videos_dir> -o <bare-name>` instead.
* Partial files are named `.<id>.part.mp4` so watchers ignore them. `ffprobe`
  runs before the rename to `.mp4`.
* Cookies (`general.cookies`) are only needed for age/region-restricted videos.
  Keep the cookie file private; never commit it.

## License

MIT
