"""Rendering helper functions for PipeWeaver renderers"""
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

# Image rendering constants
# Base image dimensions - defines the canvas size for all rendered images
IMAGE_WIDTH: Final[int] = 480  # Total width of the rendered image in pixels
IMAGE_HEIGHT: Final[int] = 240  # Total height of the rendered image in pixels

# Service unavailable screen layout
# Displayed when PipeWeaver daemon is not running
SERVICE_UNAVAILABLE_TITLE_Y: Final[int] = 60  # Vertical position for "PipeWeaver" title text in pixels
SERVICE_UNAVAILABLE_TITLE_FONT_SIZE: Final[int] = 28  # Font size for title text in points
SERVICE_UNAVAILABLE_SUBTITLE_Y: Final[int] = 100  # Vertical position for "Service Unavailable" subtitle in pixels
SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE: Final[int] = 18  # Font size for subtitle text in points
SERVICE_UNAVAILABLE_HINT_Y: Final[int] = 160  # Vertical position for hint text in pixels
SERVICE_UNAVAILABLE_HINT_FONT_SIZE: Final[int] = 18  # Font size for hint text in points

# Loading screen layout
# Displayed when devices are being loaded
LOADING_TEXT_FONT_SIZE: Final[int] = 24  # Font size for "Loading..." text in points

# Text rendering constants
DEFAULT_FONT_SIZE: Final[int] = 24  # Default font size for centered text rendering in points
LOADING_TEXT_COLOR: Final[tuple[int, int, int, int]] = (255, 255, 255, 255)  # White color (RGBA) for loading text

# Color calculation constants (standard RGB/alpha values)
RGB_MAX: Final[int] = 255  # Maximum RGB/alpha value (0-255 range)
ALPHA_FULL_OPACITY: Final[int] = 255  # Full opacity alpha value
# Used for color normalization and alpha channel values

# Color constants
COLOR_SERVICE_UNAVAILABLE_BG: Final[tuple[int, int, int, int]] = (255, 193, 7, 255)  # Amber/yellow background (RGBA) for service unavailable screen
COLOR_SERVICE_UNAVAILABLE_TEXT: Final[tuple[int, int, int, int]] = (33, 33, 33, 255)  # Dark gray text (RGBA) for service unavailable title
COLOR_SERVICE_UNAVAILABLE_HINT: Final[tuple[int, int, int, int]] = (66, 66, 66, 255)  # Medium gray text (RGBA) for service unavailable hint

# Gutter colors (WCAG AA compliant - ensures 3:1 contrast ratio minimum)
# Gutter color automatically switches based on volume bar fill color for visibility
GUTTER_COLOR_DARK: Final[tuple[int, int, int, int]] = (70, 70, 70, 255)  # Dark gutter color (default) in RGBA
GUTTER_COLOR_LIGHT: Final[tuple[int, int, int, int]] = (180, 180, 180, 255)  # Light gutter color (used when fill is dark) in RGBA
GUTTER_LUMINANCE_THRESHOLD: Final[float] = 0.1  # Relative luminance threshold for dark color detection
# If fill color luminance < GUTTER_LUMINANCE_THRESHOLD, use light gutter for better contrast


def cairo_to_pil(surface: cairo.ImageSurface) -> Image.Image:
    """Convert Cairo surface to PIL Image"""
    buf = surface.get_data()
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    
    # Convert ARGB32 to RGBA
    pil_image = Image.frombuffer(
        "RGBA", (width, height), buf, "raw", "BGRA", stride, 1
    )
    return pil_image


def create_cairo_surface(width: int, height: int) -> tuple[cairo.ImageSurface, cairo.Context]:
    """Create Cairo surface and context"""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    return surface, ctx


def set_cairo_color(ctx: cairo.Context, color: tuple[int, int, int, int]) -> None:
    """Set Cairo color from RGBA tuple (0-255)"""
    r, g, b, a = color
    ctx.set_source_rgba(r / float(RGB_MAX), g / float(RGB_MAX), b / float(RGB_MAX), a / float(RGB_MAX))


def draw_text_centered(ctx: cairo.Context, text: str, x: float, y: float, font_size: float = DEFAULT_FONT_SIZE) -> None:
    """Draw centered text at position"""
    ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(font_size)
    extents = ctx.text_extents(text)
    ctx.move_to(x - extents.width / 2 - extents.x_bearing, y - extents.height / 2 - extents.y_bearing)
    ctx.show_text(text)


def relative_luminance(color: tuple[int, int, int, int]) -> float:
    """Calculate relative luminance according to WCAG 2.1"""
    r, g, b, _ = color
    
    # Normalize RGB values to 0-1 range
    def normalize(val):
        val = val / float(RGB_MAX)
        if val <= 0.03928:
            return val / 12.92
        else:
            return ((val + 0.055) / 1.055) ** 2.4
    
    r_norm = normalize(r)
    g_norm = normalize(g)
    b_norm = normalize(b)
    
    return 0.2126 * r_norm + 0.7152 * g_norm + 0.0722 * b_norm


