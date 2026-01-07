"""Volume button rendering for PipeWeaver vol+ and vol- buttons"""
from typing import Final, Optional

import cairo  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .render_helpers import (
    create_cairo_surface,
    cairo_to_pil,
    set_cairo_color,
    render_service_unavailable_button,
    render_loading_button,
    set_image_on_action,
    get_button_size_from_action,
)
from .service_monitor import is_service_available

LARGE_SYMBOL_SIZE_RATIO: Final[float] = 0.5
LARGE_SYMBOL_LINE_WIDTH_RATIO: Final[float] = 0.13
SMALL_SYMBOL_SIZE_RATIO: Final[float] = 0.12
SMALL_SYMBOL_LINE_WIDTH_RATIO: Final[float] = 0.04
CORNER_SYMBOL_INSET_RATIO: Final[float] = 0.08
CUSTOM_ICON_INSET_RATIO: Final[float] = 0.25
MIN_LINE_WIDTH: Final[int] = 2
MIN_CORNER_INSET: Final[int] = 4


class VolumeButtonRenderer:
    def __init__(self, action, is_plus: bool):
        self.action = action
        self.is_plus = is_plus
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
            image = self._render_button()
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
            log.error(f"Error drawing button: {e}")
            try:
                fallback_image = render_service_unavailable_button(self.button_size)
                if fallback_image:
                    set_image_on_action(self.action, fallback_image)
            except Exception:
                pass
    
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
            surface, ctx = create_cairo_surface(size, size)
            
            # Black background
            set_cairo_color(ctx, (0, 0, 0, 255))
            ctx.rectangle(0, 0, size, size)
            ctx.fill()
            
            # Check if custom icon exists
            custom_icon = self.action._get_icon()
            has_custom_icon = custom_icon is not None and isinstance(custom_icon, Image.Image)
            
            # Draw plus/minus symbol using layout constants
            set_cairo_color(ctx, (255, 255, 255, 255))
            
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
            image = cairo_to_pil(surface)
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
    
