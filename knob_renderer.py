"""Knob-specific image rendering for PipeWeaver actions"""
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
    render_service_unavailable_full,
    render_loading_full,
    set_image_on_action,
    get_screen_size_from_action,
)
from .pipeweaver_helpers import DEVICE_TYPE_SOURCE
from .service_monitor import is_service_available

EDGE_PADDING: Final[int] = 10
CORNER_INSET: Final[int] = 14

ICON_MAX_SIZE: Final[int] = 52

BAR_HEIGHT: Final[int] = 12
BAR_RADIUS: Final[int] = 3
BAR_GUTTER_SIZE: Final[int] = 4
BAR_HORIZONTAL_OFFSET: Final[int] = 0
BAR_VERTICAL_OFFSET: Final[int] = 5

METER_HEIGHT: Final[int] = 4
METER_HORIZONTAL_MARGIN: Final[int] = 5

VOLUME_FULL_TOLERANCE: Final[float] = 0.5
VOLUME_PERCENTAGE_MAX: Final[float] = 100.0

RADIUS_DIVISOR: Final[int] = 2
GUTTER_MULTIPLIER: Final[int] = 2

COLOR_TARGET_FILL: Final[tuple[int, int, int, int]] = (102, 255, 102, 255)
COLOR_SOURCE_FILL: Final[tuple[int, int, int, int]] = (102, 179, 255, 255)
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)


