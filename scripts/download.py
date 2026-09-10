"""
Stage 1: USGS Landsat Downloader Script Wrapper.

This script delegates to the root download.py script, maintaining full compatibility
whether invoked from project root (python download.py) or scripts/ directory
(python scripts/download.py).
"""

import sys
import os

# Add root directory to sys.path so we can import download.py directly
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from download import main

if __name__ == "__main__":
    main()
