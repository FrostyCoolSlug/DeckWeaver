"""DeckWeaver - Stream Deck plugin for PipeWeaver audio control"""

import sys
import sysconfig
from importlib import import_module
from pathlib import Path

# Detect the correct extension module based on Python version
def _load_core_module():
    """Load the correct _core module based on the current Python version."""
    # Get the extension suffix for this Python version (includes .so extension)
    ext_suffix = sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO')
    
    # Construct the module filename with the extension suffix
    # e.g., _core.cpython-312-x86_64-linux-gnu.so
    module_filename = f"_core{ext_suffix}"
    
    # Get the directory where this __init__.py is located
    package_dir = Path(__file__).parent
    module_file = package_dir / module_filename
    
    # Try to import the version-specific module using importlib
    if module_file.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("deckweaver._core", module_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception as e:
            # If loading fails, continue to fallback options
            pass
    
    # Fallback 1: try importing _core directly (for backward compatibility)
    # This works if there's only one _core*.so file or if Python can auto-detect it
    try:
        from . import _core
        return _core
    except ImportError:
        pass
    
    # Fallback 2: try to find any _core*.so file and load it
    # This is useful if the extension suffix doesn't match exactly
    available_modules = list(package_dir.glob("_core*.so"))
    if available_modules:
        # Try the first available module as a last resort
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("deckweaver._core", available_modules[0])
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception:
            pass
    
    # If all imports fail, raise an informative error
    available_names = [f.name for f in available_modules] if available_modules else []
    
    raise ImportError(
        f"Could not find compatible _core module for Python {sys.version_info.major}.{sys.version_info.minor}.\n"
        f"Expected module: {module_filename}\n"
        f"Available modules: {available_names if available_names else 'none'}\n"
        f"Please run './build.sh all' to build extension modules for all Python versions."
    )

# Load the core module
_core = _load_core_module()

# Import all the public API from the core module
VERSION = _core.VERSION
DEFAULT_PORT = _core.DEFAULT_PORT
DeckWeaverCore = _core.DeckWeaverCore
ActionConfig = _core.ActionConfig
ActionType = _core.ActionType
Device = _core.Device
DeviceColor = _core.DeviceColor
DeviceType = _core.DeviceType
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
    "KnobRenderer",
    "SliderRenderer",
    "ButtonRenderer",
    "load_icon_to_png",
]
