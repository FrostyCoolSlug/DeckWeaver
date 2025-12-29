"""Image rendering utilities for PipeWeaver actions"""
from typing import Optional

from PIL import Image, ImageDraw, ImageFont  # type: ignore
from loguru import logger as log  # type: ignore

from .constants import (
    BAR_HEIGHT,
    BAR_RADIUS,
    COLOR_BACKGROUND_DARK,
    COLOR_LABEL,
    COLOR_METER,
    COLOR_MUTED_BG,
    COLOR_MUTED_FILL,
    COLOR_MUTED_OUTLINE,
    COLOR_OUTLINE_GRAY,
    COLOR_SERVICE_UNAVAILABLE_BG,
    COLOR_SERVICE_UNAVAILABLE_HINT,
    COLOR_SERVICE_UNAVAILABLE_TEXT,
    COLOR_SOURCE_FILL,
    COLOR_TARGET_BG,
    COLOR_TARGET_FILL,
    COLOR_TARGET_OUTLINE,
    DEVICE_TYPE_SOURCE,
    EDGE_PADDING,
    ICON_MAX_SIZE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    METER_EDGE_INSET,
    METER_HEIGHT,
    MONOSPACE_FONT_PATHS,
)
from .service_monitor import is_service_available


class ImageRenderer:
    def __init__(self, action):
        self.action = action
        self._font_cache = {}
    
    def render_image(self):
        if not is_service_available():
            try:
                image = self._render_service_unavailable()
                if image:
                    self._set_image_on_action(image)
            except Exception as e:
                log.error(f"Error rendering service unavailable state: {e}")
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
    
    def _load_monospace_font(self, size: int = 12) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        cache_key = ("mono", size)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached

        for font_path, _ in MONOSPACE_FONT_PATHS:
            try:
                font = ImageFont.truetype(font_path, size)
                self._font_cache[cache_key] = font
                return font
            except Exception:
                continue

        font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font
    
    def _render_service_unavailable(self) -> Optional[Image.Image]:
        try:
            image = Image.new('RGBA', (IMAGE_WIDTH, IMAGE_HEIGHT), COLOR_SERVICE_UNAVAILABLE_BG)
            draw = ImageDraw.Draw(image)
            
            try:
                title_font = self._load_monospace_font(28)
                subtitle_font = self._load_monospace_font(18)
            except Exception:
                title_font = ImageFont.load_default()
                subtitle_font = ImageFont.load_default()
            
            title = "PipeWeaver"
            title_bbox = draw.textbbox((0, 0), title, font=title_font)
            title_x = (IMAGE_WIDTH - (title_bbox[2] - title_bbox[0])) // 2
            draw.text((title_x, 60), title, fill=COLOR_SERVICE_UNAVAILABLE_TEXT, font=title_font)
            
            subtitle = "Service Unavailable"
            subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_x = (IMAGE_WIDTH - (subtitle_bbox[2] - subtitle_bbox[0])) // 2
            draw.text((subtitle_x, 100), subtitle, fill=COLOR_SERVICE_UNAVAILABLE_TEXT, font=subtitle_font)
            
            hint = "Start PipeWeaver to continue"
            hint_bbox = draw.textbbox((0, 0), hint, font=subtitle_font)
            hint_x = (IMAGE_WIDTH - (hint_bbox[2] - hint_bbox[0])) // 2
            draw.text((hint_x, 160), hint, fill=COLOR_SERVICE_UNAVAILABLE_HINT, font=subtitle_font)
            
            return image
        except Exception as e:
            log.error(f"Error rendering service unavailable state: {e}")
            return None
    
    def _get_layout_constants(self) -> dict[str, int]:
        icon_bottom_y = IMAGE_HEIGHT - ICON_MAX_SIZE - EDGE_PADDING
        icon_left_x = EDGE_PADDING
        left_margin = ICON_MAX_SIZE + EDGE_PADDING + EDGE_PADDING
        right_margin = EDGE_PADDING
        bar_width = IMAGE_WIDTH - left_margin - right_margin
        bar_y = IMAGE_HEIGHT - BAR_HEIGHT - EDGE_PADDING - 15
        
        return {
            'image_width': IMAGE_WIDTH,
            'image_height': IMAGE_HEIGHT,
            'edge_padding': EDGE_PADDING,
            'icon_max_size': ICON_MAX_SIZE,
            'icon_bottom_y': icon_bottom_y,
            'icon_left_x': icon_left_x,
            'left_margin': left_margin,
            'bar_width': bar_width,
            'bar_height': BAR_HEIGHT,
            'bar_y': bar_y,
            'radius': BAR_RADIUS
        }
    
    def _render_source_device(self, is_muted: bool = False) -> Optional[Image.Image]:
        device_color = self.action._device_color or {}
        volume_value = self.action.volume or 0
        
        try:
            layout = self._get_layout_constants()
            image = Image.new('RGBA', (layout['image_width'], layout['image_height']), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            start_x = layout['left_margin'] - 2
            
            self._draw_volume_bar(
                draw, start_x, layout['bar_y'], layout['bar_width'], layout['bar_height'],
                volume_value, is_muted, device_color, COLOR_SOURCE_FILL
            )
            
            bar_fill_width = int((volume_value / 100.0) * layout['bar_width'])
            meter_value = self.action._current_meter_a
            if self.action._meters_enabled and meter_value > 0 and bar_fill_width > 0:
                self._draw_animated_meter(
                    draw, meter_value, bar_fill_width, start_x, layout['bar_width'],
                    layout['bar_y'] + layout['bar_height'] - METER_HEIGHT - 2, METER_HEIGHT, layout['radius']
                )

            self._composite_icon(image, layout['icon_left_x'], layout['icon_bottom_y'], layout['icon_max_size'])
            return image
        except Exception as img_e:
            log.error(f"Error creating source device image: {img_e}")
            return None
    
    def _render_target_device(self, muted: bool = False) -> Optional[Image.Image]:
        volume = self.action.volume or 0
        
        try:
            layout = self._get_layout_constants()
            image = Image.new('RGBA', (layout['image_width'], layout['image_height']), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            bar_x = layout['left_margin'] - 2
            bar_fill_width = int((volume / 100.0) * layout['bar_width'])

            bg_color = COLOR_MUTED_BG if muted else COLOR_TARGET_BG
            outline_color = COLOR_MUTED_OUTLINE if muted else COLOR_TARGET_OUTLINE
            fill_color = COLOR_MUTED_FILL if muted else COLOR_TARGET_FILL
            
            volume_bar_color = self.action._volume_bar_color
            if volume_bar_color and not muted:
                fill_color = volume_bar_color
            
            radius = layout['bar_height'] // 2

            bar_bbox = (bar_x, layout['bar_y'], bar_x + layout['bar_width'], layout['bar_y'] + layout['bar_height'])
            self._draw_rounded_rect(draw, bar_bbox, radius, bg_color)
            self._draw_rounded_rect_outline(draw, bar_bbox, radius, outline_color, 2)

            if bar_fill_width > 0:
                fill_bbox = (bar_x + 2, layout['bar_y'] + 2, bar_x + min(bar_fill_width, layout['bar_width'] - 2), 
                           layout['bar_y'] + layout['bar_height'] - 2)
                self._draw_rounded_rect(draw, fill_bbox, max(0, radius - 2), fill_color)
            
            meter_value = self.action._current_meter_target
            if self.action._meters_enabled and meter_value > 0 and bar_fill_width > 0:
                self._draw_animated_meter(
                    draw, meter_value, bar_fill_width, bar_x, layout['bar_width'],
                    layout['bar_y'] + layout['bar_height'] - METER_HEIGHT - 2, METER_HEIGHT, radius
                )
            
            self._composite_icon(image, layout['icon_left_x'], layout['icon_bottom_y'], layout['icon_max_size'])
            return image
        except Exception as img_e:
            log.error(f"Error creating target device image: {img_e}")
            return None
    
    def _draw_rounded_rect(
        self,
        draw: ImageDraw.ImageDraw,
        bbox: tuple[int, int, int, int],
        radius: int,
        fill: tuple[int, int, int, int]
    ) -> None:
        x1, y1, x2, y2 = bbox
        
        if x2 <= x1 or y2 <= y1:
            return
        
        width = x2 - x1
        height = y2 - y1
        max_radius = min(width, height) // 2
        radius = min(radius, max_radius)
        
        if radius <= 0:
            draw.rectangle(bbox, fill=fill)
            return
        
        if x1 + radius >= x2 - radius or y1 + radius >= y2 - radius:
            draw.rectangle(bbox, fill=fill)
            return
        
        draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
        draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
        
        draw.pieslice([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=fill)
        draw.pieslice([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=fill)
        draw.pieslice([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=fill)
        draw.pieslice([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=fill)
    
    def _draw_rounded_rect_outline(
        self,
        draw: ImageDraw.ImageDraw,
        bbox: tuple[int, int, int, int],
        radius: int,
        outline: tuple[int, int, int, int],
        width: int = 1
    ) -> None:
        x1, y1, x2, y2 = bbox
        if radius <= 0:
            draw.rectangle(bbox, outline=outline, width=width)
            return
        
        draw.rectangle([x1 + radius, y1, x2 - radius, y1 + width], fill=outline)
        draw.rectangle([x1 + radius, y2 - width, x2 - radius, y2], fill=outline)
        draw.rectangle([x1, y1 + radius, x1 + width, y2 - radius], fill=outline)
        draw.rectangle([x2 - width, y1 + radius, x2, y2 - radius], fill=outline)
        
        if width == 1:
            draw.arc([x1, y1, x1 + 2*radius, y1 + 2*radius], 180, 270, fill=outline)
            draw.arc([x2 - 2*radius, y1, x2, y1 + 2*radius], 270, 360, fill=outline)
            draw.arc([x1, y2 - 2*radius, x1 + 2*radius, y2], 90, 180, fill=outline)
            draw.arc([x2 - 2*radius, y2 - 2*radius, x2, y2], 0, 90, fill=outline)
        else:
            for i in range(width):
                offset = i
                draw.arc([x1 - offset, y1 - offset, x1 + 2*radius + offset, y1 + 2*radius + offset], 180, 270, fill=outline)
                draw.arc([x2 - 2*radius - offset, y1 - offset, x2 + offset, y1 + 2*radius + offset], 270, 360, fill=outline)
                draw.arc([x1 - offset, y2 - 2*radius - offset, x1 + 2*radius + offset, y2 + offset], 90, 180, fill=outline)
                draw.arc([x2 - 2*radius - offset, y2 - 2*radius - offset, x2 + offset, y2 + offset], 0, 90, fill=outline)
    
    def _draw_volume_bar(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        height: int,
        volume: int,
        is_muted: bool,
        device_color: Optional[dict[str, int]] = None,
        fallback_color: tuple[int, int, int, int] = COLOR_SOURCE_FILL
    ) -> None:
        draw.rectangle([x, y, x + width, y + height], fill=COLOR_BACKGROUND_DARK)
        draw.rectangle([x, y, x + width, y + height], outline=COLOR_OUTLINE_GRAY, width=4)
        
        if volume <= 0:
            return
            
        fill_width = int((volume / 100.0) * width)
        fill_x = x + 4
        fill_x2 = x + min(fill_width, width - 4)
        fill_y = y + 4
        fill_y2 = y + height - 4
        
        if fill_x2 <= fill_x:
            return
        
        if is_muted:
            draw.rectangle([fill_x, fill_y, fill_x2, fill_y2], fill=COLOR_MUTED_FILL)
        else:
            volume_bar_color = self.action._volume_bar_color
            if volume_bar_color:
                color = volume_bar_color
            elif device_color:
                color = (device_color['red'], device_color['green'], device_color['blue'], 255)
            else:
                color = fallback_color
            draw.rectangle([fill_x, fill_y, fill_x2, fill_y2], fill=color)
    
    def _draw_animated_meter(
        self,
        draw: ImageDraw.ImageDraw,
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
            draw.rectangle(
                [meter_x1_inset, meter_y, meter_x2_inset, meter_y + meter_height],
                fill=meter_color
            )

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
            image.load()
            self.action.set_media(image=image, update=True)
            
            # Workaround: call update again to force hardware sync
            dial = self.action.get_input()
            if dial:
                dial.update()
        except Exception as e:
            log.error(f"Error setting image: {e}")
