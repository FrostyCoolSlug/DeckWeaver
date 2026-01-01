"""Knob-specific image rendering for PipeWeaver actions"""
import math
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .render_helpers import (
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    RGB_MAX,
    ALPHA_FULL_OPACITY,
    GUTTER_COLOR_DARK,
    GUTTER_COLOR_LIGHT,
    GUTTER_LUMINANCE_THRESHOLD,
    create_cairo_surface,
    cairo_to_pil,
    set_cairo_color,
    draw_text_centered,
    get_gutter_color,
    render_service_unavailable_full,
    render_loading_full,
    set_image_on_action,
)
from .service_monitor import is_service_available

# Layout spacing constants
# General edge padding between icon and volume bar
EDGE_PADDING: Final[int] = 20  # Horizontal spacing between icon and volume bar in pixels
# Extra inset from corners for rounded corner elements (icon, bar positioning)
CORNER_INSET: Final[int] = 28  # Distance from edges for corner-positioned elements in pixels

# Icon layout constants
ICON_MAX_SIZE: Final[int] = 105  # Maximum size (width/height) for the device icon in pixels

# Volume bar constants
BAR_HEIGHT: Final[int] = 32  # Height of the volume bar (not including gutter) in pixels
BAR_RADIUS: Final[int] = 6  # Corner radius for volume bar rounded ends in pixels
BAR_GUTTER_SIZE: Final[int] = 6  # Size of gutter border around volume bar (creates border effect) in pixels
BAR_HORIZONTAL_OFFSET: Final[int] = 0  # Horizontal offset for bar position from calculated left margin in pixels
BAR_VERTICAL_OFFSET: Final[int] = 10  # Vertical offset from bottom edge for bar position in pixels

# Meter constants
# Meter (audio level indicator) constants - drawn inside volume bar
METER_HEIGHT: Final[int] = 10  # Height of the meter bar in pixels
METER_HORIZONTAL_MARGIN: Final[int] = 10  # Horizontal margin from volume bar edges (left and right) in pixels

# Volume bar rendering constants
VOLUME_FULL_TOLERANCE: Final[float] = 0.5  # Floating point tolerance for detecting 100% volume
# Used to determine if volume bar should have rounded right end (at 100%) or flat end (< 100%)
VOLUME_PERCENTAGE_MAX: Final[float] = 100.0  # Maximum volume percentage (100%)
# Used in calculations: effective_fill_width = (volume / VOLUME_PERCENTAGE_MAX) * bar_width

# Mathematical constants for radius calculations
RADIUS_DIVISOR: Final[int] = 2  # Used to calculate radius from height/width (radius = dimension / RADIUS_DIVISOR)
GUTTER_MULTIPLIER: Final[int] = 2  # Used to calculate gutter size (gutter extends GUTTER_MULTIPLIER * BAR_GUTTER_SIZE on each side)

# Color constants
COLOR_MUTED_FILL: Final[tuple[int, int, int, int]] = (110, 110, 110, 255)  # Gray color (RGBA) for muted volume bar fill
COLOR_TARGET_FILL: Final[tuple[int, int, int, int]] = (102, 255, 102, 255)  # Green color (RGBA) for target device volume bar fill
COLOR_SOURCE_FILL: Final[tuple[int, int, int, int]] = (102, 179, 255, 255)  # Blue color (RGBA) for source device volume bar fill
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)  # Black color (RGBA) for audio level meter

# Device types
DEVICE_TYPE_SOURCE: Final[str] = "source"  # Device type identifier for input/source devices


class KnobRenderer:
    def __init__(self, action):
        self.action = action
    
    def render_image(self):
        if not is_service_available():
            try:
                image = render_service_unavailable_full()
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
            return
        
        if getattr(self.action, '_is_loading_devices', False):
            try:
                image = render_loading_full()
                if image:
                    set_image_on_action(self.action, image)
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
                set_image_on_action(self.action, image)
            else:
                try:
                    fallback_image = render_service_unavailable_full()
                    if fallback_image:
                        set_image_on_action(self.action, fallback_image)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Error drawing volume bars: {e}")
            try:
                fallback_image = render_service_unavailable_full()
                if fallback_image:
                    set_image_on_action(self.action, fallback_image)
            except Exception:
                pass
    
    
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
            surface, ctx = create_cairo_surface(layout['image_width'], layout['image_height'])
            
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
            gutter_bg = get_gutter_color(fill_color)
            
            # Draw gutter (larger, creating border effect)
            set_cairo_color(ctx, gutter_bg)
            self._draw_rounded_rect(ctx, gutter_x, gutter_y, gutter_width, gutter_height, gutter_radius)
            ctx.fill()

            # Draw fill if there's volume
            if effective_fill_width > 0 and fill_color:
                set_cairo_color(ctx, fill_color)
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
            
            image = cairo_to_pil(surface)
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
        set_cairo_color(ctx, meter_color)
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
    
