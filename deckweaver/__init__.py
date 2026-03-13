"""DeckWeaver - Stream Deck plugin for PipeWeaver audio control"""

import importlib.util
import sys
from pathlib import Path

def _load_core():
    """Load the _core extension module (abi3 or version-specific)."""
    pkg = Path(__file__).parent
    candidates = [
        pkg / "_core.abi3.so",  # abi3 build (works on Python 3.11+)
        pkg / f"_core{sys.implementation.cache_tag.replace('cpython', '.cpython')}-{sys.platform}.so",
    ]
    # Also try any _core*.so as fallback
    candidates.extend(sorted(pkg.glob("_core*.so")))

    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("deckweaver._core", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod

    available = [p.name for p in pkg.glob("_core*.so")]
    raise ImportError(
        f"No compatible _core module for Python {sys.version_info.major}.{sys.version_info.minor}.\n"
        f"Available: {available or 'none'}. Build with: ./build.sh release  or  pip install."
    )

_core = _load_core()

# Re-export public API
VERSION = _core.VERSION
DEFAULT_PORT = _core.DEFAULT_PORT
DeckWeaverCore = _core.DeckWeaverCore
ActionConfig = _core.ActionConfig
ActionType = _core.ActionType
Device = _core.Device
DeviceColor = _core.DeviceColor
DeviceType = _core.DeviceType
HardwareDevice = _core.HardwareDevice
KnobRenderer = _core.KnobRenderer
SliderRenderer = _core.SliderRenderer
ButtonRenderer = _core.ButtonRenderer
load_icon_to_png = _core.load_icon_to_png

__version__ = VERSION
__all__ = [
    "VERSION",
    "DEFAULT_PORT",
    "DeckWeaverCore",
    "ActionConfig",
    "ActionType",
    "Device",
    "DeviceColor",
    "DeviceType",
    "HardwareDevice",
    "KnobRenderer",
    "SliderRenderer",
    "ButtonRenderer",
    "load_icon_to_png",
]
