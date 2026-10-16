# framegen

Raise any video to a higher frame rate (60 fps by default) with neural frame
interpolation. It turns 24 / 25 / 30 fps footage into smooth 60 fps, keeps the
audio, and runs on any GPU — or on the CPU.

## What it does

- Reads the real source frame rate and picks an exact ratio (so 23.976 fps also
  lands on smooth 60 fps).
- Fills in the missing frames with **RIFE** (neural interpolation), not a simple
  blend.
- Uses your GPU for speed (NVIDIA, AMD, Intel, Apple) and falls back to the CPU
  when there is none.
- Keeps the audio track as-is.

## Supported formats

Anything ffmpeg can read: MP4, MOV, MKV, WebM, AVI, WMV, TS and similar.

## Usage

Download the latest release for your platform from
[Releases](https://github.com/wdmcourses/framegen/releases/latest), then make
`framegen` available in your terminal:

- **Windows** — extract `framegen-win-x64.zip` and add the folder to `PATH`.
- **Linux** — extract `framegen-linux-x64.tar.gz` and symlink it, e.g.
  `ln -s "$PWD/framegen-linux-x64/framegen" ~/.local/bin/framegen`.
- **macOS** — extract `framegen-mac-arm64.zip`, run `xattr -cr framegen-mac-arm64`
  once, and symlink it, e.g.
  `ln -s "$PWD/framegen-mac-arm64/framegen" /usr/local/bin/framegen`.

Then:

```
framegen <file>
framegen -r <folder>
```

The result is saved in the current folder as `<name>_60fps.<ext>`.

To pick a different frame rate:

```
framegen clip.mp4 -f 120
```

To process a whole folder (unsupported files are skipped):

```
framegen -r clips/
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-f, --fps` | `60` | Target frame rate. |
| `-o, --output` | `<name>_<fps>fps.<ext>` | Output file. |
| `-r, --recursive` | off | Process every video in a folder. |
| `-q, --quiet` | off | Print only the output path. |
| `-v, --verbose` | off | Print progress lines (for host apps). |

Everything else is tuned automatically. A few advanced options (codec, quality,
model, lossless output) are still accepted but hidden from `--help`.

## Running from source

The repository ships code only. To fetch the engine and weights for the current
platform:

```
framegen -i
```

Set `FRAMEGEN_MIRROR=<base url>` to pull the lean per-platform archives instead
of the large upstream release. The recommended setup (engine + `rife-v4.6`) is
about **17 MB** on disk.

## Building

```
python scripts/fetch_engines.py    # engine binaries for all platforms
python scripts/pack.py             # dist/framegen-<platform>/ + archives
```

Output: `framegen-win-x64.zip`, `framegen-linux-x64.tar.gz`,
`framegen-mac-arm64.zip`.

## Credits

- [RIFE](https://github.com/hzwer/arXiv2020-RIFE) - frame interpolation (MIT).
- [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan) - the portable
  Vulkan engine (MIT).
- [FFmpeg](https://ffmpeg.org).
- This tool is MIT-licensed.
