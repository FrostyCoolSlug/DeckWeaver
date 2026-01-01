"""Slider button rendering for PipeWeaver - creates illusion of single slider across 2 buttons"""
import math
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .render_helpers import (
    IMAGE_WIDTH,
    RGB_MAX,
    ALPHA_FULL_OPACITY,
    create_cairo_surface,
    cairo_to_pil,
    set_cairo_color,
    draw_text_centered,
    get_gutter_color,
    render_service_unavailable_button,
    render_loading_button,
    get_button_size_from_action,
    set_image_on_action,
)
from .service_monitor import is_service_available

# ============================================================================
# SLIDER BUTTON RENDERER CONSTANTS - SUPER PARAMETRIC, EASY TO EDIT
# ============================================================================
# All dimensions are in pixels. Change these values to adjust appearance.
# Everything is calculated from these constants - no magic numbers!

# Base dimensions
BUTTON_SIZE: Final[int] = 72  # Standard Stream Deck button size in pixels
DOUBLE_HEIGHT: Final[int] = 144  # Double height for continuous slider (2 buttons) = BUTTON_SIZE * 2

# Layout spacing - adjust these to change margins and positioning
CORNER_INSET: Final[int] = 10  # Distance from button edges for slider positioning in pixels
BAR_HORIZONTAL_OFFSET: Final[int] = 0  # Horizontal offset for bar position from center in pixels (0 = perfectly centered)
BAR_VERTICAL_OFFSET: Final[int] = 3  # Vertical offset from top edge for bar position in pixels

# Volume bar dimensions - change these to make slider thicker/thinner
BAR_WIDTH: Final[int] = 12  # Width of the volume bar (not including gutter) in pixels
BAR_RADIUS: Final[int] = 6  # Corner radius for volume bar rounded ends in pixels (should be <= BAR_WIDTH / 2)

# Gutter dimensions - change these to adjust the border around the slider
BAR_GUTTER_SIZE: Final[int] = 3  # Size of gutter border around volume bar in pixels (creates border effect)
GUTTER_MULTIPLIER: Final[int] = 2  # Gutter extends GUTTER_MULTIPLIER * BAR_GUTTER_SIZE on each side

# Meter dimensions - change these to adjust the audio level indicator
METER_WIDTH: Final[int] = 6  # Width of the meter bar in pixels 
METER_VERTICAL_MARGIN: Final[int] = 4  # Vertical margin from volume bar edges (top and bottom) in pixels
METER_HORIZONTAL_MARGIN: Final[int] = 3  # Horizontal margin from volume bar edges (left and right) in pixels

# Volume bar rendering constants - EXACT like knob renderer
VOLUME_PERCENTAGE_MAX: Final[float] = 100.0  # Maximum volume percentage (100%)

# Color constants
COLOR_MUTED_FILL: Final[tuple[int, int, int, int]] = (110, 110, 110, 255)  # Gray color (RGBA) for muted slider fill
COLOR_TARGET_FILL: Final[tuple[int, int, int, int]] = (102, 255, 102, 255)  # Green color (RGBA) for target device slider fill
COLOR_SOURCE_FILL: Final[tuple[int, int, int, int]] = (102, 179, 255, 255)  # Blue color (RGBA) for source device slider fill
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)  # Black color (RGBA) for audio level meter (default, can be overridden)

# Mathematical constants for radius calculations
RADIUS_DIVISOR: Final[int] = 2  # Used to calculate radius from height/width (radius = dimension / RADIUS_DIVISOR)

# Device types
DEVICE_TYPE_SOURCE: Final[str] = "source"  # Device type identifier for input/source devices


