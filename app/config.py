"""Application paths and immutable runtime configuration."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RELATE_FILE = DATA_DIR / "tpl_library_graph.rl"
APP_ENV = os.getenv("APP_ENV", "development")

# The seven source files are intentionally colocated in one directory. The
# application does not accept alternate paths or filenames: deploy the agreed
# snapshots under data/ and redeploy to refresh the read-only deployment.
