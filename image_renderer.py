"""Image rendering utilities for PipeWeaver actions"""
import math
from typing import Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .constants import (
    BAR_GUTTER_SIZE,
    BAR_HEIGHT,
    BAR_HORIZONTAL_OFFSET,
    BAR_RADIUS,
    BAR_VERTICAL_OFFSET,
    COLOR_METER,
    COLOR_MUTED_FILL,
    COLOR_SERVICE_UNAVAILABLE_BG,
    COLOR_SERVICE_UNAVAILABLE_HINT,
    COLOR_SERVICE_UNAVAILABLE_TEXT,
    COLOR_SOURCE_FILL,
    COLOR_TARGET_FILL,
    CORNER_INSET,
    DEFAULT_FONT_SIZE,
    DEVICE_TYPE_SOURCE,
    EDGE_PADDING,
    GUTTER_COLOR_DARK,
    GUTTER_COLOR_LIGHT,
    GUTTER_LUMINANCE_THRESHOLD,
    ICON_MAX_SIZE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    LOADING_TEXT_COLOR,
    LOADING_TEXT_FONT_SIZE,
    METER_HEIGHT,
    METER_HORIZONTAL_MARGIN,
    RADIUS_DIVISOR,
    RGB_MAX,
    ALPHA_FULL_OPACITY,
    GUTTER_MULTIPLIER,
    SERVICE_UNAVAILABLE_HINT_FONT_SIZE,
    SERVICE_UNAVAILABLE_HINT_Y,
    SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE,
    SERVICE_UNAVAILABLE_SUBTITLE_Y,
    SERVICE_UNAVAILABLE_TITLE_FONT_SIZE,
    SERVICE_UNAVAILABLE_TITLE_Y,
    VOLUME_FULL_TOLERANCE,
    VOLUME_PERCENTAGE_MAX,
)
from .service_monitor import is_service_available