def get_gutter_color(fill_color: Optional[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """Get appropriate gutter color based on fill color brightness (WCAG AA compliant)"""
    # If no fill color or volume is 0, use default dark gutter
    if not fill_color:
        return GUTTER_COLOR_DARK
    
    # Check if fill color is dark (low luminance)
    # If fill color is dark, use light gutter for visibility
    fill_luminance = relative_luminance(fill_color)
    
    # Use light gutter for dark fill colors
    if fill_luminance < GUTTER_LUMINANCE_THRESHOLD:
        return GUTTER_COLOR_LIGHT
    
    return GUTTER_COLOR_DARK


def render_service_unavailable_full(
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT
) -> Optional[Image.Image]:
    """Render service unavailable screen for full-size images (knob renderer)"""
    try:
        surface, ctx = create_cairo_surface(width, height)
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_BG)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_TEXT)
        draw_text_centered(ctx, "PipeWeaver", width / 2, SERVICE_UNAVAILABLE_TITLE_Y, SERVICE_UNAVAILABLE_TITLE_FONT_SIZE)
        
        draw_text_centered(ctx, "Service Unavailable", width / 2, SERVICE_UNAVAILABLE_SUBTITLE_Y, SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE)
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_HINT)
        draw_text_centered(ctx, "Start PipeWeaver to continue", width / 2, SERVICE_UNAVAILABLE_HINT_Y, SERVICE_UNAVAILABLE_HINT_FONT_SIZE)
        
        return cairo_to_pil(surface)
    except Exception as e:
        log.error(f"Error rendering service unavailable state: {e}")
        return None


def render_service_unavailable_button(button_size: int) -> Optional[Image.Image]:
    """Render service unavailable screen for button-size images (slider/volume button renderers)"""
    try:
        surface, ctx = create_cairo_surface(button_size, button_size)
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_BG)
        ctx.rectangle(0, 0, button_size, button_size)
        ctx.fill()
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_TEXT)
        # Scale font sizes for button
        title_font = max(14, int(SERVICE_UNAVAILABLE_TITLE_FONT_SIZE * button_size / IMAGE_WIDTH))
        subtitle_font = max(10, int(SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE * button_size / IMAGE_WIDTH))
        hint_font = max(10, int(SERVICE_UNAVAILABLE_HINT_FONT_SIZE * button_size / IMAGE_WIDTH))
        
        draw_text_centered(ctx, "PipeWeaver", button_size / 2, button_size * 0.25, title_font)
        draw_text_centered(ctx, "Service", button_size / 2, button_size * 0.42, subtitle_font)
        draw_text_centered(ctx, "Unavailable", button_size / 2, button_size * 0.58, subtitle_font)
        
        set_cairo_color(ctx, COLOR_SERVICE_UNAVAILABLE_HINT)
        draw_text_centered(ctx, "Start PipeWeaver", button_size / 2, button_size * 0.75, hint_font)
        
        return cairo_to_pil(surface)
    except Exception as e:
        log.error(f"Error rendering service unavailable state: {e}")
        return None


def render_loading_full(
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT
) -> Optional[Image.Image]:
    """Render loading screen for full-size images (knob renderer)"""
    try:
        surface, ctx = create_cairo_surface(width, height)
        
        center_x, center_y = width / 2, height / 2
        
        set_cairo_color(ctx, LOADING_TEXT_COLOR)
        draw_text_centered(ctx, "Loading...", center_x, center_y, LOADING_TEXT_FONT_SIZE)
        
        return cairo_to_pil(surface)
    except Exception as e:
        log.error(f"Error rendering loading state: {e}")
        return None


def render_loading_button(button_size: int) -> Optional[Image.Image]:
    """Render loading screen for button-size images (slider/volume button renderers)"""
    try:
        surface, ctx = create_cairo_surface(button_size, button_size)
        
        center_x, center_y = button_size / 2, button_size / 2
        
        set_cairo_color(ctx, LOADING_TEXT_COLOR)
        font_size = max(12, int(LOADING_TEXT_FONT_SIZE * button_size / IMAGE_WIDTH))
        draw_text_centered(ctx, "Loading...", center_x, center_y, font_size)
        
        return cairo_to_pil(surface)
    except Exception as e:
        log.error(f"Error rendering loading state: {e}")
        return None


def get_button_size_from_action(action) -> int:
    """Get the actual button size from the action, default to 72 for standard buttons"""
    try:
        button = action.get_input()
        if button and hasattr(button, 'get_size'):
            size = button.get_size()
            if size and len(size) >= 2:
                # Buttons are square, use the smaller dimension or average
                return min(size[0], size[1]) if size[0] != size[1] else size[0]
        # Try to get from action if available
        if hasattr(action, 'button_size'):
            return action.button_size
        if hasattr(action, 'get_button_size'):
            return action.get_button_size()
    except Exception:
        pass
    # Default to 72x72 for standard Stream Deck buttons
    return 72


def set_image_on_action(action, image: Image.Image) -> None:
    """Set image on action and update button/dial"""
    try:
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        materialized_image = image.copy()
        materialized_image.load()
        
        action.set_media(image=materialized_image, update=True)
        
        input_device = action.get_input()
        if input_device:
            input_device.update()
    except Exception as e:
        log.error(f"Error setting image: {e}")
