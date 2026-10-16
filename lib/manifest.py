"""Pinned, tested component releases.

Nothing here is ever "latest": every source is an exact tag / commit so an
install is reproducible, and every artifact is size-checked (and checksum-
checked when a mirror provides one).

The engine archive published upstream bundles *all* RIFE models (431 MB). We
only ever extract the engine executable plus the requested model folder(s) from
it, so an install stays around 15 MB.
"""

import os

# --- upstream project pins ------------------------------------------------
RIFE_REPO = "nihui/rife-ncnn-vulkan"
RIFE_TAG = "20221029"                                  # never "latest"
RIFE_COMMIT = "a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7"
RELEASE_BASE = "https://github.com/%s/releases/download/%s" % (RIFE_REPO, RIFE_TAG)

# --- framegen's own lean mirror (optional, preferred when set) -------------
# Put small per-platform engine archives and model archives here. Override
# with the FRAMEGEN_MIRROR environment variable, e.g.
#   FRAMEGEN_MIRROR=https://github.com/you/framegen/releases/download/v1.0
MIRROR = os.environ.get("FRAMEGEN_MIRROR", "").rstrip("/")

# Platform -> (asset name, url, size)
ENGINE = {
    "win64": ("rife-ncnn-vulkan-20221029-windows.zip",
              RELEASE_BASE + "/rife-ncnn-vulkan-20221029-windows.zip",
              431540241),
    "lin64": ("rife-ncnn-vulkan-20221029-ubuntu.zip",
              RELEASE_BASE + "/rife-ncnn-vulkan-20221029-ubuntu.zip",
              431302796),
    "mac": ("rife-ncnn-vulkan-20221029-macos.zip",
            RELEASE_BASE + "/rife-ncnn-vulkan-20221029-macos.zip",
            436537917),
}

# Files taken out of the engine archive for each platform (basenames).
ENGINE_FILES = {
    "win64": ("rife-ncnn-vulkan.exe", "vcomp140.dll"),
    "lin64": ("rife-ncnn-vulkan",),
    "mac": ("rife-ncnn-vulkan",),
}

ENGINE_EXE = {
    "win64": "rife-ncnn-vulkan.exe",
    "lin64": "rife-ncnn-vulkan",
    "mac": "rife-ncnn-vulkan",
}

# Model name -> ((filename, size) ...) exactly as shipped inside the pinned
# engine archive. Sizes are verified after extraction.
MODELS = {
    "rife-v4.6": (("flownet.bin", 10614320), ("flownet.param", 16749)),
    "rife-v4": (("flownet.bin", 10340416), ("flownet.param", 12999)),
}

DEFAULT_MODELS = ("rife-v4.6",)

# ffmpeg/ffprobe are resolved from resources/<platform>, then from PATH. The
# repository ships a pinned ffmpeg per platform (shared with lossless-debreath);
# the tool never downloads ffmpeg implicitly.
