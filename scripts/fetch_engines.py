"""Fetch the pinned RIFE engine binaries for every platform into resources/.

    python scripts/fetch_engines.py                 # all platforms
    python scripts/fetch_engines.py --platform lin64 mac
    python scripts/fetch_engines.py --force

The engine executable is per-platform; the model weights in resources/models
are platform-independent and are not touched here. Archives are cached under
the user cache dir (see lib.config.cache_dir), so re-runs do not re-download.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import manifest  # noqa: E402
from lib.install import install_engine  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Fetch pinned engine binaries.")
    ap.add_argument("--platform", nargs="+", choices=list(manifest.ENGINE) + ["all"],
                    default=["all"])
    ap.add_argument("--force", action="store_true", help="re-extract even if present")
    args = ap.parse_args()

    plats = list(manifest.ENGINE) if "all" in args.platform else args.platform
    for plat in plats:
        install_engine(plat, force=args.force)


if __name__ == "__main__":
    main()
