"""Private portable Windows entry point, invoked by the native PE launcher."""
from pathlib import Path
import sys

# ==========================================
# Function: Start the native mail client from its own source directory.
# Method: Use isolated embedded Python and never require caller cwd, PATH or site packages.
# ==========================================
def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from maildesk.desktop import main as desktop_main
    return desktop_main()

if __name__ == '__main__':
    raise SystemExit(main())
