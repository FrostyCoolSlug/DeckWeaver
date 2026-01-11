"""Version information for DeckWeaver, derived from git."""
import subprocess
from pathlib import Path


def get_version() -> str:
    """
    Get version string from git.
    
    Returns a version like:
    - "0.1.0" (if on exact tag)
    - "0.1.0-38-g71c704c" (38 commits after tag, short hash)
    - "0.1.0-38-g71c704c-dirty" (with uncommitted changes)
    - "71c704c" (fallback to short hash if no tags)
    - "unknown" (if not in git repo)
    """
    plugin_dir = Path(__file__).parent
    
    try:
        # Try git describe first (includes tag info + commits + hash)
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        
        # Fallback to short hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
            
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    
    return "unknown"


# Cache the version at import time
VERSION = get_version()
