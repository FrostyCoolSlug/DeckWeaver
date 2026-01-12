//! Slider button renderer for Stream Deck keys

use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;

const CORNER_INSET: f32 = 10.0;
const BAR_WIDTH: f32 = 25.0;
const BAR_OFFSET_Y: f32 = 3.0;
const METER_WIDTH: f32 = 11.0;
const METER_MARGIN_Y: f32 = 2.0;
const STROKE_WIDTH: f32 = 2.0;

/// Slider button renderer - creates top/bottom half of a virtual slider
#[pyclass]
pub struct SliderRenderer {
    button_size: u32,
}

#[pymethods]
impl SliderRenderer {
    #[new]
    #[pyo3(signature = (button_size=72))]
    pub fn new(button_size: u32) -> Self {
        Self { button_size }
    }

    #[pyo3(signature = (
        volume,
        is_top=true,
        is_source=true,
        is_horizontal=false,
        meter_value=0,
        device_color=None,
        volume_bar_color=None,
        meter_color=None,
        meter_invert=true,
        meters_enabled=true
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn render(
        &self,
        volume: u8,
        is_top: bool,
        is_source: bool,
        is_horizontal: bool,
        meter_value: u8,
        device_color: Option<(u8, u8, u8)>,
        volume_bar_color: Option<(u8, u8, u8, u8)>,
        meter_color: Option<(u8, u8, u8, u8)>,
        meter_invert: bool,
        meters_enabled: bool,
    ) -> PyResult<Vec<u8>> {
        let params = RenderParams {
            volume, is_muted: false, is_source, meter_value, device_color,
            volume_bar_color, meter_color, meter_invert, meters_enabled,
        };
        self.encode_pixmap(self.render_internal(&params, is_top, is_horizontal))
    }

    pub fn render_unavailable(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.button_size, self.button_size, COLOR_SERVICE_UNAVAILABLE_BG))
    }

    pub fn render_loading(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.button_size, self.button_size, COLOR_TRANSPARENT))
    }
}

impl SliderRenderer {
    fn encode_pixmap(&self, pixmap: Option<Pixmap>) -> PyResult<Vec<u8>> {
        let pixmap = pixmap.ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;
        pixmap_to_png(&pixmap).ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode PNG"))
    }

    pub fn render_internal_png(&self, params: &RenderParams, is_top: bool, is_horizontal: bool) -> Option<Vec<u8>> {
        pixmap_to_png(&self.render_internal(params, is_top, is_horizontal)?)
    }

    pub fn render_unavailable_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.button_size, self.button_size, COLOR_SERVICE_UNAVAILABLE_BG)?)
    }

    pub fn render_loading_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.button_size, self.button_size, COLOR_TRANSPARENT)?)
    }

    fn render_internal(&self, params: &RenderParams, is_top: bool, is_horizontal: bool) -> Option<Pixmap> {
        let size = self.button_size as f32;
        let double_h = size * 2.0;

        let mut full = Pixmap::new(self.button_size, self.button_size * 2)?;
        fill_background(&mut full, COLOR_TRANSPARENT);

        // Layout
        let slider_y = CORNER_INSET + BAR_OFFSET_Y;
        let slider_h = double_h - CORNER_INSET * 2.0 - BAR_OFFSET_Y;
        let slider_x = (size - BAR_WIDTH) / 2.0;

        let fill_color = params.fill_color();
        let fill_h = (params.volume as f32 / 100.0) * slider_h;

        // Calculate half-circle radius for gutter (always full height)
        let gutter_radius = (BAR_WIDTH / 2.0).min(slider_h / 2.0);
        
        // Gutter
        let bar = Rect::new(slider_x, slider_y, BAR_WIDTH, slider_h, gutter_radius);
        bar.draw_filled(&mut full, gutter_color_for(fill_color));

        // Volume fill (from bottom) - half-circle radius
        let fill_radius = (BAR_WIDTH / 2.0).min(fill_h / 2.0);
        if let Some(color) = fill_color {
            if fill_h > 0.0 {
                Rect::new(slider_x, slider_y + slider_h - fill_h, BAR_WIDTH, fill_h, fill_radius)
                    .draw_filled(&mut full, color);
            }
        }

        // Stroke
        bar.draw_stroked(&mut full, COLOR_BLACK, STROKE_WIDTH);

        // Meter overlay - half-circle radius (always starts from bottom before rotation)
        if params.meters_enabled && params.meter_value > 0 && fill_h > 0.0 {
            if let Some(fc) = fill_color {
                let fill_y = slider_y + slider_h - fill_h;
                // Meter offset from edge (same for both orientations before rotation)
                let meter_offset = METER_MARGIN_Y * 4.0;
                // Meter horizontal position (centers meter in bar width)
                let meter_x = slider_x + (BAR_WIDTH - METER_WIDTH) / 2.0;
                let available = fill_h - meter_offset * 2.0;
                if available > 0.0 {
                    let meter_h = (params.meter_value as f32 / 100.0) * available;
                    // Always start from bottom - rotation handles horizontal orientation
                    let meter_y = fill_y + meter_offset + available - meter_h;
                    let meter_radius = (METER_WIDTH / 2.0).min(meter_h / 2.0);
                    let meter_color = if params.meter_invert {
                        fc.invert()
                    } else {
                        params.meter_color.map(Rgba::from).unwrap_or(COLOR_BLACK)
                    };
                    Rect::new(meter_x, meter_y, METER_WIDTH, meter_h, meter_radius)
                        .draw_filled(&mut full, meter_color);
                }
            }
        }

        // Crop to half
        let mut result = Pixmap::new(self.button_size, self.button_size)?;
        let y_off = if is_top { 0 } else { self.button_size as usize };
        let row_bytes = self.button_size as usize * 4;

        for y in 0..self.button_size as usize {
            let src = (y + y_off) * row_bytes;
            let dst = y * row_bytes;
            result.data_mut()[dst..dst + row_bytes].copy_from_slice(&full.data()[src..src + row_bytes]);
        }

        if is_horizontal { self.rotate_cw(&result) } else { Some(result) }
    }

    fn rotate_cw(&self, pixmap: &Pixmap) -> Option<Pixmap> {
        let (w, h) = (pixmap.width(), pixmap.height());
        let mut rotated = Pixmap::new(h, w)?;
        let (src, dst) = (pixmap.data(), rotated.data_mut());

        for y in 0..h {
            for x in 0..w {
                let si = ((y * w + x) * 4) as usize;
                let di = ((x * h + (h - 1 - y)) * 4) as usize;
                dst[di..di + 4].copy_from_slice(&src[si..si + 4]);
            }
        }
        Some(rotated)
    }
}
