"""Simple SVG to PIL converter using cairosvg"""
import os
import io
from typing import Optional

import cairosvg  # type: ignore
from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

from .constants import SVG_DEFAULT_SIZE, SVG_PADDING


def svg_to_pil(svg_path: str, size: tuple[int, int] = SVG_DEFAULT_SIZE) -> Optional[Image.Image]:
    if not os.path.exists(svg_path):
        return None
    
    try:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        png_data = cairosvg.svg2png(
            bytestring=svg_content.encode('utf-8'),
            output_width=size[0],
            output_height=size[1],
            background_color='transparent'
        )
        
        image = Image.open(io.BytesIO(png_data))
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        return _crop_and_pad(image, padding=SVG_PADDING)
    except Exception as e:
        log.error(f"Error converting SVG to PIL: {e}")
        return None


def _crop_and_pad(image: Image.Image, padding: int = SVG_PADDING) -> Image.Image:
    try:
        bbox = image.getbbox()
        if bbox is None:
            return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        
        cropped = image.crop(bbox)
        width, height = cropped.size
        padded_image = Image.new('RGBA', (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
        bottom_y = padded_image.height - height - padding
        padded_image.paste(cropped, (padding, bottom_y))
        return padded_image
    except Exception:
        return image


def is_svg_file(file_path: str) -> bool:
    return file_path.lower().endswith('.svg')