class SliderButtonRenderer:
    def __init__(self, action, is_top: bool):
        self.action = action
        self.is_top = is_top  # True for top button, False for bottom button
        # Get button size - buttons are square, default to 72x72 for standard buttons
        self.button_size = get_button_size_from_action(action)
    
    def render_image(self):
        if not is_service_available():
            try:
                image = render_service_unavailable_button(self.button_size)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
            return
        
        if getattr(self.action, '_is_loading_devices', False):
            try:
                image = render_loading_button(self.button_size)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering loading state: {e}")
            return
        
        if not self.action.selected_device_name:
            return
        
        try:
            image = self._render_slider()
            if image:
                set_image_on_action(self.action, image)
            else:
                try:
                    fallback_image = render_service_unavailable_button(self.button_size)
                    if fallback_image:
                        set_image_on_action(self.action, fallback_image)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Error drawing slider: {e}")
            try:
                fallback_image = render_service_unavailable_button(self.button_size)
                if fallback_image:
                    set_image_on_action(self.action, fallback_image)
            except Exception:
                pass
    
    
    def _draw_rounded_rect_vertical(
        self,
        ctx: cairo.Context,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
        top_end_flat: bool = False
    ) -> None:
        """Draw rounded rectangle with optional flat top end - EXACT copy of knob renderer's _draw_rounded_rect but vertical"""
        if width <= 0 or height <= 0:
            return
        
        # Bottom end should ALWAYS be a semi-circle with full radius (or width/RADIUS_DIVISOR if smaller)
        # This is the vertical equivalent of left end always being rounded in horizontal
        bottom_radius = min(radius, width / RADIUS_DIVISOR)
        
        # Top end radius depends on height
        max_radius = min(width, height) / RADIUS_DIVISOR
        top_radius = min(radius, max_radius) if not top_end_flat else 0
        
        if bottom_radius <= 0:
            ctx.rectangle(x, y, width, height)
            return
        
        ctx.new_sub_path()
        
        # Bottom end: ALWAYS draw as a semi-circle with bottom_radius
        # Start at the bottommost point of the bottom-left semi-circle
        ctx.move_to(x + bottom_radius, y + height)
        
        # Draw bottom-left semi-circle: arc from bottom (π/2) to left (π)
        ctx.arc(x + bottom_radius, y + height - bottom_radius, bottom_radius, math.pi / 2, math.pi)
        
        # Left edge - go to top side
        if top_end_flat or height < (bottom_radius * GUTTER_MULTIPLIER):
            # Flat top end - go straight to top-left corner
            ctx.line_to(x, y)
        else:
            # Rounded top end - go to start of top-left arc
            ctx.line_to(x, y + top_radius)
            ctx.arc(x + top_radius, y + top_radius, top_radius, math.pi, 3 * math.pi / 2)
        
        # Top edge
        if top_end_flat or height < (bottom_radius * GUTTER_MULTIPLIER):
            # Flat top end - straight across
            ctx.line_to(x + width, y)
        else:
            # Rounded top end - continue to top-right arc
            ctx.arc(x + width - top_radius, y + top_radius, top_radius, -math.pi / 2, 0)
        
        # Right edge - go back to bottom side
        ctx.line_to(x + width, y + height - bottom_radius)
        
        # Bottom end: bottom-right semi-circle (ALWAYS drawn as semi-circle with bottom_radius)
        # Draw from right (0) to bottom (π/2)
        ctx.arc(x + width - bottom_radius, y + height - bottom_radius, bottom_radius, 0, math.pi / 2)
        
        ctx.close_path()
    
    def _draw_vertical_meter(
        self,
        ctx: cairo.Context,
        meter_value: int,
        fill_height: int,
        start_y: int,
        slider_x: float,
        slider_height: float,
        meter_x: float,
        meter_width: float,
        radius: float,
        volume_color: tuple[int, int, int, int]
    ) -> None:
        """Draw vertical meter (audio level indicator) - EXACT copy of knob renderer's _draw_animated_meter but vertical"""
        if meter_value <= 0 or fill_height <= 0:
            return
        
        # Calculate meter height with margins - EXACT like knob renderer
        available_height = fill_height - (METER_VERTICAL_MARGIN * GUTTER_MULTIPLIER)
        if available_height <= 0:
            return
        
        # EXACT like knob renderer but vertical:
        # Horizontal: base_meter_width = int((meter_value / VOLUME_PERCENTAGE_MAX) * available_width)
        #            meter_x1 = start_x + METER_HORIZONTAL_MARGIN  (left edge of fill + margin)
        #            meter_x2 = meter_x1 + base_meter_width  (goes right)
        # Vertical:   base_meter_height = int((meter_value / VOLUME_PERCENTAGE_MAX) * available_height)
        #            meter_y2 = start_y + fill_height - METER_VERTICAL_MARGIN  (bottom edge of fill - margin)
        #            meter_y1 = meter_y2 - base_meter_height  (goes up from bottom)
        base_meter_height = int((meter_value / VOLUME_PERCENTAGE_MAX) * available_height)
        meter_y2 = start_y + fill_height - METER_VERTICAL_MARGIN
        meter_y1 = meter_y2 - base_meter_height
        
        if meter_y2 <= meter_y1 or meter_x < 0:
            return
        
        meter_height = meter_y2 - meter_y1
        meter_radius = min(meter_width / RADIUS_DIVISOR, radius)
        
        if getattr(self.action, "_meter_invert_color", True):
            r, g, b, a = volume_color
            meter_color = (RGB_MAX - r, RGB_MAX - g, RGB_MAX - b, a)
        else:
            meter_color = self.action._meter_color or COLOR_METER
        
        # Draw meter with rounded ends (no antialiasing for solid color)
        ctx.set_antialias(cairo.ANTIALIAS_NONE)  # Disable antialiasing for crisp, solid color
        self._draw_rounded_rect_vertical(ctx, meter_x, meter_y1, meter_width, meter_height, meter_radius, top_end_flat=False)
        set_cairo_color(ctx, meter_color)
        ctx.set_line_width(0)  # Ensure no border/shadow
        ctx.fill()
        ctx.set_antialias(cairo.ANTIALIAS_DEFAULT)  # Restore default antialiasing
    
    def _get_layout_constants(self) -> dict[str, int]:
        """
        Calculate all layout constants from base constants - SUPER PARAMETRIC
        Everything is derived from the constants above - just change those to adjust!
        """
        size = self.button_size
        double_height = DOUBLE_HEIGHT  # Use constant directly
        
        # Calculate slider bar position and size - all from constants above
        # Slider starts at top with corner inset and vertical offset
        slider_y = CORNER_INSET + BAR_VERTICAL_OFFSET
        # Slider height = full double height minus top and bottom insets
        slider_height = double_height - (CORNER_INSET * 2) - BAR_VERTICAL_OFFSET
        
        # Slider bar is horizontally centered (with optional offset)
        slider_x = (size - BAR_WIDTH) // 2 + BAR_HORIZONTAL_OFFSET
        
        # Gutter dimensions - all calculated from constants above
        # Gutter is larger than bar to create border effect
        gutter_x = slider_x - BAR_GUTTER_SIZE
        gutter_y = slider_y - BAR_GUTTER_SIZE
        gutter_width = BAR_WIDTH + (BAR_GUTTER_SIZE * GUTTER_MULTIPLIER)
        gutter_height = slider_height + (BAR_GUTTER_SIZE * GUTTER_MULTIPLIER)
        gutter_radius = (slider_height / RADIUS_DIVISOR) + BAR_GUTTER_SIZE
        
        return {
            'button_size': size,
            'double_height': double_height,
            'slider_width': BAR_WIDTH,
            'slider_height': slider_height,
            'slider_radius': BAR_RADIUS,
            'slider_x': slider_x,
            'slider_y': slider_y,
            'gutter_x': gutter_x,
            'gutter_y': gutter_y,
            'gutter_width': gutter_width,
            'gutter_height': gutter_height,
            'gutter_radius': gutter_radius,
        }
    
    def _render_slider(self) -> Optional[Image.Image]:
        """Render the slider button with continuous slider across 2 buttons"""
        try:
            layout = self._get_layout_constants()
            size = int(layout['button_size'])
            double_height = int(layout['double_height'])
            
            # Render at 2x resolution for smooth edges, then scale down
            scale_factor = 2
            surface, ctx = create_cairo_surface(size * scale_factor, double_height * scale_factor)
            ctx.scale(scale_factor, scale_factor)  # Scale coordinate system
            # Enable high-quality antialiasing for smooth rounded edges
            ctx.set_antialias(cairo.ANTIALIAS_BEST)
            
            # All dimensions come from layout constants (fully parametric) - EXACT like knob renderer
            slider_x = layout['slider_x']
            slider_y = layout['slider_y']
            slider_width = layout['slider_width']
            slider_height = layout['slider_height']
            slider_radius = layout['slider_radius']
            
            gutter_x = layout['gutter_x']
            gutter_y = layout['gutter_y']
            gutter_width = layout['gutter_width']
            gutter_height = layout['gutter_height']
            gutter_radius = layout['gutter_radius']
            
            volume = self.action.volume or 0
            device_color = self.action._device_color or {}
            is_source = self.action.selected_device_type == DEVICE_TYPE_SOURCE
            
            effective_fill_height = (volume / VOLUME_PERCENTAGE_MAX) * slider_height
            
            # Determine fill color first (needed for WCAG contrast check)
            fill_color = None
            if effective_fill_height > 0:
                is_muted = getattr(self.action, '_is_muted', False)
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
            
            # Get appropriate gutter color based on fill color contrast (WCAG compliant) - EXACT like knob renderer
            gutter_bg = get_gutter_color(fill_color)
            
            # Draw gutter (larger, creating border effect) - EXACT like knob renderer
            set_cairo_color(ctx, gutter_bg)
            self._draw_rounded_rect_vertical(ctx, gutter_x, gutter_y, gutter_width, gutter_height, gutter_radius)
            ctx.fill()
            
            # Draw fill if there's volume - EXACT like knob renderer
            if effective_fill_height > 0 and fill_color:
                set_cairo_color(ctx, fill_color)
                # Draw volume bar: both ends always semi-circles (like knob renderer: right_end_flat=False)
                slider_fill_y = slider_y + slider_height - effective_fill_height  # Fill from bottom up
                self._draw_rounded_rect_vertical(ctx, slider_x, slider_fill_y, slider_width, effective_fill_height, slider_radius, top_end_flat=False)
                ctx.fill()
            
            # Draw meter if enabled - EXACT like knob renderer
            meter_value = self.action._current_meter_a if is_source else self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and effective_fill_height > 0 and fill_color:
                # Meter position - EXACT like knob renderer: meter_y = bar_y + (bar_height - METER_HEIGHT) / RADIUS_DIVISOR
                # Vertical equivalent: meter_x = slider_x + METER_HORIZONTAL_MARGIN (left edge of fill + margin)
                meter_x = int(slider_x + METER_HORIZONTAL_MARGIN)
                volume_color_for_invert = fill_color
                self._draw_vertical_meter(
                    ctx, meter_value, int(effective_fill_height), int(slider_fill_y), 
                    int(slider_x), int(effective_fill_height), meter_x, METER_WIDTH, int(slider_radius), volume_color_for_invert
                )
            
            # Convert to PIL image, scale down, and crop
            full_image = cairo_to_pil(surface)
            # Scale down from 2x resolution to 1x for crisp rendering
            full_image = full_image.resize((size, double_height), Image.Resampling.LANCZOS)
            
            # Crop to appropriate half based on button position
            if self.is_top:
                return full_image.crop((0, 0, size, size))
            else:
                return full_image.crop((0, size, size, double_height))
        except Exception as img_e:
            log.error(f"Error creating slider image: {img_e}")
            return None
    
