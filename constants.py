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
MIN_VOLUME_STEP: Final[int] = 5
MAX_VOLUME_STEP: Final[int] = 20
VOLUME_MIN: Final[int] = 0
VOLUME_MAX: Final[int] = 100
VOLUME_RAW_MAX: Final[int] = 255

# Image rendering constants
# Base image dimensions - defines the canvas size for all rendered images
IMAGE_WIDTH: Final[int] = 480  # Total width of the rendered image
IMAGE_HEIGHT: Final[int] = 240  # Total height of the rendered image

# Layout spacing constants
EDGE_PADDING: Final[int] = 20  # General edge padding between icon and volume bar
CORNER_INSET: Final[int] = 28  # Extra inset from corners for rounded corner elements (icon, bar positioning)

# Icon layout constants
ICON_MAX_SIZE: Final[int] = 105  # Maximum size (width/height) for the device icon

# Volume bar constants
BAR_HEIGHT: Final[int] = 32  # Height of the volume bar (not including gutter)
BAR_RADIUS: Final[int] = 6  # Corner radius for volume bar rounded ends
BAR_GUTTER_SIZE: Final[int] = 6  # Size of gutter border around volume bar (creates border effect)
BAR_HORIZONTAL_OFFSET: Final[int] = 0  # Horizontal offset for bar position from calculated left margin
BAR_VERTICAL_OFFSET: Final[int] = 10  # Vertical offset from bottom edge for bar position
# Note: Bar width is calculated as: IMAGE_WIDTH - (CORNER_INSET + ICON_MAX_SIZE + EDGE_PADDING) - CORNER_INSET
# Bar Y position: IMAGE_HEIGHT - BAR_HEIGHT - CORNER_INSET - BAR_VERTICAL_OFFSET
# Gutter extends BAR_GUTTER_SIZE pixels beyond bar on all sides

# Meter (audio level indicator) constants
METER_HEIGHT: Final[int] = 10  # Height of the meter bar (drawn inside volume bar)
METER_HORIZONTAL_MARGIN: Final[int] = 10  # Horizontal margin from volume bar edges (left and right)
# Meter is vertically centered within the volume bar
# Meter width is calculated as: (meter_value / 100.0) * (fill_width - METER_HORIZONTAL_MARGIN * 2)

# Service unavailable screen layout
# Displayed when PipeWeaver daemon is not running
SERVICE_UNAVAILABLE_TITLE_Y: Final[int] = 60  # Vertical position for "PipeWeaver" title text
SERVICE_UNAVAILABLE_TITLE_FONT_SIZE: Final[int] = 28  # Font size for title text
SERVICE_UNAVAILABLE_SUBTITLE_Y: Final[int] = 100  # Vertical position for "Service Unavailable" subtitle
SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE: Final[int] = 18  # Font size for subtitle text
SERVICE_UNAVAILABLE_HINT_Y: Final[int] = 160  # Vertical position for hint text
SERVICE_UNAVAILABLE_HINT_FONT_SIZE: Final[int] = 18  # Font size for hint text
# All text is horizontally centered at IMAGE_WIDTH / 2

# Loading screen layout
# Displayed when devices are being loaded (spinner animation removed, only text shown)
LOADING_SPINNER_RADIUS: Final[int] = 20  # Radius of spinner circle (not currently used)
LOADING_SPINNER_DOT_COUNT: Final[int] = 8  # Number of dots in spinner (not currently used)
LOADING_SPINNER_DOT_RADIUS: Final[int] = 3  # Radius of each spinner dot (not currently used)
LOADING_SPINNER_VERTICAL_OFFSET: Final[int] = -30  # Vertical offset from center for spinner (not currently used)
LOADING_SPINNER_ANGLE_STEP: Final[float] = 0.1  # Animation speed multiplier (not currently used)
LOADING_SPINNER_ALPHA_MIN: Final[float] = 0.3  # Minimum alpha for spinner dots (not currently used)
LOADING_SPINNER_ALPHA_MAX: Final[float] = 0.7  # Maximum alpha for spinner dots (not currently used)
LOADING_TEXT_VERTICAL_OFFSET: Final[int] = 20  # Vertical offset from center for "Loading..." text (not currently used, text is centered)
LOADING_TEXT_FONT_SIZE: Final[int] = 24  # Font size for "Loading..." text
LOADING_ANIMATION_FRAMES: Final[int] = 60  # Frames per animation cycle (not currently used)
# Loading text is centered at (IMAGE_WIDTH / 2, IMAGE_HEIGHT / 2)

# Text rendering constants
DEFAULT_FONT_SIZE: Final[int] = 24  # Default font size for centered text rendering
LOADING_TEXT_COLOR: Final[tuple[int, int, int, int]] = (255, 255, 255, 255)  # White color for loading text

# Gutter colors (WCAG AA compliant - ensures 3:1 contrast ratio minimum)
# Gutter color automatically switches based on volume bar fill color for visibility
GUTTER_COLOR_DARK: Final[tuple[int, int, int, int]] = (70, 70, 70, 255)  # Dark gutter color (default)
GUTTER_COLOR_LIGHT: Final[tuple[int, int, int, int]] = (180, 180, 180, 255)  # Light gutter color (used when fill is dark)
GUTTER_LUMINANCE_THRESHOLD: Final[float] = 0.1  # Relative luminance threshold for dark color detection
# If fill color luminance < GUTTER_LUMINANCE_THRESHOLD, use light gutter for better contrast

# Volume bar rendering constants
VOLUME_FULL_TOLERANCE: Final[float] = 0.5  # Floating point tolerance for detecting 100% volume
# Used to determine if volume bar should have rounded right end (at 100%) or flat end (< 100%)
VOLUME_PERCENTAGE_MAX: Final[float] = 100.0  # Maximum volume percentage (100%)
# Used in calculations: effective_fill_width = (volume / VOLUME_PERCENTAGE_MAX) * bar_width

# Color calculation constants (standard RGB/alpha values)
RGB_MAX: Final[int] = 255  # Maximum RGB/alpha value (0-255 range)
ALPHA_FULL_OPACITY: Final[int] = 255  # Full opacity alpha value
# Used for color normalization and alpha channel values

# Mathematical constants for radius calculations
RADIUS_DIVISOR: Final[int] = 2  # Used to calculate radius from height/width (radius = dimension / RADIUS_DIVISOR)
GUTTER_MULTIPLIER: Final[int] = 2  # Used to calculate gutter size (gutter extends GUTTER_MULTIPLIER * BAR_GUTTER_SIZE on each side)

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
COLOR_MUTED_FILL: Final[tuple[int, int, int, int]] = (110, 110, 110, 255)
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

