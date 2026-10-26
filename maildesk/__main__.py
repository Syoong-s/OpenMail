"""Default module entry point opens the native Linux desktop client."""
from .desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
