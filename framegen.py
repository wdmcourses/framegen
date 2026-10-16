import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
