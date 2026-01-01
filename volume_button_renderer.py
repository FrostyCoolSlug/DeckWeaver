"""Volume button rendering for PipeWeaver vol+ and vol- buttons"""
import math
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .service_monitor import is_service_available

# Image rendering constants
# Base image dimensions - defines the canvas size for all rendered images
IMAGE_WIDTH: Final[int] = 480  # Total width of the rendered image in pixels
IMAGE_HEIGHT: Final[int] = 240  # Total height of the rendered image in pixels

# Layout spacing constants
# Extra inset from corners for rounded corner elements
CORNER_INSET: Final[int] = 28  # Distance from edges for corner-positioned elements in pixels

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
# Used for color normalization and alpha channel values

# Color constants
COLOR_SERVICE_UNAVAILABLE_BG: Final[tuple[int, int, int, int]] = (255, 193, 7, 255)  # Amber/yellow background (RGBA) for service unavailable screen
COLOR_SERVICE_UNAVAILABLE_TEXT: Final[tuple[int, int, int, int]] = (33, 33, 33, 255)  # Dark gray text (RGBA) for service unavailable title
COLOR_SERVICE_UNAVAILABLE_HINT: Final[tuple[int, int, int, int]] = (66, 66, 66, 255)  # Medium gray text (RGBA) for service unavailable hint

# Button symbol constants (as ratios of button size)
# These ratios are multiplied by the button size to calculate actual dimensions
LARGE_SYMBOL_SIZE_RATIO: Final[float] = 0.5  # 50% of button size for default large plus/minus symbol
LARGE_SYMBOL_LINE_WIDTH_RATIO: Final[float] = 0.13  # 13% of button size for large symbol line width
SMALL_SYMBOL_SIZE_RATIO: Final[float] = 0.12  # 12% of button size for corner plus/minus symbol (when custom icon exists)
SMALL_SYMBOL_LINE_WIDTH_RATIO: Final[float] = 0.04  # 4% of button size for corner symbol line width
CORNER_SYMBOL_INSET_RATIO: Final[float] = 0.08  # 8% of button size for corner symbol inset from edge
CUSTOM_ICON_INSET_RATIO: Final[float] = 0.25  # 25% of button size for custom icon inset (leaves room for corner symbol)
MIN_LINE_WIDTH: Final[int] = 2  # Minimum line width in pixels (ensures symbol is visible on small buttons)
MIN_CORNER_INSET: Final[int] = 4  # Minimum corner inset in pixels (ensures symbol doesn't touch edge)


