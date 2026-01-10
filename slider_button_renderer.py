"""Slider button rendering for PipeWeaver - creates illusion of single slider across 2 buttons"""
import math
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .render_helpers import (
    RGB_MAX,
    ALPHA_FULL_OPACITY,
    create_cairo_surface,
    cairo_to_pil,
    set_cairo_color,
    get_gutter_color,
    render_service_unavailable_button,
    render_loading_button,
    set_image_on_action,
    get_button_size_from_action,
)
from .pipeweaver_helpers import DEVICE_TYPE_SOURCE
from .service_monitor import is_service_available


# Base pixel values for 64px button - easy to edit
BASE_BUTTON_SIZE: Final[int] = 64
BAR_WIDTH: Final[int] = 25
BAR_RADIUS: Final[int] = 10
BAR_GUTTER_SIZE: Final[int] = 3
CORNER_INSET: Final[int] = 10
METER_WIDTH: Final[int] = 11
METER_VERTICAL_MARGIN: Final[int] = 2

# Fixed constants
BAR_HORIZONTAL_OFFSET: Final[int] = 0
BAR_VERTICAL_OFFSET: Final[int] = 3
GUTTER_MULTIPLIER: Final[int] = 2
VOLUME_PERCENTAGE_MAX: Final[float] = 100.0
COLOR_TARGET_FILL: Final[tuple[int, int, int, int]] = (102, 255, 102, 255)
COLOR_SOURCE_FILL: Final[tuple[int, int, int, int]] = (102, 179, 255, 255)
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)
RADIUS_DIVISOR: Final[int] = 2


