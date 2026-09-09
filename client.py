"""Repository convenience entry point; distributed client lives with its skill."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / ".cline/skills/web-search/scripts/web_relay_client.py"), run_name="__main__")