class VolumeButtonRenderer:
    def __init__(self, action, is_plus: bool):
        self.action = action
        self.is_plus = is_plus  # True for vol+, False for vol-
        # Get button size - buttons are square, default to 72x72 for standard buttons
        self.button_size = self._get_button_size()
    
    def render_image(self):
        if not is_service_available():
            try:
                image = self._render_service_unavailable()
                if image:
                    self._set_image_on_action(image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
            return
        
        if getattr(self.action, '_is_loading_devices', False):
            try:
                image = self._render_loading()
                if image:
                    self._set_image_on_action(image)
            except Exception as e:
                log.error(f"Error rendering loading state: {e}")
            return
        
        if not self.action.selected_device_name:
            return
        
        try:
            image = self._render_button()
            if image:
                self._set_image_on_action(image)
            else:
                try:
                    fallback_image = self._render_service_unavailable()
                    if fallback_image:
                        self._set_image_on_action(fallback_image)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Error drawing button: {e}")
            try:
                fallback_image = self._render_service_unavailable()
                if fallback_image:
                    self._set_image_on_action(fallback_image)
            except Exception:
                pass
    
    def _cairo_to_pil(self, surface: cairo.ImageSurface) -> Image.Image:
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
    
    def _create_cairo_surface(self, width: int, height: int) -> tuple[cairo.ImageSurface, cairo.Context]:
        """Create Cairo surface and context"""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        return surface, ctx
    
    def _set_color(self, ctx: cairo.Context, color: tuple[int, int, int, int]):
        """Set Cairo color from RGBA tuple (0-255)"""
        r, g, b, a = color
        ctx.set_source_rgba(r / float(RGB_MAX), g / float(RGB_MAX), b / float(RGB_MAX), a / float(RGB_MAX))
    
    def _draw_text_centered(self, ctx: cairo.Context, text: str, x: float, y: float, font_size: float = DEFAULT_FONT_SIZE):
        """Draw centered text at position"""
        ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(font_size)
        extents = ctx.text_extents(text)
        ctx.move_to(x - extents.width / 2 - extents.x_bearing, y - extents.height / 2 - extents.y_bearing)
        ctx.show_text(text)
    
    def _render_service_unavailable(self) -> Optional[Image.Image]:
        try:
            size = self.button_size
            surface, ctx = self._create_cairo_surface(size, size)
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_BG)
            ctx.rectangle(0, 0, size, size)
            ctx.fill()
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_TEXT)
            # Scale font sizes for button
            title_font = max(14, int(SERVICE_UNAVAILABLE_TITLE_FONT_SIZE * size / IMAGE_WIDTH))
            subtitle_font = max(10, int(SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE * size / IMAGE_WIDTH))
            hint_font = max(10, int(SERVICE_UNAVAILABLE_HINT_FONT_SIZE * size / IMAGE_WIDTH))
            
            self._draw_text_centered(ctx, "PipeWeaver", size / 2, size * 0.25, title_font)
            self._draw_text_centered(ctx, "Service", size / 2, size * 0.42, subtitle_font)
            self._draw_text_centered(ctx, "Unavailable", size / 2, size * 0.58, subtitle_font)
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_HINT)
            self._draw_text_centered(ctx, "Start PipeWeaver", size / 2, size * 0.75, hint_font)
            
            return self._cairo_to_pil(surface)
        except Exception as e:
            log.error(f"Error rendering service unavailable state: {e}")
            return None
    
    def _render_loading(self) -> Optional[Image.Image]:
        try:
            size = self.button_size
            surface, ctx = self._create_cairo_surface(size, size)
            
            center_x, center_y = size / 2, size / 2
            
            self._set_color(ctx, LOADING_TEXT_COLOR)
            font_size = max(12, int(LOADING_TEXT_FONT_SIZE * size / IMAGE_WIDTH))
            self._draw_text_centered(ctx, "Loading...", center_x, center_y, font_size)
            
            return self._cairo_to_pil(surface)
        except Exception as e:
            log.error(f"Error rendering loading state: {e}")
            return None
    
    def _draw_plus_symbol(self, ctx: cairo.Context, center_x: float, center_y: float, size: float, line_width: float):
        """Draw a plus (+) symbol"""
        # Horizontal line
        ctx.move_to(center_x - size / 2, center_y)
        ctx.line_to(center_x + size / 2, center_y)
        # Vertical line
        ctx.move_to(center_x, center_y - size / 2)
        ctx.line_to(center_x, center_y + size / 2)
        ctx.set_line_width(line_width)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    
    def _draw_minus_symbol(self, ctx: cairo.Context, center_x: float, center_y: float, size: float, line_width: float):
        """Draw a minus (-) symbol"""
        # Horizontal line only
        ctx.move_to(center_x - size / 2, center_y)
        ctx.line_to(center_x + size / 2, center_y)
        ctx.set_line_width(line_width)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    
    def _get_layout_constants(self) -> dict[str, float]:
        """Get all layout constants calculated from button size (fully parametric)"""
        size = self.button_size
        
        # Center position
        center_x = size / 2
        center_y = size / 2
        
        # Large symbol (default, no custom icon)
        large_symbol_size = size * LARGE_SYMBOL_SIZE_RATIO
        large_symbol_line_width = max(3, int(size * LARGE_SYMBOL_LINE_WIDTH_RATIO))
        
        # Small symbol (when custom icon exists)
        small_symbol_size = size * SMALL_SYMBOL_SIZE_RATIO
        small_symbol_line_width = max(MIN_LINE_WIDTH, int(size * SMALL_SYMBOL_LINE_WIDTH_RATIO))
        corner_inset = max(MIN_CORNER_INSET, int(size * CORNER_SYMBOL_INSET_RATIO))
        corner_x = size - corner_inset - small_symbol_size / 2
        corner_y = size - corner_inset - small_symbol_size / 2
        
        # Custom icon layout
        custom_icon_inset = max(MIN_CORNER_INSET, int(size * CUSTOM_ICON_INSET_RATIO))
        max_icon_size = size - (custom_icon_inset * 2)
        
        return {
            'button_size': size,
            'center_x': center_x,
            'center_y': center_y,
            'large_symbol_size': large_symbol_size,
            'large_symbol_line_width': large_symbol_line_width,
            'small_symbol_size': small_symbol_size,
            'small_symbol_line_width': small_symbol_line_width,
            'corner_inset': corner_inset,
            'corner_x': corner_x,
            'corner_y': corner_y,
            'custom_icon_inset': custom_icon_inset,
            'max_icon_size': max_icon_size,
        }
    
    def _render_button(self) -> Optional[Image.Image]:
        """Render the volume button with plus/minus symbol"""
        try:
            layout = self._get_layout_constants()
            size = int(layout['button_size'])
            surface, ctx = self._create_cairo_surface(size, size)
            
            # Black background
            self._set_color(ctx, (0, 0, 0, 255))
            ctx.rectangle(0, 0, size, size)
            ctx.fill()
            
            # Check if custom icon exists
            custom_icon = self.action._get_icon()
            has_custom_icon = custom_icon is not None and isinstance(custom_icon, Image.Image)
            
            # Draw plus/minus symbol using layout constants
            self._set_color(ctx, (255, 255, 255, 255))
            
            if has_custom_icon:
                # If custom icon exists, draw small plus/minus in bottom corner
                if self.is_plus:
                    self._draw_plus_symbol(
                        ctx, 
                        layout['corner_x'], 
                        layout['corner_y'], 
                        layout['small_symbol_size'], 
                        layout['small_symbol_line_width']
                    )
                else:
                    self._draw_minus_symbol(
                        ctx, 
                        layout['corner_x'], 
                        layout['corner_y'], 
                        layout['small_symbol_size'], 
                        layout['small_symbol_line_width']
                    )
            else:
                # Default: large centered plus/minus
                if self.is_plus:
                    self._draw_plus_symbol(
                        ctx, 
                        layout['center_x'], 
                        layout['center_y'], 
                        layout['large_symbol_size'], 
                        layout['large_symbol_line_width']
                    )
                else:
                    self._draw_minus_symbol(
                        ctx, 
                        layout['center_x'], 
                        layout['center_y'], 
                        layout['large_symbol_size'], 
                        layout['large_symbol_line_width']
                    )
            
            # Composite custom icon if it exists
            image = self._cairo_to_pil(surface)
            if has_custom_icon:
                image = self._composite_icon(image, custom_icon, layout)
            
            return image
        except Exception as e:
            log.error(f"Error creating button image: {e}")
            return None
    
    def _composite_icon(self, image: Image.Image, icon: Image.Image, layout: dict[str, float]) -> Image.Image:
        """Composite custom icon onto the button image"""
        try:
            size = int(layout['button_size'])
            max_icon_size = layout['max_icon_size']
            
            icon_w, icon_h = icon.size
            scale = min(max_icon_size / icon_w, max_icon_size / icon_h, 1.0)
            icon_size = (int(icon_w * scale), int(icon_h * scale))
            
            # Use high-quality LANCZOS resampling for best quality when scaling
            icon_resized = icon.resize(icon_size, Image.Resampling.LANCZOS)
            
            if icon_resized.mode != 'RGBA':
                icon_resized = icon_resized.convert('RGBA')
            
            # Center the icon
            icon_x = (size - icon_size[0]) // 2
            icon_y = (size - icon_size[1]) // 2
            
            # Use alpha composite for smooth blending
            temp_image = Image.new('RGBA', image.size, (0, 0, 0, 0))
            temp_image.paste(icon_resized, (icon_x, icon_y), icon_resized)
            return Image.alpha_composite(image, temp_image)
        except Exception as e:
            log.warning(f"Error compositing icon: {e}")
            return image
    
    def _get_button_size(self) -> int:
        """Get the actual button size from the action, default to 72 for standard buttons"""
        try:
            button = self.action.get_input()
            if button and hasattr(button, 'get_size'):
                size = button.get_size()
                if size and len(size) >= 2:
                    # Buttons are square, use the smaller dimension or average
                    return min(size[0], size[1]) if size[0] != size[1] else size[0]
            # Try to get from action if available
            if hasattr(self.action, 'button_size'):
                return self.action.button_size
            if hasattr(self.action, 'get_button_size'):
                return self.action.get_button_size()
        except Exception:
            pass
        # Default to 72x72 for standard Stream Deck buttons
        return 72
    
    def _set_image_on_action(self, image: Image.Image) -> None:
        try:
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            
            materialized_image = image.copy()
            materialized_image.load()
            
            self.action.set_media(image=materialized_image, update=True)
            
            button = self.action.get_input()
            if button:
                button.update()
        except Exception as e:
            log.error(f"Error setting image: {e}")
