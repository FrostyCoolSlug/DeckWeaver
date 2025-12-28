"""Constants used throughout the DeckWeaver plugin"""
from typing import Final

# PipeWeaver WebSocket configuration
PIPEWEAVER_HOST: Final[str] = "localhost"
PIPEWEAVER_PORT: Final[int] = 14565
PIPEWEAVER_WS_ENDPOINT: Final[str] = f"ws://{PIPEWEAVER_HOST}:{PIPEWEAVER_PORT}/api/websocket"
PIPEWEAVER_METER_ENDPOINT: Final[str] = f"ws://{PIPEWEAVER_HOST}:{PIPEWEAVER_PORT}/api/websocket/meter"

# Service monitor configuration
CHECK_INTERVAL: Final[float] = 5.0  # seconds between service checks
CONNECTION_TIMEOUT: Final[float] = 2.0  # seconds for socket timeout
RECONNECT_DELAY: Final[float] = 5.0  # seconds to wait before reconnecting

# WebSocket timeouts
WS_TIMEOUT: Final[float] = 5.0  # seconds for WebSocket connection timeout
WS_SOCK_TIMEOUT: Final[float] = 1.0  # seconds for socket recv timeout
COMMAND_TIMEOUT: Final[float] = 5.0  # seconds for command response timeout
INITIAL_STATUS_TIMEOUT: Final[float] = 10.0  # seconds for initial status request

# Device types
DEVICE_TYPE_SOURCE: Final[str] = "source"
DEVICE_TYPE_TARGET: Final[str] = "target"

# Volume settings
DEFAULT_VOLUME: Final[int] = 50
DEFAULT_VOLUME_STEP: Final[int] = 5
MIN_VOLUME_STEP: Final[int] = 1
MAX_VOLUME_STEP: Final[int] = 20
VOLUME_MIN: Final[int] = 0
VOLUME_MAX: Final[int] = 100
VOLUME_RAW_MAX: Final[int] = 255

# Image rendering constants
IMAGE_WIDTH: Final[int] = 480
IMAGE_HEIGHT: Final[int] = 240
EDGE_PADDING: Final[int] = 10
ICON_MAX_SIZE: Final[int] = 150
BAR_HEIGHT: Final[int] = 32
BAR_RADIUS: Final[int] = 4
METER_HEIGHT: Final[int] = 10
METER_EDGE_INSET: Final[int] = 6

# Font paths for monospace fonts
MONOSPACE_FONT_PATHS: Final[tuple[tuple[str, bool], ...]] = (
    ("/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf", True),
    ("/usr/share/fonts/truetype/source-code-pro/SourceCodePro-Bold.ttf", True),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", True),
    ("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf", True),
    ("/usr/share/fonts/truetype/ubuntu/UbuntuMono-Bold.ttf", True),
    ("/usr/share/fonts/truetype/fira-code/FiraCode-Bold.ttf", True),
    ("/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf", False),
    ("/usr/share/fonts/truetype/source-code-pro/SourceCodePro-Regular.ttf", False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", False),
    ("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf", False),
    ("/usr/share/fonts/TTF/arial.ttf", False),
    ("/System/Library/Fonts/Monaco.ttf", False),
    ("C:/Windows/Fonts/consola.ttf", False),
)

# Color constants
COLOR_BACKGROUND_DARK: Final[tuple[int, int, int, int]] = (30, 30, 30, 255)
COLOR_OUTLINE_GRAY: Final[tuple[int, int, int, int]] = (60, 60, 60, 255)
COLOR_MUTED_BG: Final[tuple[int, int, int, int]] = (38, 38, 38, 255)
COLOR_MUTED_FILL: Final[tuple[int, int, int, int]] = (77, 77, 77, 255)
COLOR_MUTED_OUTLINE: Final[tuple[int, int, int, int]] = (77, 77, 77, 255)
COLOR_TARGET_BG: Final[tuple[int, int, int, int]] = (20, 38, 20, 255)
COLOR_TARGET_OUTLINE: Final[tuple[int, int, int, int]] = (102, 204, 102, 255)
COLOR_TARGET_FILL: Final[tuple[int, int, int, int]] = (102, 255, 102, 255)
COLOR_SOURCE_FILL: Final[tuple[int, int, int, int]] = (102, 179, 255, 255)
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)
COLOR_LABEL: Final[tuple[int, int, int, int]] = (204, 204, 204, 204)
COLOR_SERVICE_UNAVAILABLE_BG: Final[tuple[int, int, int, int]] = (255, 193, 7, 255)
COLOR_SERVICE_UNAVAILABLE_TEXT: Final[tuple[int, int, int, int]] = (33, 33, 33, 255)
COLOR_SERVICE_UNAVAILABLE_HINT: Final[tuple[int, int, int, int]] = (66, 66, 66, 255)

# JSON Patch operation types
JSON_PATCH_ADD: Final[str] = "add"
JSON_PATCH_REMOVE: Final[str] = "remove"
JSON_PATCH_REPLACE: Final[str] = "replace"

# Special message IDs
MESSAGE_ID_PATCH: Final[int] = 2**64 - 1

# SVG conversion settings
SVG_DEFAULT_SIZE: Final[tuple[int, int]] = (400, 400)
SVG_PADDING: Final[int] = 2

