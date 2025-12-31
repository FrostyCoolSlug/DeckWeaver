"""Image rendering utilities for PipeWeaver actions"""
import math
from typing import Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .constants import (
    BAR_HEIGHT,
    BAR_RADIUS,
    COLOR_METER,
    COLOR_MUTED_FILL,
    COLOR_SERVICE_UNAVAILABLE_BG,
    COLOR_SERVICE_UNAVAILABLE_HINT,
    COLOR_SERVICE_UNAVAILABLE_TEXT,
    COLOR_SOURCE_FILL,
    COLOR_TARGET_FILL,
    CORNER_INSET,
    DEVICE_TYPE_SOURCE,
    EDGE_PADDING,
    ICON_MAX_SIZE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    METER_EDGE_INSET,
    METER_HEIGHT,
)
from .service_monitor import is_service_available


class ImageRenderer:
    def __init__(self, action):
        self.action = action
        self._loading_frame = 0
    
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
                    self._loading_frame = (self._loading_frame + 1) % 60
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
        ctx.set_source_rgba(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    
    def _draw_text_centered(self, ctx: cairo.Context, text: str, x: float, y: float, font_size: float = 24):
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
            self._draw_text_centered(ctx, "PipeWeaver", IMAGE_WIDTH / 2, 60, 28)
            
            self._draw_text_centered(ctx, "Service Unavailable", IMAGE_WIDTH / 2, 100, 18)
            
            self._set_color(ctx, COLOR_SERVICE_UNAVAILABLE_HINT)
            self._draw_text_centered(ctx, "Start PipeWeaver to continue", IMAGE_WIDTH / 2, 160, 18)
            
            return self._cairo_to_pil(surface)
        except Exception as e:
            log.error(f"Error rendering service unavailable state: {e}")
            return None
    
    def _render_loading(self) -> Optional[Image.Image]:
        try:
            surface, ctx = self._create_cairo_surface(IMAGE_WIDTH, IMAGE_HEIGHT)
            
            center_x, center_y = IMAGE_WIDTH / 2, IMAGE_HEIGHT / 2
            spinner_radius = 20
            dot_count = 8
            angle_step = 2 * math.pi / dot_count
            
            for i in range(dot_count):
                angle = (self._loading_frame * 0.1) + (i * angle_step)
                dot_x = center_x + math.cos(angle) * spinner_radius
                dot_y = center_y - 30 + math.sin(angle) * spinner_radius
                
                alpha = 0.3 + 0.7 * (1.0 - abs(i - (self._loading_frame % dot_count)) / dot_count)
                ctx.set_source_rgba(1.0, 1.0, 1.0, alpha)
                ctx.arc(dot_x, dot_y, 3, 0, 2 * math.pi)
                ctx.fill()
            
            self._set_color(ctx, (255, 255, 255, 255))
            self._draw_text_centered(ctx, "Loading...", center_x, center_y + 20, 24)
            
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
        bar_y = IMAGE_HEIGHT - BAR_HEIGHT - CORNER_INSET - 8
        
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
            'bar_y': bar_y,
            'radius': BAR_RADIUS
        }
    
    def _render_device(self, is_muted: bool = False) -> Optional[Image.Image]:
        """Unified rendering for both source and target devices."""
        volume = self.action.volume or 0
        device_color = self.action._device_color or {}
        is_source = self.action.selected_device_type == DEVICE_TYPE_SOURCE
        
        GUTTER_BG = (70, 70, 70, 255)
        
        try:
            layout = self._get_layout_constants()
            surface, ctx = self._create_cairo_surface(layout['image_width'], layout['image_height'])
            
            bar_x = layout['left_margin'] - 2
            bar_width = layout['bar_width']
            bar_height = layout['bar_height']
            bar_y = layout['bar_y']
            radius = layout['bar_height'] / 2

            self._set_color(ctx, GUTTER_BG)
            self._draw_rounded_rect(ctx, bar_x, bar_y, bar_width, bar_height, radius)
            ctx.fill()

            effective_fill_width = (volume / 100.0) * bar_width
            
            if effective_fill_width > 0:
                if is_muted:
                    fill_color = COLOR_MUTED_FILL
                else:
                    volume_bar_color = self.action._volume_bar_color
                    if volume_bar_color:
                        fill_color = volume_bar_color
                    elif device_color:
                        fill_color = (device_color.get('red', 0), device_color.get('green', 0), 
                                      device_color.get('blue', 0), 255)
                    else:
                        fill_color = COLOR_SOURCE_FILL if is_source else COLOR_TARGET_FILL
                
                self._set_color(ctx, fill_color)
                self._draw_rounded_rect(ctx, bar_x, bar_y, effective_fill_width, bar_height, radius)
                ctx.fill()
            
            meter_value = self.action._current_meter_a if is_source else self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and effective_fill_width > 0:
                meter_y = bar_y + bar_height - METER_HEIGHT - 2
                self._draw_animated_meter(
                    ctx, meter_value, int(effective_fill_width), int(bar_x), 
                    int(bar_width), int(meter_y), METER_HEIGHT, int(radius)
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
        radius: float
    ) -> None:
        """Draw rounded rectangle"""
        if width <= 0 or height <= 0:
            return
        
        max_radius = min(width, height) / 2
        radius = min(radius, max_radius)
        
        if radius <= 0:
            ctx.rectangle(x, y, width, height)
            return
        
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        ctx.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        ctx.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
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
        radius: int
    ) -> None:
        if meter_value <= 0 or fill_width <= 0:
            return

        base_meter_width = int((meter_value / 100.0) * fill_width)
        meter_x1 = start_x
        meter_x2 = start_x + base_meter_width

        if meter_x2 <= meter_x1 or meter_y < 0:
            return

        meter_x1_inset = max(meter_x1, start_x + 2)
        meter_x2_inset = min(meter_x2, start_x + bar_width - METER_EDGE_INSET)

        if meter_x2_inset > meter_x1_inset:
            meter_color = self.action._meter_color or COLOR_METER
            self._set_color(ctx, meter_color)
            ctx.rectangle(meter_x1_inset, meter_y, meter_x2_inset - meter_x1_inset, meter_height)
            ctx.fill()

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
