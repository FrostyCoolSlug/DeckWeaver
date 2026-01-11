//! Icon loading and conversion utilities

use image::{imageops::FilterType, ImageEncoder};
use pyo3::prelude::*;
use resvg::{tiny_skia, usvg};
use std::fs;
use std::path::Path;

const DEFAULT_ICON_SIZE: u32 = 200;
const MIN_ICON_SIZE: u32 = 200;

/// Load an icon file and convert it to PNG bytes
/// 
/// Supports:
/// - SVG files (rendered to PNG using resvg)
/// - PNG, JPEG, GIF, WebP, BMP, and other formats (via image crate)
/// 
/// Icons smaller than 200px are scaled up to maintain quality.
#[pyfunction]
pub fn load_icon_to_png(path: &str) -> PyResult<Option<Vec<u8>>> {
    let path_obj = Path::new(path);
    
    // Check if file exists
    if !path_obj.exists() {
        return Ok(None);
    }
    
    // Handle SVG files
    if path_obj.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("svg"))
        .unwrap_or(false)
    {
        return load_svg_to_png(path);
    }
    
    // Handle other image formats
    load_image_to_png(path)
}

/// Load and convert SVG to PNG
fn load_svg_to_png(path: &str) -> PyResult<Option<Vec<u8>>> {
    let svg_data = match fs::read(path) {
        Ok(data) => data,
        Err(e) => {
            tracing::warn!("Failed to read SVG file {}: {}", path, e);
            return Ok(None);
        }
    };
    
    // Parse SVG
    let opt = usvg::Options::default();
    let tree = match usvg::Tree::from_data(&svg_data, &opt) {
        Ok(tree) => tree,
        Err(e) => {
            tracing::warn!("Failed to parse SVG {}: {}", path, e);
            return Ok(None);
        }
    };
    
    let size = tree.size();
    let (target_width, target_height, scale_x, scale_y) = if size.width() > 0.0 && size.height() > 0.0 {
        let max_dim = size.width().max(size.height());
        let scale = DEFAULT_ICON_SIZE as f32 / max_dim;
        let tw = (size.width() * scale) as u32;
        let th = (size.height() * scale) as u32;
        let sx = tw as f32 / size.width();
        let sy = th as f32 / size.height();
        (tw, th, sx, sy)
    } else {
        (DEFAULT_ICON_SIZE, DEFAULT_ICON_SIZE, 1.0, 1.0)
    };
    
    // Render to pixmap
    let mut pixmap = match tiny_skia::Pixmap::new(target_width, target_height) {
        Some(pixmap) => pixmap,
        None => {
            tracing::warn!("Failed to create pixmap for SVG {}", path);
            return Ok(None);
        }
    };
    
    // Calculate transform to scale SVG to target size
    let transform = tiny_skia::Transform::from_scale(scale_x, scale_y);
    
    // Render SVG using resvg
    resvg::render(&tree, transform, &mut pixmap.as_mut());
    
    // Encode as PNG
    match pixmap.encode_png() {
        Ok(png_data) => Ok(Some(png_data)),
        Err(e) => {
            tracing::warn!("Failed to encode SVG as PNG {}: {}", path, e);
            Ok(None)
        }
    }
}

/// Load and convert image file to PNG
fn load_image_to_png(path: &str) -> PyResult<Option<Vec<u8>>> {
    // Load image
    let img = match image::open(path) {
        Ok(img) => img,
        Err(e) => {
            tracing::warn!("Failed to load image {}: {}", path, e);
            return Ok(None);
        }
    };
    
    // Convert to RGBA
    let rgba_img = img.to_rgba8();
    
    // Scale up if needed
    let (width, height) = rgba_img.dimensions();
    let max_dim = width.max(height);
    
    let final_img = if max_dim < MIN_ICON_SIZE {
        // Scale up small icons
        let scale = MIN_ICON_SIZE as f32 / max_dim as f32;
        let new_width = (width as f32 * scale) as u32;
        let new_height = (height as f32 * scale) as u32;
        image::imageops::resize(&rgba_img, new_width, new_height, FilterType::Lanczos3)
    } else {
        rgba_img
    };
    
    // Encode as PNG
    let mut png_data = Vec::new();
    {
        let encoder = image::codecs::png::PngEncoder::new(&mut png_data);
        if let Err(e) = encoder.write_image(
            &final_img,
            final_img.width(),
            final_img.height(),
            image::ColorType::Rgba8.into(),
        ) {
            tracing::warn!("Failed to encode image as PNG {}: {}", path, e);
            return Ok(None);
        }
    }
    
    Ok(Some(png_data))
}
