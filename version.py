"""Version information - uses Rust core version"""

try:
    from deckweaver import VERSION
except ImportError:
    VERSION = "0.3.0"
