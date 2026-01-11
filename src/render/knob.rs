//! Knob/dial renderer for Stream Deck Plus touchscreen

use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;

const EDGE_PADDING: f32 = 10.0;
const CORNER_INSET: f32 = 14.0;
const ICON_MAX_SIZE: f32 = 52.0;
const BAR_HEIGHT: f32 = 14.0;
const BAR_OFFSET_Y: f32 = 5.0;
const METER_HEIGHT: f32 = 4.0;
const METER_MARGIN_X: f32 = 5.0;
const STROKE_WIDTH: f32 = 2.0;

/// Knob renderer for dial touchscreen display
#[pyclass]
pub struct KnobRenderer {
    width: u32,
    height: u32,
}

#[pymethods]
impl KnobRenderer {
    #[new]
    #[pyo3(signature = (width=200, height=100))]
    pub fn new(width: u32, height: u32) -> Self {
        Self { width, height }
    }

    #[pyo3(signature = (
        volume,
        is_muted=false,
        is_source=true,
        meter_value=0,
        device_color=None,
        volume_bar_color=None,
        meter_color=None,
        meter_invert=true,
        meters_enabled=true,
        icon_png=None
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn render(
        &self,
        volume: u8,
        is_muted: bool,
        is_source: bool,
        meter_value: u8,
        device_color: Option<(u8, u8, u8)>,
        volume_bar_color: Option<(u8, u8, u8, u8)>,
        meter_color: Option<(u8, u8, u8, u8)>,
        meter_invert: bool,
        meters_enabled: bool,
        icon_png: Option<Vec<u8>>,
    ) -> PyResult<Vec<u8>> {
        let params = RenderParams {
            volume, is_muted, is_source, meter_value, device_color,
            volume_bar_color, meter_color, meter_invert, meters_enabled,
        };
        self.encode_pixmap(self.render_internal(&params, icon_png))
    }

    pub fn render_unavailable(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.width, self.height, COLOR_SERVICE_UNAVAILABLE_BG))
    }

    pub fn render_loading(&self) -> PyResult<Vec<u8>> {
        self.encode_pixmap(create_filled_pixmap(self.width, self.height, COLOR_TRANSPARENT))
    }
}

impl KnobRenderer {
    fn encode_pixmap(&self, pixmap: Option<Pixmap>) -> PyResult<Vec<u8>> {
        let pixmap = pixmap.ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;
        pixmap_to_png(&pixmap).ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode PNG"))
    }

    pub fn render_internal_png(&self, params: &RenderParams, icon_png: Option<Vec<u8>>) -> Option<Vec<u8>> {
        pixmap_to_png(&self.render_internal(params, icon_png)?)
    }

    pub fn render_unavailable_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.width, self.height, COLOR_SERVICE_UNAVAILABLE_BG)?)
    }

    pub fn render_loading_internal(&self) -> Option<Vec<u8>> {
        pixmap_to_png(&create_filled_pixmap(self.width, self.height, COLOR_TRANSPARENT)?)
    }

    fn render_internal(&self, params: &RenderParams, icon_png: Option<Vec<u8>>) -> Option<Pixmap> {
        let (w, h) = (self.width as f32, self.height as f32);
        let mut pixmap = Pixmap::new(self.width, self.height)?;
        fill_background(&mut pixmap, COLOR_TRANSPARENT);

        // Layout
        let icon_x = CORNER_INSET;
        let icon_y = h - ICON_MAX_SIZE - CORNER_INSET;
        let bar_x = icon_x + ICON_MAX_SIZE + EDGE_PADDING;
        let bar_w = w - bar_x - CORNER_INSET;
        let bar_y = h - BAR_HEIGHT - CORNER_INSET - BAR_OFFSET_Y;
        let bar_radius = BAR_HEIGHT / 2.0;

        let fill_color = params.fill_color();
        let fill_width = (params.volume as f32 / 100.0) * bar_w;

        // Gutter
        let bar = Rect::new(bar_x, bar_y, bar_w, BAR_HEIGHT, bar_radius);
        bar.draw_filled(&mut pixmap, gutter_color_for(fill_color));

        // Volume fill
        if let Some(color) = fill_color {
            if fill_width > 0.0 {
                Rect::new(bar_x, bar_y, fill_width, BAR_HEIGHT, bar_radius).draw_filled(&mut pixmap, color);
            }
        }

        // Stroke
        bar.draw_stroked(&mut pixmap, COLOR_BLACK, STROKE_WIDTH);

        // Meter overlay
        if params.meters_enabled && params.meter_value > 0 && fill_width > 0.0 {
            if let Some(fc) = fill_color {
                let available = fill_width - METER_MARGIN_X * 2.0;
                if available > 0.0 {
                    let meter_w = (params.meter_value as f32 / 100.0) * available;
                    let meter_y = bar_y + (BAR_HEIGHT - METER_HEIGHT) / 2.0;
                    let meter_color = if params.meter_invert {
                        fc.invert()
                    } else {
                        params.meter_color.map(Rgba::from).unwrap_or(COLOR_BLACK)
                    };
                    Rect::new(bar_x + METER_MARGIN_X, meter_y, meter_w, METER_HEIGHT, METER_HEIGHT / 2.0)
                        .draw_filled(&mut pixmap, meter_color);
                }
            }
        }

        // Icon
        if let Some(png_data) = icon_png {
            self.composite_icon(&mut pixmap, &png_data, icon_x, icon_y);
        }

        // Mute indicator
        if params.is_muted {
            draw_diagonal_line(&mut pixmap, icon_x, icon_y + ICON_MAX_SIZE, icon_x + ICON_MAX_SIZE, icon_y, 6.0, COLOR_RED);
        }

        Some(pixmap)
    }

    fn composite_icon(&self, pixmap: &mut Pixmap, png_data: &[u8], x: f32, y: f32) {
        let Ok(img) = image::load_from_memory(png_data) else { return };

        let (iw, ih) = (img.width() as f32, img.height() as f32);
        let scale = (ICON_MAX_SIZE / iw).min(ICON_MAX_SIZE / ih).min(1.0);
        let (sw, sh) = ((iw * scale) as u32, (ih * scale) as u32);

        let resized = img.resize(sw, sh, image::imageops::FilterType::Lanczos3).to_rgba8();
        let (fx, fy) = (
            (x + (ICON_MAX_SIZE - sw as f32) / 2.0) as i32,
            (y + (ICON_MAX_SIZE - sh as f32) / 2.0) as i32,
        );

        // Alpha-blend each pixel
        for (ix, iy, pixel) in resized.enumerate_pixels() {
            let (px, py) = (fx + ix as i32, fy + iy as i32);
            if px < 0 || py < 0 || px >= self.width as i32 || py >= self.height as i32 {
                continue;
            }
            let src_a = pixel[3] as f32 / 255.0;
            if src_a == 0.0 { continue; }

            let idx = (py as usize * self.width as usize + px as usize) * 4;
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