class KnobRenderer:
    def __init__(self, action):
        self.action = action
        self.screen_width, self.screen_height = get_screen_size_from_action(action)
    
    def render_image(self):
        if not is_service_available():
            try:
                image = render_service_unavailable_full(self.screen_width, self.screen_height)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
            return
        
        if getattr(self.action, '_is_loading_devices', False):
            try:
                image = render_loading_full(self.screen_width, self.screen_height)
                if image:
                    set_image_on_action(self.action, image)
            except Exception as e:
                log.error(f"Error rendering loading state: {e}")
            return
        
        if not self.action.selected_device_name:
            return
        
        try:
            image = self._render_device()
            
            if image:
                set_image_on_action(self.action, image)
            else:
                try:
                    fallback_image = render_service_unavailable_full(self.screen_width, self.screen_height)
                    if fallback_image:
                        set_image_on_action(self.action, fallback_image)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Error drawing volume bars: {e}")
            try:
                fallback_image = render_service_unavailable_full(self.screen_width, self.screen_height)
                if fallback_image:
                    set_image_on_action(self.action, fallback_image)
            except Exception:
                pass
    
    def _get_layout_constants(self) -> dict[str, int]:
        icon_left_x = CORNER_INSET
        icon_bottom_y = self.screen_height - ICON_MAX_SIZE - CORNER_INSET
        
        left_margin = icon_left_x + ICON_MAX_SIZE + EDGE_PADDING
        right_margin = CORNER_INSET
        bar_width = self.screen_width - left_margin - right_margin
        bar_y = self.screen_height - BAR_HEIGHT - CORNER_INSET - BAR_VERTICAL_OFFSET
        bar_x = left_margin + BAR_HORIZONTAL_OFFSET
        gutter_x = bar_x
        gutter_y = bar_y
        gutter_width = bar_width
        gutter_height = BAR_HEIGHT
        gutter_radius = BAR_HEIGHT / RADIUS_DIVISOR
        
        return {
            'image_width': self.screen_width,
            'image_height': self.screen_height,
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
    
    def _render_device(self) -> Optional[Image.Image]:
        """Unified rendering for both source and target devices."""
        volume = self.action.volume or 0
        device_color = self.action._device_color or {}
        is_source = self.action.selected_device_type == DEVICE_TYPE_SOURCE
        
        try:
            layout = self._get_layout_constants()
            surface, ctx = create_cairo_surface(layout['image_width'], layout['image_height'])
            effective_fill_width = (volume / VOLUME_PERCENTAGE_MAX) * layout['bar_width']
            
            fill_color = None
            if effective_fill_width > 0:
                if self.action._volume_bar_color:
                    fill_color = self.action._volume_bar_color
                elif device_color:
                    fill_color = (device_color.get('red', 0), device_color.get('green', 0), 
                                  device_color.get('blue', 0), ALPHA_FULL_OPACITY)
                else:
                    fill_color = COLOR_SOURCE_FILL if is_source else COLOR_TARGET_FILL
            
            gutter_bg = get_gutter_color(fill_color)
            set_cairo_color(ctx, gutter_bg)
            self._draw_rounded_rect(ctx, layout['gutter_x'], layout['gutter_y'], layout['gutter_width'], layout['gutter_height'], layout['gutter_radius'])
            ctx.fill()

            if effective_fill_width > 0 and fill_color:
                set_cairo_color(ctx, fill_color)
                self._draw_rounded_rect(ctx, layout['bar_x'], layout['bar_y'], effective_fill_width, layout['bar_height'], layout['bar_radius'], right_end_flat=False)
                ctx.fill()
            
            # Add stroke around gutter - 2px for both muted and unmuted
            stroke_width = 2
            set_cairo_color(ctx, (0, 0, 0, 255))  # Always black
            ctx.set_line_width(stroke_width)
            self._draw_rounded_rect(ctx, layout['gutter_x'], layout['gutter_y'], 
                                   layout['gutter_width'], layout['gutter_height'], 
                                   layout['gutter_radius'])
            ctx.stroke()
            
            meter_value = self.action._current_meter_a if is_source else self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and effective_fill_width > 0 and fill_color:
                meter_y = layout['bar_y'] + (layout['bar_height'] - METER_HEIGHT) / RADIUS_DIVISOR
                self._draw_animated_meter(
                    ctx, meter_value, int(effective_fill_width), int(layout['bar_x']), 
                    int(effective_fill_width), int(meter_y), METER_HEIGHT, int(layout['bar_radius']), fill_color
                )
            
            image = cairo_to_pil(surface)
            self._composite_icon(image, layout['icon_left_x'], layout['icon_bottom_y'], layout['icon_max_size'])
            
            # Draw red diagonal line across icon container when muted
            if self.action._is_device_muted():
                # Create a new surface for the line overlay
                line_surface, line_ctx = create_cairo_surface(layout['image_width'], layout['image_height'])
                line_ctx.set_antialias(cairo.ANTIALIAS_BEST)
                
                # Draw thick red diagonal line from bottom-left to top-right of icon container
                icon_top_y = layout['icon_bottom_y'] + layout['icon_max_size']
                icon_right_x = layout['icon_left_x'] + layout['icon_max_size']
                
                set_cairo_color(line_ctx, (255, 0, 0, 255))
                line_ctx.set_line_width(6)  # Thick red line
                line_ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                line_ctx.move_to(layout['icon_left_x'], icon_top_y)  # Bottom-left corner
                line_ctx.line_to(icon_right_x, layout['icon_bottom_y'])  # Top-right corner
                line_ctx.stroke()
                
                # Composite the line over the image
                line_image = cairo_to_pil(line_surface)
                if line_image.mode != 'RGBA':
                    line_image = line_image.convert('RGBA')
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')
                image = Image.alpha_composite(image, line_image)
            
            return image
        except Exception as img_e:
            log.error(f"Error creating device image: {img_e}")
            return None
    
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
        
        left_radius = min(radius, height / RADIUS_DIVISOR)
        max_radius = min(width, height) / RADIUS_DIVISOR
        right_radius = min(radius, max_radius) if not right_end_flat else 0
        
        if left_radius <= 0:
            ctx.rectangle(x, y, width, height)
            return
        
        ctx.new_sub_path()
        ctx.move_to(x, y + left_radius)
        ctx.arc(x + left_radius, y + left_radius, left_radius, math.pi, 3 * math.pi / 2)
        
        if right_end_flat or width < (left_radius * GUTTER_MULTIPLIER):
            ctx.line_to(x + width, y)
        else:
            ctx.line_to(x + width - right_radius, y)
            ctx.arc(x + width - right_radius, y + right_radius, right_radius, -math.pi / 2, 0)
        
        if right_end_flat or width < (left_radius * GUTTER_MULTIPLIER):
            ctx.line_to(x + width, y + height)
        else:
            ctx.arc(x + width - right_radius, y + height - right_radius, right_radius, 0, math.pi / 2)
        
        ctx.line_to(x + left_radius, y + height)
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
        
        if self.action._meter_invert_color:
            r, g, b, a = volume_color
            meter_color = (RGB_MAX - r, RGB_MAX - g, RGB_MAX - b, a)
        else:
            meter_color = self.action._meter_color or COLOR_METER
        
        ctx.set_antialias(cairo.ANTIALIAS_NONE)
        self._draw_rounded_rect(ctx, meter_x1, meter_y, meter_width, meter_height, meter_radius, right_end_flat=False)
        set_cairo_color(ctx, meter_color)
        ctx.set_line_width(0)
        ctx.fill()
        ctx.set_antialias(cairo.ANTIALIAS_DEFAULT)

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