class ImageRenderer:
    def __init__(self, action):
        self.action = action
    
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
            is_muted = self.action._is_muted
            if self.action.selected_device_type == DEVICE_TYPE_SOURCE:
                image = self._render_source_device(is_muted)
            else:
                image = self._render_target_device(is_muted)
            
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
            log.error(f"Error drawing volume bars: {e}")
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
    
    def _relative_luminance(self, color: tuple[int, int, int, int]) -> float:
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
    
    def _contrast_ratio(self, color1: tuple[int, int, int, int], color2: tuple[int, int, int, int]) -> float:
        """Calculate contrast ratio between two colors according to WCAG 2.1"""
        lum1 = self._relative_luminance(color1)
        lum2 = self._relative_luminance(color2)
        
        # Ensure lighter color is in numerator
        lighter = max(lum1, lum2)
        darker = min(lum1, lum2)
        
        if darker == 0:
            return float('inf')
        
        return (lighter + 0.05) / (darker + 0.05)
    
    def _get_gutter_color(self, fill_color: Optional[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        """Get appropriate gutter color based on fill color brightness (WCAG AA compliant)"""
        # If no fill color or volume is 0, use default dark gutter
        if not fill_color:
            return GUTTER_COLOR_DARK
        
        # Check if fill color is dark (low luminance)
        # If fill color is dark, use light gutter for visibility
        fill_luminance = self._relative_luminance(fill_color)
        
        # Use light gutter for dark fill colors
        if fill_luminance < GUTTER_LUMINANCE_THRESHOLD:
            return GUTTER_COLOR_LIGHT
        
        return GUTTER_COLOR_DARK
    
    def _draw_text_centered(self, ctx: cairo.Context, text: str, x: float, y: float, font_size: float = DEFAULT_FONT_SIZE):
        """Draw centered text at position"""
        ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(font_size)
        extents = ctx.text_extents(text)
        ctx.move_to(x - extents.width / 2 - extents.x_bearing, y - extents.height / 2 - extents.y_bearing)
        ctx.show_text(text)
    
    def _render_service_unavailable(self) -> Optional[Image.Image]:
        try:
            surface, ctx = self._create_cairo_surface(IMAGE_WIDTH, IMAGE_HEIGHT)
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_BG)
            ctx.rectangle(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT)
            ctx.fill()
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_TEXT)
            self._draw_text_centered(ctx, "PipeWeaver", IMAGE_WIDTH / 2, SERVICE_UNAVAILABLE_TITLE_Y, SERVICE_UNAVAILABLE_TITLE_FONT_SIZE)
            
            self._draw_text_centered(ctx, "Service Unavailable", IMAGE_WIDTH / 2, SERVICE_UNAVAILABLE_SUBTITLE_Y, SERVICE_UNAVAILABLE_SUBTITLE_FONT_SIZE)
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_HINT)
            self._draw_text_centered(ctx, "Start PipeWeaver to continue", IMAGE_WIDTH / 2, SERVICE_UNAVAILABLE_HINT_Y, SERVICE_UNAVAILABLE_HINT_FONT_SIZE)
            
            return self._cairo_to_pil(surface)
        except Exception as e:
            log.error(f"Error rendering service unavailable state: {e}")
            return None
    
    def _render_loading(self) -> Optional[Image.Image]:
        try:
            surface, ctx = self._create_cairo_surface(IMAGE_WIDTH, IMAGE_HEIGHT)
            
            center_x, center_y = IMAGE_WIDTH / 2, IMAGE_HEIGHT / 2
            
            self._set_color(ctx, LOADING_TEXT_COLOR)
            self._draw_text_centered(ctx, "Loading...", center_x, center_y, LOADING_TEXT_FONT_SIZE)
            
            return self._cairo_to_pil(surface)
        except Exception as e:
            log.error(f"Error rendering loading state: {e}")
            return None
    
    def _get_layout_constants(self) -> dict[str, int]:
        icon_left_x = CORNER_INSET
        icon_bottom_y = IMAGE_HEIGHT - ICON_MAX_SIZE - CORNER_INSET
        
        left_margin = icon_left_x + ICON_MAX_SIZE + EDGE_PADDING
        right_margin = CORNER_INSET
        bar_width = IMAGE_WIDTH - left_margin - right_margin
        bar_y = IMAGE_HEIGHT - BAR_HEIGHT - CORNER_INSET - BAR_VERTICAL_OFFSET
        
        # Bar position (volume bar inside gutter)
        bar_x = left_margin + BAR_HORIZONTAL_OFFSET
        
        # Gutter dimensions (larger than bar to create border effect)
        gutter_x = bar_x - BAR_GUTTER_SIZE
        gutter_y = bar_y - BAR_GUTTER_SIZE
        gutter_width = bar_width + (BAR_GUTTER_SIZE * GUTTER_MULTIPLIER)
        gutter_height = BAR_HEIGHT + (BAR_GUTTER_SIZE * GUTTER_MULTIPLIER)
        gutter_radius = (BAR_HEIGHT / RADIUS_DIVISOR) + BAR_GUTTER_SIZE
        
        return {
            'image_width': IMAGE_WIDTH,
            'image_height': IMAGE_HEIGHT,
            'edge_padding': EDGE_PADDING,
            'corner_inset': CORNER_INSET,
            'icon_max_size': ICON_MAX_SIZE,
            'icon_bottom_y': icon_bottom_y,
            'icon_left_x': icon_left_x,
            'left_margin': left_margin,
            'bar_width': bar_width,
            'bar_height': BAR_HEIGHT,
            'bar_x': bar_x,
            'bar_y': bar_y,
            'bar_radius': BAR_HEIGHT / RADIUS_DIVISOR,
            'gutter_x': gutter_x,
            'gutter_y': gutter_y,
            'gutter_width': gutter_width,
            'gutter_height': gutter_height,
            'gutter_radius': gutter_radius,
        }
    
    def _render_device(self, is_muted: bool = False) -> Optional[Image.Image]:
        """Unified rendering for both source and target devices."""
        volume = self.action.volume or 0
        device_color = self.action._device_color or {}
        is_source = self.action.selected_device_type == DEVICE_TYPE_SOURCE
        
        try:
            layout = self._get_layout_constants()
            surface, ctx = self._create_cairo_surface(layout['image_width'], layout['image_height'])
            
            # All dimensions come from layout constants (fully parametric)
            bar_x = layout['bar_x']
            bar_y = layout['bar_y']
            bar_width = layout['bar_width']
            bar_height = layout['bar_height']
            bar_radius = layout['bar_radius']
            
            gutter_x = layout['gutter_x']
            gutter_y = layout['gutter_y']
            gutter_width = layout['gutter_width']
            gutter_height = layout['gutter_height']
            gutter_radius = layout['gutter_radius']

            effective_fill_width = (volume / VOLUME_PERCENTAGE_MAX) * bar_width
            
            # Determine fill color first (needed for WCAG contrast check)
            fill_color = None
            if effective_fill_width > 0:
                if is_muted:
                    fill_color = COLOR_MUTED_FILL
                else:
                    volume_bar_color = self.action._volume_bar_color
                    if volume_bar_color:
                        fill_color = volume_bar_color
                    elif device_color:
                        fill_color = (device_color.get('red', 0), device_color.get('green', 0), 
                                      device_color.get('blue', 0), ALPHA_FULL_OPACITY)
                    else:
                        fill_color = COLOR_SOURCE_FILL if is_source else COLOR_TARGET_FILL
            
            # Get appropriate gutter color based on fill color contrast (WCAG compliant)
            gutter_bg = self._get_gutter_color(fill_color)
            
            # Draw gutter (larger, creating border effect)
            self._set_color(ctx, gutter_bg)
            self._draw_rounded_rect(ctx, gutter_x, gutter_y, gutter_width, gutter_height, gutter_radius)
            ctx.fill()

            # Draw fill if there's volume
            if effective_fill_width > 0 and fill_color:
                self._set_color(ctx, fill_color)
                # Draw volume bar: both ends always semi-circles
                self._draw_rounded_rect(ctx, bar_x, bar_y, effective_fill_width, bar_height, bar_radius, right_end_flat=False)
                ctx.fill()
            
            meter_value = self.action._current_meter_a if is_source else self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and effective_fill_width > 0 and fill_color:
                meter_y = bar_y + (bar_height - METER_HEIGHT) / RADIUS_DIVISOR
                volume_color_for_invert = fill_color
                self._draw_animated_meter(
                    ctx, meter_value, int(effective_fill_width), int(bar_x), 
                    int(effective_fill_width), int(meter_y), METER_HEIGHT, int(bar_radius), volume_color_for_invert
                )
            
            image = self._cairo_to_pil(surface)
            self._composite_icon(image, layout['icon_left_x'], layout['icon_bottom_y'], layout['icon_max_size'])
            return image
        except Exception as img_e:
            log.error(f"Error creating device image: {img_e}")
            return None
    
    def _render_source_device(self, is_muted: bool = False) -> Optional[Image.Image]:
        return self._render_device(is_muted)
    
    def _render_target_device(self, muted: bool = False) -> Optional[Image.Image]:
        return self._render_device(muted)
    
    def _draw_rounded_rect(
        self,
        ctx: cairo.Context,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
        right_end_flat: bool = False
    ) -> None:
        """Draw rounded rectangle with optional flat right end"""
        if width <= 0 or height <= 0:
            return
        
        # Left end should ALWAYS be a semi-circle with full radius (or height/RADIUS_DIVISOR if smaller)
        left_radius = min(radius, height / RADIUS_DIVISOR)
        
        # Right end radius depends on width
        max_radius = min(width, height) / RADIUS_DIVISOR
        right_radius = min(radius, max_radius) if not right_end_flat else 0
        
        if left_radius <= 0:
            ctx.rectangle(x, y, width, height)
            return
        
        ctx.new_sub_path()
        
        # Left end: ALWAYS draw as a semi-circle with left_radius
        # Start at the leftmost point of the top-left semi-circle
        ctx.move_to(x, y + left_radius)
        
        # Draw top-left semi-circle: arc from left (π) to top (3π/2)
        ctx.arc(x + left_radius, y + left_radius, left_radius, math.pi, 3 * math.pi / 2)
        
        # Top edge - go to right side
        if right_end_flat or width < (left_radius * GUTTER_MULTIPLIER):
            # Flat right end - go straight to top-right corner
            ctx.line_to(x + width, y)
        else:
            # Rounded right end - go to start of top-right arc
            ctx.line_to(x + width - right_radius, y)
            ctx.arc(x + width - right_radius, y + right_radius, right_radius, -math.pi / 2, 0)
        
        # Right edge
        if right_end_flat or width < (left_radius * GUTTER_MULTIPLIER):
            # Flat right end - straight down
            ctx.line_to(x + width, y + height)
        else:
            # Rounded right end - continue to bottom-right arc
            ctx.arc(x + width - right_radius, y + height - right_radius, right_radius, 0, math.pi / 2)
        
        # Bottom edge - go back to left side
        ctx.line_to(x + left_radius, y + height)
        
        # Left end: bottom-left semi-circle (ALWAYS drawn as semi-circle with left_radius)
        # Draw from bottom (π/2) to left (π)
        ctx.arc(x + left_radius, y + height - left_radius, left_radius, math.pi / 2, math.pi)
        
        ctx.close_path()
    
    def _draw_animated_meter(
        self,
        ctx: cairo.Context,
        meter_value: int,
        fill_width: int,
        start_x: int,
        bar_width: int,
        meter_y: int,
        meter_height: int,
        radius: int,
        volume_color: tuple[int, int, int, int]
    ) -> None:
        if meter_value <= 0 or fill_width <= 0:
            return

        # Calculate meter width with margins
        available_width = fill_width - (METER_HORIZONTAL_MARGIN * GUTTER_MULTIPLIER)
        if available_width <= 0:
            return
            
        base_meter_width = int((meter_value / VOLUME_PERCENTAGE_MAX) * available_width)
        meter_x1 = start_x + METER_HORIZONTAL_MARGIN
        meter_x2 = meter_x1 + base_meter_width

        if meter_x2 <= meter_x1 or meter_y < 0:
            return

        meter_width = meter_x2 - meter_x1
        meter_radius = min(meter_height / RADIUS_DIVISOR, BAR_RADIUS)
        
        if getattr(self.action, "_meter_invert_color", True):
            r, g, b, a = volume_color
            meter_color = (RGB_MAX - r, RGB_MAX - g, RGB_MAX - b, a)
        else:
            meter_color = self.action._meter_color or COLOR_METER
        
        # Draw meter with rounded ends (no antialiasing for solid color)
        ctx.set_antialias(cairo.ANTIALIAS_NONE)  # Disable antialiasing for crisp, solid color
        self._draw_rounded_rect(ctx, meter_x1, meter_y, meter_width, meter_height, meter_radius, right_end_flat=False)
        self._set_color(ctx, meter_color)
        ctx.set_line_width(0)  # Ensure no border/shadow
        ctx.fill()
        ctx.set_antialias(cairo.ANTIALIAS_DEFAULT)  # Restore default antialiasing

    def _composite_icon(
        self,
        image: Image.Image,
        icon_left_x: int,
        icon_bottom_y: int,
        icon_max_size: int
    ) -> None:
        try:
            icon = self.action._get_icon()
            if icon and isinstance(icon, Image.Image):
                icon_w, icon_h = icon.size
                scale = min(icon_max_size / icon_w, icon_max_size / icon_h, 1.0)
                icon_size = (int(icon_w * scale), int(icon_h * scale))
                icon_resized = icon.resize(icon_size, Image.Resampling.LANCZOS)
                if icon_resized.mode != 'RGBA':
                    icon_resized = icon_resized.convert('RGBA')

                final_icon_bottom_y = icon_bottom_y + (icon_max_size - icon_size[1])
                final_icon_left_x = icon_left_x + (icon_max_size - icon_size[0]) // 2
                
                image.paste(icon_resized, (final_icon_left_x, final_icon_bottom_y), icon_resized)
        except Exception as e:
            log.warning(f"Error compositing icon: {e}")
    
    def _set_image_on_action(self, image: Image.Image) -> None:
        try:
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            
            materialized_image = image.copy()
            materialized_image.load()
            
            self.action.set_media(image=materialized_image, update=True)
            
            dial = self.action.get_input()
            if dial:
                dial.update()
        except Exception as e:
            log.error(f"Error setting image: {e}")
