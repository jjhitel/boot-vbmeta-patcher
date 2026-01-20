import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ltbox.main import entry_point  # noqa: E402

if __name__ == "__main__":
    try:
        entry_point()
    except KeyboardInterrupt:
        sys.exit(0)
