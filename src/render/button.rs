//! Volume button renderer for Stream Deck keys (+/- buttons)

use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;
use image;

const LARGE_SYMBOL_RATIO: f32 = 0.5;
const LARGE_LINE_WIDTH_RATIO: f32 = 0.13;
const SMALL_SYMBOL_RATIO: f32 = 0.12;
const SMALL_LINE_WIDTH_RATIO: f32 = 0.04;
const CORNER_INSET_RATIO: f32 = 0.08;
const ICON_INSET_RATIO: f32 = 0.25;
const MIN_LINE_WIDTH: f32 = 2.0;
const MIN_CORNER_INSET: f32 = 4.0;

/// Volume button renderer (+/- buttons)
#[pyclass]
pub struct ButtonRenderer {
    button_size: u32,
}

#[pymethods]
impl ButtonRenderer {
    #[new]
    #[pyo3(signature = (button_size=72))]
    pub fn new(button_size: u32) -> Self {
        Self { button_size }
    }

    /// Render the volume button as PNG bytes
    ///
    /// Args:
    ///     is_plus: True for plus button, False for minus
    ///     icon_png: Optional PNG bytes for custom icon
    #[pyo3(signature = (is_plus=true, icon_png=None))]
    pub fn render(&self, is_plus: bool, icon_png: Option<Vec<u8>>) -> PyResult<Vec<u8>> {
        let pixmap = self
            .render_internal(is_plus, icon_png)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;

        pixmap_to_png(&pixmap)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode PNG"))
    }

    pub fn render_unavailable(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.button_size, self.button_size, COLOR_SERVICE_UNAVAILABLE_BG))
    }

    pub fn render_loading(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.button_size, self.button_size, COLOR_TRANSPARENT))
    }
}

impl ButtonRenderer {
    fn encode_pixmap(&self, pixmap: Option<Pixmap>) -> PyResult<Vec<u8>> {
        let pixmap = pixmap.ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;
        pixmap_to_png(&pixmap).ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode PNG"))
    }

    pub fn render_internal_png(&self, is_plus: bool, icon_png: Option<Vec<u8>>) -> Option<Vec<u8>> {
        pixmap_to_png(&self.render_internal(is_plus, icon_png)?)
    }

    pub fn render_unavailable_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.button_size, self.button_size, COLOR_SERVICE_UNAVAILABLE_BG)?)
    }

    pub fn render_loading_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.button_size, self.button_size, COLOR_TRANSPARENT)?)
    }

    fn render_internal(&self, is_plus: bool, icon_png: Option<Vec<u8>>) -> Option<Pixmap> {
        let size = self.button_size as f32;
        let mut pixmap = Pixmap::new(self.button_size, self.button_size)?;
        fill_background(&mut pixmap, COLOR_TRANSPARENT);

        let center = size / 2.0;
        let has_icon = icon_png.is_some();

        // Draw symbol: small in corner if custom icon, else large centered
        let (cx, cy, sym_size, line_width) = if has_icon {
            let inset = (size * CORNER_INSET_RATIO).max(MIN_CORNER_INSET);
            let sym = size * SMALL_SYMBOL_RATIO;
            (size - inset - sym / 2.0, size - inset - sym / 2.0, sym, (size * SMALL_LINE_WIDTH_RATIO).max(MIN_LINE_WIDTH))
        } else {
            (center, center, size * LARGE_SYMBOL_RATIO, (size * LARGE_LINE_WIDTH_RATIO).max(3.0))
        };
        draw_symbol(&mut pixmap, cx, cy, sym_size, line_width, COLOR_WHITE, is_plus);

        if let Some(png_data) = icon_png {
            self.composite_icon(&mut pixmap, &png_data);
        }
        Some(pixmap)
    }

    fn composite_icon(&self, pixmap: &mut Pixmap, png_data: &[u8]) {
        let size = self.button_size as f32;
        let inset = (size * ICON_INSET_RATIO).max(MIN_CORNER_INSET);
        let max_size = size - inset * 2.0;

        let Ok(img) = image::load_from_memory(png_data) else { return };
        let (iw, ih) = (img.width() as f32, img.height() as f32);
        let scale = (max_size / iw).min(max_size / ih).min(1.0);
        let (sw, sh) = ((iw * scale) as u32, (ih * scale) as u32);

        let resized = img.resize(sw, sh, image::imageops::FilterType::Lanczos3).to_rgba8();
        let (fx, fy) = (
            ((size - sw as f32) / 2.0) as i32,
            ((size - sh as f32) / 2.0) as i32,
        );

        // Alpha-blend each pixel
        for (ix, iy, pixel) in resized.enumerate_pixels() {
            let (px, py) = (fx + ix as i32, fy + iy as i32);
            if px < 0 || py < 0 || px >= self.button_size as i32 || py >= self.button_size as i32 {
                continue;
            }
            let src_a = pixel[3] as f32 / 255.0;
            if src_a == 0.0 { continue; }

            let idx = (py as usize * self.button_size as usize + px as usize) * 4;
            let data = pixmap.data_mut();
            if idx + 3 >= data.len() { continue; }

            let dst_a = data[idx + 3] as f32 / 255.0;
            let out_a = src_a + dst_a * (1.0 - src_a);
            if out_a > 0.0 {
                let blend = |s: u8, d: u8| ((s as f32 * src_a + d as f32 * dst_a * (1.0 - src_a)) / out_a) as u8;
                data[idx] = blend(pixel[0], data[idx]);
                data[idx + 1] = blend(pixel[1], data[idx + 1]);
                data[idx + 2] = blend(pixel[2], data[idx + 2]);
                data[idx + 3] = (out_a * 255.0) as u8;
            }
        }
    }
}
