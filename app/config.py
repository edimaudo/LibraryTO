"""Application paths and immutable runtime configuration."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RELATE_FILE = DATA_DIR / "tpl_library_graph.rl"
APP_ENV = os.getenv("APP_ENV", "development")