class SliderButtonRenderer:
    def __init__(self, action):
        self.action = action
        self.button_size = get_button_size_from_action(action)
    
    @property
    def is_top(self) -> bool:
        step = getattr(self.action, 'volume_step', 5)
        return step > 0
    
    def render_image(self):
        if not is_service_available():
            try:
                image = render_service_unavailable_button(self.button_size)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
            return
        
        if getattr(self.action, '_is_loading_devices', False) or not self.action.selected_device_name:
            try:
                image = render_loading_button(self.button_size)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering loading state: {e}")
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
        """Draw rounded rectangle with optional flat top end"""
        if width <= 0 or height <= 0:
            return
        
        bottom_radius = min(radius, width / RADIUS_DIVISOR)
        max_radius = min(width, height) / RADIUS_DIVISOR
        top_radius = min(radius, max_radius) if not top_end_flat else 0
        
        if bottom_radius <= 0:
            ctx.rectangle(x, y, width, height)
            return
        
        ctx.new_sub_path()
        ctx.move_to(x + bottom_radius, y + height)
        ctx.arc(x + bottom_radius, y + height - bottom_radius, bottom_radius, math.pi / 2, math.pi)
        
        if top_end_flat or height < (bottom_radius * GUTTER_MULTIPLIER):
            ctx.line_to(x, y)
        else:
            ctx.line_to(x, y + top_radius)
            ctx.arc(x + top_radius, y + top_radius, top_radius, math.pi, 3 * math.pi / 2)
        
        if top_end_flat or height < (bottom_radius * GUTTER_MULTIPLIER):
            ctx.line_to(x + width, y)
        else:
            ctx.arc(x + width - top_radius, y + top_radius, top_radius, -math.pi / 2, 0)
        
        ctx.line_to(x + width, y + height - bottom_radius)
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
        volume_color: tuple[int, int, int, int],
        meter_vertical_margin: int
    ) -> None:
        """Draw vertical meter (audio level indicator)"""
        if meter_value <= 0 or fill_height <= 0:
            return
        
        available_height = fill_height - (meter_vertical_margin * GUTTER_MULTIPLIER)
        if available_height <= 0:
            return
        
        base_meter_height = int((meter_value / VOLUME_PERCENTAGE_MAX) * available_height)
        meter_y2 = start_y + fill_height - meter_vertical_margin
        meter_y1 = meter_y2 - base_meter_height
        
        if meter_y2 <= meter_y1 or meter_x < 0:
            return
        
        meter_height = meter_y2 - meter_y1
        meter_radius = min(meter_width / RADIUS_DIVISOR, radius)
        
        if self.action._meter_invert_color:
            r, g, b, a = volume_color
            meter_color = (RGB_MAX - r, RGB_MAX - g, RGB_MAX - b, a)
        else:
            meter_color = self.action._meter_color or COLOR_METER
        
        ctx.set_antialias(cairo.ANTIALIAS_BEST)
        self._draw_rounded_rect_vertical(ctx, meter_x, meter_y1, meter_width, meter_height, meter_radius, top_end_flat=False)
        set_cairo_color(ctx, meter_color)
        ctx.set_line_width(0)
        ctx.fill()
        ctx.set_antialias(cairo.ANTIALIAS_DEFAULT)
    
    def _get_layout_constants(self) -> dict[str, int]:
        """Calculate all layout constants from base pixel values, scaled to button size"""
        size = self.button_size
        double_height = size * 2  # Double height is always 2x button size
        
        slider_y = CORNER_INSET + BAR_VERTICAL_OFFSET
        slider_height = double_height - (CORNER_INSET * 2) - BAR_VERTICAL_OFFSET
        slider_x = (size - BAR_WIDTH) // 2 + BAR_HORIZONTAL_OFFSET
        
        gutter_x = slider_x
        gutter_y = slider_y
        gutter_width = BAR_WIDTH
        gutter_height = slider_height
        gutter_radius = slider_height / RADIUS_DIVISOR
        
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
            'gutter_width': BAR_WIDTH,
            'gutter_height': gutter_height,
            'gutter_radius': gutter_radius,
            'meter_width': METER_WIDTH,
            'meter_vertical_margin': METER_VERTICAL_MARGIN,
        }
    
    def _render_slider(self) -> Optional[Image.Image]:
        """Render the slider button with continuous slider across 2 buttons"""
        try:
            layout = self._get_layout_constants()
            size = int(layout['button_size'])
            double_height = int(layout['double_height'])
            
            surface, ctx = create_cairo_surface(size, double_height)
            ctx.set_antialias(cairo.ANTIALIAS_BEST)
            
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
            
            fill_color = None
            if effective_fill_height > 0:
                if self.action._volume_bar_color:
                    fill_color = self.action._volume_bar_color
                elif device_color:
                    fill_color = (device_color.get('red', 0), device_color.get('green', 0), 
                                  device_color.get('blue', 0), ALPHA_FULL_OPACITY)
                else:
                    fill_color = COLOR_SOURCE_FILL if is_source else COLOR_TARGET_FILL
            
            gutter_bg = get_gutter_color(fill_color)
            set_cairo_color(ctx, gutter_bg)
            self._draw_rounded_rect_vertical(ctx, gutter_x, gutter_y, gutter_width, gutter_height, gutter_radius)
            ctx.fill()
            
            if effective_fill_height > 0 and fill_color:
                set_cairo_color(ctx, fill_color)
                slider_fill_y = slider_y + slider_height - effective_fill_height
                self._draw_rounded_rect_vertical(ctx, slider_x, slider_fill_y, slider_width, effective_fill_height, slider_radius, top_end_flat=False)
                ctx.fill()
            
            # Add stroke around gutter - 2px for both muted and unmuted
            stroke_width = 2
            set_cairo_color(ctx, (0, 0, 0, 255))  # Always black
            ctx.set_antialias(cairo.ANTIALIAS_BEST)
            ctx.set_line_width(stroke_width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            # Draw border on outside of gutter
            self._draw_rounded_rect_vertical(ctx, gutter_x, gutter_y, 
                                            gutter_width, gutter_height, 
                                            gutter_radius)
            ctx.stroke()
            ctx.set_antialias(cairo.ANTIALIAS_DEFAULT)
            
            meter_value = self.action._current_meter_a if is_source else self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and effective_fill_height > 0 and fill_color:
                # Center meter horizontally within slider (draw meter from left edge)
                meter_x = slider_x + (slider_width - layout['meter_width']) // 2
                # Position meter further away from bottom with more padding
                meter_y_offset = int(layout['meter_vertical_margin'] * 4) + 1  # More padding from bottom
                meter_start_y = slider_fill_y + meter_y_offset - 3
                meter_available_height = int(effective_fill_height) - meter_y_offset - layout['meter_vertical_margin']
                
                if meter_available_height > 0:
                    volume_color_for_invert = fill_color
                    self._draw_vertical_meter(
                        ctx, meter_value, meter_available_height, meter_start_y, 
                        int(slider_x), int(effective_fill_height), meter_x, layout['meter_width'], 
                        int(slider_radius), volume_color_for_invert, layout['meter_vertical_margin']
                    )
            
            full_image = cairo_to_pil(surface)
            
            # Crop the appropriate portion
            if self.is_top:
                result_image = full_image.crop((0, 0, size, size))
            else:
                result_image = full_image.crop((0, size, size, double_height))
            
            # Rotate for horizontal orientation
            orientation = getattr(self.action, 'orientation', 'vertical')
            if orientation == "horizontal":
                result_image = result_image.rotate(-90, expand=True)
                # Resize back to square if rotation changed dimensions
                if result_image.size != (size, size):
                    result_image = result_image.resize((size, size), Image.Resampling.LANCZOS)
            
            return result_image
        except Exception as img_e:
            log.error(f"Error creating slider image: {img_e}")
            return None    
