"""Image rendering utilities for PipeWeaver actions"""
import os
import traceback

from PIL import Image, ImageDraw, ImageFont  # type: ignore
from loguru import logger as log  # type: ignore

from .service_monitor import is_service_available


class ImageRenderer:
    """Renders images for PipeWeaver actions using PIL"""
    
    def __init__(self, action):
        """Initialize renderer with action instance"""
        self.action = action
        self._font_cache = {}
        self._icon_cache_local = {}
    
    def render_image(self):
        """Render the button image - shows mute state or volume bars"""
        # Check service availability first - show error state if down
        if not is_service_available():
            image = self._render_service_unavailable()
            if image:
                self._set_image_on_action(image)
            return
        
        if not self.action.selected_device_name:
            display_text = self.action.selected_device_name if self.action.selected_device_name else "PipeWeaver"
            if hasattr(self.action, 'set_label'):
                self.action.set_label(text=display_text, position="center", font_size=10)
            return
        
        # Use only cached UI state for drawing to keep rendering snappy and avoid
        # blocking on status/device lookups.
        device_short = self.action.selected_device_name[:7] if self.action.selected_device_name else ""

        try:
            if hasattr(self.action, '_menu_mode') and self.action._menu_mode:
                image = self._render_menu()
            elif self.action.selected_device_type == "source":
                image = self._render_source_device()
            else:
                image = self._render_target_device()
            
            if image:
                self._set_image_on_action(image)
        except Exception as e:
            log.error(f"Error drawing volume bars: {e}")
            log.error(traceback.format_exc())
    
    def _load_monospace_font(self, size=12):
        """Load a bold, clean monospace font with caching and fallback to default."""
        cache_key = ("mono", size)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached

        font_paths = [
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
            "/usr/share/fonts/truetype/source-code-pro/SourceCodePro-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/UbuntuMono-Bold.ttf",
            "/usr/share/fonts/truetype/fira-code/FiraCode-Bold.ttf",
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
            "/usr/share/fonts/truetype/source-code-pro/SourceCodePro-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/TTF/arial.ttf",
            "/System/Library/Fonts/Monaco.ttf",
            "C:/Windows/Fonts/consola.ttf",
        ]

        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, size)
                self._font_cache[cache_key] = font
                return font
            except Exception:
                continue

        font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font
    
    def _render_service_unavailable(self):
        """Render error state when PipeWeaver service is unavailable.
        
        Shows a yellow/amber background with error message to clearly indicate
        the service is down.
        """
        try:
            image_width = 480
            image_height = 240
            
            # Yellow/amber background for warning state
            bg_color = (255, 193, 7, 255)  # Amber/yellow
            image = Image.new('RGBA', (image_width, image_height), bg_color)
            draw = ImageDraw.Draw(image)
            
            # Load font for text
            try:
                title_font = self._load_monospace_font(28)
                subtitle_font = self._load_monospace_font(18)
            except Exception:
                title_font = ImageFont.load_default()
                subtitle_font = ImageFont.load_default()
            
            # Dark text for contrast on yellow background
            text_color = (33, 33, 33, 255)
            
            # Draw warning icon (triangle with exclamation)
            center_x = image_width // 2
            
            # Title text
            title = "PipeWeaver"
            title_bbox = draw.textbbox((0, 0), title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (image_width - title_width) // 2
            draw.text((title_x, 60), title, fill=text_color, font=title_font)
            
            # Subtitle text
            subtitle = "Service Unavailable"
            subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
            subtitle_x = (image_width - subtitle_width) // 2
            draw.text((subtitle_x, 100), subtitle, fill=text_color, font=subtitle_font)
            
            # Hint text
            hint = "Start PipeWeaver to continue"
            hint_bbox = draw.textbbox((0, 0), hint, font=subtitle_font)
            hint_width = hint_bbox[2] - hint_bbox[0]
            hint_x = (image_width - hint_width) // 2
            draw.text((hint_x, 160), hint, fill=(66, 66, 66, 255), font=subtitle_font)
            
            return image
            
        except Exception as e:
            log.error(f"Error rendering service unavailable state: {e}")
            log.error(traceback.format_exc())
            return None
    
    def _render_source_device(self, is_a_muted=False, is_b_muted=False):
        """Render image for source device with two volume bars.

        Uses only locally cached UI state (volume, meters, selected mixes) for speed.
        """
        device_colour = getattr(self.action, "_device_colour", {}) or {}

        # Use the currently displayed volume for both bars; selected_mixes decides focus.
        volume_value = getattr(self.action, "volume", 0) or 0
        volumes = [volume_value, volume_value]
        
        try:
            is_linked = False
            
            image_width = 480
            image_height = 240
            
            image = Image.new('RGBA', (image_width, image_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            edge_padding = 10
            
            icon_max_size = 150
            icon_bottom_y = image_height - icon_max_size - edge_padding
            icon_left_x = edge_padding
            
            left_margin = icon_max_size + edge_padding + edge_padding
            right_margin = edge_padding
            bar_width = image_width - left_margin - right_margin
            bar_height = 24
            bar_spacing = 12
            radius = 4
            start_x = left_margin
            bar_b_y = image_height - bar_height - edge_padding - 15
            bar_a_y = bar_b_y - bar_height - bar_spacing
            
            volume_a = volumes[0] if len(volumes) > 0 else 0
            volume_b = volumes[1] if len(volumes) > 1 else 0
            
            # Labels for volume and meter
            try:
                label_font = self._load_monospace_font(12)
            except Exception:
                label_font = ImageFont.load_default()

            draw.text((start_x + 4, bar_a_y - 15), "VOL", fill=(204, 204, 204, 204), font=label_font)

            meter_label_y = bar_a_y + bar_height + 12
            draw.text((start_x + 4, meter_label_y), "LVL", fill=(204, 204, 204, 204), font=label_font)

            if is_linked:
                self._draw_linked_volume_bars(draw, start_x, bar_a_y, bar_width, bar_height, radius,
                                             volume_a, volume_b, is_a_muted, is_b_muted, device_colour)
            
            bar_a_fill_width = int((volume_a / 100.0) * bar_width)
            bar_b_fill_width = int((volume_b / 100.0) * bar_width)
            
            is_a_selected = "A" in self.action.selected_mixes
            is_b_selected = "B" in self.action.selected_mixes

            indicators_y = bar_a_y - 45

            total_indicators = (1 if is_linked else 0) + (1 if is_a_selected else 0) + (1 if is_b_selected else 0)

            if total_indicators > 0:
                indicator_index = 0

                icon_size = 48
                icon_x = start_x + 4
                icon_y = indicators_y - 4

                if is_linked:
                    icon_name = "linked-white.png"
                else:
                    icon_name = "unlinked-dimmed.png"
                
                icon_path = self.action.plugin_base.get_asset_path(icon_name, ["icons"])
                cache_key = (icon_path, icon_size)
                cached_icon = self._icon_cache_local.get(cache_key)
                if cached_icon is None and os.path.exists(icon_path):
                    link_icon = Image.open(icon_path)
                    if link_icon.mode == 'P':
                        link_icon = link_icon.convert('RGBA')
                    if link_icon.mode != 'RGBA':
                        link_icon = link_icon.convert('RGBA')
                    link_icon_resized = link_icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    cached_icon = link_icon_resized
                    self._icon_cache_local[cache_key] = cached_icon
                if cached_icon is not None:
                    image.paste(cached_icon, (icon_x, icon_y), cached_icon)
                indicator_index += 1

            self._draw_unlinked_volume_bars(draw, start_x, bar_a_y, bar_width, bar_height, radius,
                                    volume_a, volume_b, is_a_muted, is_b_muted, device_colour)

            self._composite_icon(image, icon_left_x, icon_bottom_y, icon_max_size)

            return image
        except Exception as img_e:
            log.error(f"Error creating image: {img_e}")
            log.error(traceback.format_exc())
            return None
    
    def _render_target_device(self, muted=False):
        """Render image for target device with single volume bar.

        Uses only the cached UI volume value for speed.
        """
        volume = getattr(self.action, "volume", 0) or 0
        
        try:
            image_width = 480
            image_height = 240
            
            image = Image.new('RGBA', (image_width, image_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            edge_padding = 10
            
            icon_max_size = 150
            icon_bottom_y = image_height - icon_max_size - edge_padding
            icon_left_x = edge_padding
            
            left_margin = icon_max_size + edge_padding + edge_padding
            right_margin = edge_padding
            bar_width = image_width - left_margin - right_margin
            bar_height = 24
            bar_x = left_margin
            bar_y = image_height - bar_height - edge_padding - 15
            
            display_volume = volume
            bar_fill_width = int((display_volume / 100.0) * bar_width)

            # Labels for volume and meter
            try:
                label_font = self._load_monospace_font(12)
            except Exception:
                label_font = ImageFont.load_default()

            draw.text((bar_x + 4, bar_y - 15), "VOL", fill=(204, 204, 204, 204), font=label_font)

            meter_label_y = bar_y + bar_height + 12
            draw.text((bar_x + 4, meter_label_y), "LVL", fill=(204, 204, 204, 204), font=label_font)

            if muted:
                bg_color = (38, 38, 38, 255)
                outline_color = (77, 77, 77, 255)
            else:
                bg_color = (20, 38, 20, 255)
                outline_color = (102, 204, 102, 255)

            radius = bar_height // 2

            self._draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height), radius, bg_color)

            self._draw_rounded_rect_outline(draw, (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height), radius, outline_color, 2)

            if bar_fill_width > 0:
                fill_color = (77, 77, 77, 255) if muted else (102, 255, 102, 255)
                fill_x1 = bar_x + 2
                fill_x2 = bar_x + min(bar_fill_width, bar_width - 2)
                fill_y1 = bar_y + 2
                fill_y2 = bar_y + bar_height - 2
                if fill_x2 > fill_x1 and not muted:
                    self._draw_gradient_bar(draw, fill_x1, fill_y1, fill_x2, fill_y2, fill_color, 2)
                elif fill_x2 > fill_x1:
                    self._draw_rounded_rect(draw, (fill_x1, fill_y1, fill_x2, fill_y2), max(0, radius - 2), fill_color)
            
            meter_value = self.action._current_meter_target
            if meter_value > 0 and bar_fill_width > 0:
                self._draw_animated_meter(draw, meter_value, bar_fill_width, bar_x, bar_width,
                                        bar_y + bar_height - 9, 6, radius)
            
            self._composite_icon(image, icon_left_x, icon_bottom_y, icon_max_size)

            return image
        except Exception as img_e:
            log.error(f"Error creating image: {img_e}")
            log.error(traceback.format_exc())
            return None
    
    def _draw_rounded_rect(self, draw, bbox, radius, fill):
        """Draw a rounded rectangle"""
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
    
    def _draw_rounded_rect_outline(self, draw, bbox, radius, outline, width=1):
        """Draw a rounded rectangle outline"""
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
    
    def _draw_volume_bar(self, draw, x, y, width, height, volume, is_muted, device_colour=None, fallback_color=(102, 179, 255, 255)):
        """Draw a single volume bar with gradient"""
        draw.rectangle([x, y, x + width, y + height], fill=(30, 30, 30, 255))
        draw.rectangle([x, y, x + width, y + height], outline=(60, 60, 60, 255), width=4)
        
        if volume > 0:
            fill_width = int((volume / 100.0) * width)
            fill_x = x + 4
            fill_x2 = x + min(fill_width, width - 4)
            fill_y = y + 4
            fill_y2 = y + height - 4
            
            if fill_x2 > fill_x:
                if is_muted:
                    draw.rectangle([fill_x, fill_y, fill_x2, fill_y2], fill=(77, 77, 77, 255))
                else:
                    if device_colour:
                        color = (device_colour['red'], device_colour['green'], device_colour['blue'], 255)
                    else:
                        color = fallback_color
                    # Simple solid fill instead of a multi-strip gradient for speed.
                    draw.rectangle([fill_x, fill_y, fill_x2, fill_y2], fill=color)
    
    def _draw_linked_volume_bars(self, draw, start_x, start_y, bar_width, bar_height, radius,
                                   volume_a, volume_b, is_a_muted, is_b_muted, device_colour=None):
        """Draw linked volume bars with device color"""
        bar_spacing = 8
        bar_a_y = start_y
        bar_b_y = start_y + bar_height + bar_spacing
        
        # Draw Mix A bar
        self._draw_volume_bar(draw, start_x, bar_a_y, bar_width, bar_height, 
                             volume_a, is_a_muted, device_colour, (102, 179, 255, 255))
        
        # Draw Mix B bar  
        self._draw_volume_bar(draw, start_x, bar_b_y, bar_width, bar_height,
                             volume_b, is_b_muted, device_colour, (255, 77, 77, 255))
        
        # Draw meters
        bar_a_fill_width = int((volume_a / 100.0) * bar_width)
        bar_b_fill_width = int((volume_b / 100.0) * bar_width)
        self._draw_unlinked_meters(draw, start_x, bar_width, bar_a_y, bar_b_y, bar_height,
                                  bar_a_fill_width, bar_b_fill_width, radius)
    
    def _draw_unlinked_volume_bars(self, draw, start_x, start_y, bar_width, bar_height, radius,
                                   volume_a, volume_b, is_a_muted, is_b_muted, device_colour=None):
        """Draw unlinked volume bars (two separate bars) with enhanced visibility"""
        bar_spacing = 8
        bar_a_y = start_y
        bar_b_y = start_y + bar_height + bar_spacing
        
        # Draw Mix A bar
        self._draw_volume_bar(draw, start_x, bar_a_y, bar_width, bar_height, 
                             volume_a, is_a_muted, device_colour, (102, 179, 255, 255))
        
        # Draw Mix B bar
        self._draw_volume_bar(draw, start_x, bar_b_y, bar_width, bar_height,
                             volume_b, is_b_muted, device_colour, (255, 77, 77, 255))
        
        # Draw meters
        bar_a_fill_width = int((volume_a / 100.0) * bar_width)
        bar_b_fill_width = int((volume_b / 100.0) * bar_width)
        self._draw_unlinked_meters(draw, start_x, bar_width, bar_a_y, bar_b_y, bar_height,
                                  bar_a_fill_width, bar_b_fill_width, radius)
    
    def _draw_unlinked_meters(self, draw, start_x, bar_width, bar_a_y, bar_b_y, bar_height,
                             bar_a_fill_width, bar_b_fill_width, radius):
        """Draw animated meter overlays for unlinked volume bars"""
        meter_a = self.action._current_meter_a
        meter_b = self.action._current_meter_b

        if meter_a > 0 and bar_a_fill_width > 0:
            self._draw_animated_meter(draw, meter_a, bar_a_fill_width, start_x, bar_width,
                                    bar_a_y + bar_height - 9, 6, radius)

        if meter_b > 0 and bar_b_fill_width > 0:
            self._draw_animated_meter(draw, meter_b, bar_b_fill_width, start_x, bar_width,
                                    bar_b_y + bar_height - 9, 6, radius)
    
    def _draw_animated_meter(self, draw, meter_value, fill_width, start_x, bar_width, meter_y, meter_height, radius):
        """Draw simple black meter bars"""
        if meter_value <= 0 or fill_width <= 0:
            return

        base_meter_width = int((meter_value / 100.0) * fill_width)
        meter_x1 = start_x
        meter_x2 = start_x + base_meter_width

        if meter_x2 <= meter_x1 or meter_y < 0:
            return

        edge_inset = 6
        meter_x1_inset = max(meter_x1, start_x + edge_inset)
        meter_x2_inset = min(meter_x2, start_x + bar_width - edge_inset)

        if meter_x2_inset > meter_x1_inset:
            draw.rectangle([meter_x1_inset, meter_y, meter_x2_inset, meter_y + meter_height], fill=(0, 0, 0, 255))

    def _composite_icon(self, image, icon_left_x, icon_bottom_y, icon_max_size):
        """Composite icon onto image if configured"""
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
            pass
    
    def _render_menu(self):
        """Render the interactive menu with 3 horizontal full-screen buttons"""
        image_width = 480
        image_height = 240
        image = Image.new("RGBA", (image_width, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Cached monospace font for button labels
        try:
            button_font = self._load_monospace_font(64)
        except Exception:
            button_font = ImageFont.load_default()

        margin = 15
        total_margins = margin * 4
        button_width = (image_width - total_margins) // 3
        button_height = (image_height - (margin * 2)) // 2
        start_x = margin
        start_y = image_height - button_height - margin
        
        buttons = [
            ("Link", "link", (100, 200, 100)),
            ("A", "bus_a", (102, 179, 255)),
            ("B", "bus_b", (255, 179, 77))
        ]
        
        for i, (label, action_key, color) in enumerate(buttons):
            x = start_x + i * (button_width + margin)
            y = start_y
            
            # Use cached link state from the action to avoid client calls during
            # rendering.
            if action_key == "link" and self.action.selected_device_id:
                is_linked = getattr(self.action, "_is_linked_cached", False)
                label = "Unlink" if is_linked else "Link"
            
            is_selected = False
            if action_key == "bus_a" and "A" in self.action.selected_mixes:
                is_selected = True
            elif action_key == "bus_b" and "B" in self.action.selected_mixes:
                is_selected = True
            elif action_key == "link" and self.action.selected_device_id:
                is_linked = self.action.client.is_volume_linked(self.action.selected_device_id)
                is_selected = is_linked
            
            if action_key == "bus_a":
                if is_selected:
                    bg_color = color + (255,)
                else:
                    bg_color = tuple(int(c * 0.6) for c in color) + (255,)
                outline_color = (51, 77, 128, 255)
            elif action_key == "bus_b":
                if is_selected:
                    bg_color = color + (255,)
                else:
                    bg_color = tuple(int(c * 0.6) for c in color) + (255,)
                outline_color = (128, 77, 26, 255)
            else:
                if is_selected:
                    bg_color = color + (255,)
                else:
                    bg_color = tuple(int(c * 0.6) for c in color) + (255,)
                outline_color = tuple(int(c * 0.9) for c in color) + (255,)
            
            radius = 10
            draw.rounded_rectangle([x, y, x + button_width, y + button_height], 
                                  radius=radius, fill=bg_color, outline=outline_color, width=2)
            
            if action_key == "link":
                icon_size = min(button_width - 20, button_height - 20)
                icon_x = x + (button_width - icon_size) // 2
                icon_y = y + (button_height - icon_size) // 2
                
                if self.action.selected_device_id:
                    is_linked = getattr(self.action, "_is_linked_cached", False)
                    icon_name = "linked-white.png" if is_linked else "unlinked-dimmed.png"
                else:
                    icon_name = "unlinked-dimmed.png"
                
                icon_path = self.action.plugin_base.get_asset_path(icon_name, ["icons"])
                cache_key = (icon_path, icon_size)
                cached_icon = self._icon_cache_local.get(cache_key)
                if cached_icon is None and os.path.exists(icon_path):
                    link_icon = Image.open(icon_path)
                    if link_icon.mode == 'P':
                        link_icon = link_icon.convert('RGBA')
                    elif link_icon.mode != 'RGBA':
                        link_icon = link_icon.convert('RGBA')
                    link_icon_resized = link_icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    cached_icon = link_icon_resized
                    self._icon_cache_local[cache_key] = cached_icon
                if cached_icon is not None:
                    image.paste(cached_icon, (icon_x, icon_y), cached_icon)
            else:
                # Center label text inside the button
                try:
                    text_bbox = draw.textbbox((0, 0), label, font=button_font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    text_x = x + (button_width - text_width) // 2
                    text_y = y + (button_height - text_height) // 2 - text_bbox[1]
                except Exception:
                    # Fallback: approximate centering without bbox
                    text_x = x + button_width // 4
                    text_y = y + button_height // 4

                draw.text((text_x, text_y), label, fill=(255, 255, 255, 255), font=button_font)
            button_info = {
                'x': x,
                'y': y,
                'width': button_width,
                'height': button_height,
                'action': action_key
            }
            self._menu_buttons.append(button_info)
        
        return image
    
    def _set_image_on_action(self, image):
        """Set the rendered image on the action"""
        try:
            image.load()
            self.action.set_media(image=image)
        except Exception as e:
            log.error(f"Error setting image: {e}")
            log.error(traceback.format_exc())
