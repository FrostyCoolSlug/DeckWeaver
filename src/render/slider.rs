use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;

const CORNER_INSET: f32 = 16.0;
const BAR_WIDTH: f32 = 25.0;
const BAR_OFFSET_Y: f32 = 0.0;
const STROKE_WIDTH: f32 = 2.0;
const METER_LIGHTEN_AMOUNT: f32 = 0.42;
const PANEL_INSET: f32 = 4.0;
const PANEL_RADIUS: f32 = 0.0;
const COLOR_PANEL_BASE: Rgba = Rgba::rgb(45, 50, 48);

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
    ) -> PyResult<(Vec<u8>, u32, u32)> {
        let params = RenderParams {
            volume,
            is_muted: false,
            is_source,
            meter_value,
            device_color,
            volume_bar_color,
            meter_color,
            meter_invert,
            meters_enabled,
            mix_b_active: false,
            source_mute_a: false,
            source_mute_b: false,
            source_mute_a_all: false,
            source_mute_b_all: false,
            source_mute_a_target_count: 0,
            source_mute_b_target_count: 0,
            source_volumes_linked: false,
            show_action_page: false,
        };
        self.encode_pixmap(self.render_internal(&params, is_top, is_horizontal))
    }

    pub fn render_unavailable(&self) -> PyResult<(Vec<u8>, u32, u32)> {
        self.encode_pixmap(create_unavailable_pixmap(
            self.button_size,
            self.button_size,
        ))
    }

    pub fn render_loading(&self) -> PyResult<(Vec<u8>, u32, u32)> {
        let params = RenderParams {
            volume: 0,
            is_muted: false,
            is_source: false,
            meter_value: 0,
            device_color: None,
            volume_bar_color: None,
            meter_color: None,
            meter_invert: true,
            meters_enabled: false,
            mix_b_active: false,
            source_mute_a: false,
            source_mute_b: false,
            source_mute_a_all: false,
            source_mute_b_all: false,
            source_mute_a_target_count: 0,
            source_mute_b_target_count: 0,
            source_volumes_linked: false,
            show_action_page: false,
        };
        self.encode_pixmap(self.render_internal(&params, true, false))
    }
}

impl SliderRenderer {
    fn encode_pixmap(&self, pixmap: Option<Pixmap>) -> PyResult<(Vec<u8>, u32, u32)> {
        let pixmap =
            pixmap.ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;
        pixmap_to_rgba(&pixmap)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode RGBA"))
    }

    pub fn render_internal_png(
        &self,
        params: &RenderParams,
        is_top: bool,
        is_horizontal: bool,
    ) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&self.render_internal(params, is_top, is_horizontal)?)
    }

    pub fn render_unavailable_internal(&self) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&create_unavailable_pixmap(
            self.button_size,
            self.button_size,
        )?)
    }

    pub fn render_loading_internal(&self) -> Option<(Vec<u8>, u32, u32)> {
        let params = RenderParams {
            volume: 0,
            is_muted: false,
            is_source: false,
            meter_value: 0,
            device_color: None,
            volume_bar_color: None,
            meter_color: None,
            meter_invert: true,
            meters_enabled: false,
            mix_b_active: false,
            source_mute_a: false,
            source_mute_b: false,
            source_mute_a_all: false,
            source_mute_b_all: false,
            source_mute_a_target_count: 0,
            source_mute_b_target_count: 0,
            source_volumes_linked: false,
            show_action_page: false,
        };
        pixmap_to_rgba(&self.render_internal(&params, true, false)?)
    }

    fn render_internal(
        &self,
        params: &RenderParams,
        is_top: bool,
        is_horizontal: bool,
    ) -> Option<Pixmap> {
        if is_horizontal {
            let mut background = self.render_single_panel(params)?;
            let mut bars = Pixmap::new(self.button_size, self.button_size * 2)?;
            fill_background(&mut bars, COLOR_TRANSPARENT);
            self.draw_slider_stack(&mut bars, params);
            if params.meters_enabled && params.meter_value > 0 {
                self.render_meter_overlay(&mut bars, params);
            }
            let cropped = self.extract_square(&bars, is_top)?;
            let rotated = self.rotate_cw(&cropped)?;
            blend_pixmap(&mut background, &rotated, 0, 0);
            return Some(background);
        }

        let mut full = self.render_base(params)?;
        if params.meters_enabled && params.meter_value > 0 {
            self.render_meter_overlay(&mut full, params);
        }
        self.extract_square(&full, is_top)
    }

    pub fn render_base(&self, params: &RenderParams) -> Option<Pixmap> {
        let mut full = self.render_panel_stack(params)?;
        self.draw_slider_stack(&mut full, params);
        Some(full)
    }

    pub fn render_meter_overlay(&self, full: &mut Pixmap, params: &RenderParams) {
        let size = self.button_size as f32;
        let double_h = size * 2.0;
        let slider_y = CORNER_INSET + BAR_OFFSET_Y;
        let slider_h = double_h - CORNER_INSET * 2.0 - BAR_OFFSET_Y;
        let slider_x = (size - BAR_WIDTH) / 2.0;
        let inset = STROKE_WIDTH * 0.5;
        let inner_x = slider_x + inset;
        let inner_w = (BAR_WIDTH - inset * 2.0).max(0.0);

        let fill_color = params.fill_color();
        let fill_h = (params.volume as f32 / 100.0) * slider_h;

        if params.meter_value > 0 && fill_h > 0.0 {
            if let Some(fc) = fill_color {
                let fill_y = slider_y + slider_h - fill_h;
                let available = (fill_h - inset * 2.0).max(0.0);
                if available > 0.0 {
                    let meter_h = (params.meter_value as f32 / 100.0) * available;
                    let meter_y = fill_y + inset + available - meter_h;
                    let meter_color = fc.blend(COLOR_WHITE, METER_LIGHTEN_AMOUNT);
                    Rect::new(inner_x, meter_y, inner_w, meter_h, 0.0)
                        .draw_filled(full, meter_color);
                }
            }
        }
    }

    pub fn rotate_cw(&self, pixmap: &Pixmap) -> Option<Pixmap> {
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

    fn render_panel_stack(&self, params: &RenderParams) -> Option<Pixmap> {
        let size = self.button_size as f32;
        let mut full = Pixmap::new(self.button_size, self.button_size * 2)?;
        fill_background(&mut full, COLOR_TRANSPARENT);

        let panel_w = size - PANEL_INSET * 2.0;
        let panel_h = size - PANEL_INSET * 2.0;
        let top_panel = Rect::new(PANEL_INSET, PANEL_INSET, panel_w, panel_h, PANEL_RADIUS);
        let bottom_panel = Rect::new(
            PANEL_INSET,
            size + PANEL_INSET,
            panel_w,
            panel_h,
            PANEL_RADIUS,
        );
        let accent = params.accent_color();
        let gradient_start = top_panel.y;
        let gradient_end = bottom_panel.y + bottom_panel.h;
        let gradient_span = (gradient_end - gradient_start).max(1.0);
        let gradient_bottom = accent.with_alpha(77);

        for panel in [top_panel, bottom_panel] {
            panel.draw_filled(&mut full, COLOR_PANEL_BASE);
            let top_t = ((panel.y - gradient_start) / gradient_span).clamp(0.0, 1.0);
            let bottom_t = ((panel.y + panel.h - gradient_start) / gradient_span).clamp(0.0, 1.0);
            panel.draw_vertical_gradient_filled(
                &mut full,
                COLOR_TRANSPARENT.blend(gradient_bottom, top_t),
                COLOR_TRANSPARENT.blend(gradient_bottom, bottom_t),
            );
        }

        Some(full)
    }

    fn render_single_panel(&self, params: &RenderParams) -> Option<Pixmap> {
        let size = self.button_size as f32;
        let mut panel = Pixmap::new(self.button_size, self.button_size)?;
        fill_background(&mut panel, COLOR_TRANSPARENT);

        let background = Rect::new(
            PANEL_INSET,
            PANEL_INSET,
            size - PANEL_INSET * 2.0,
            size - PANEL_INSET * 2.0,
            PANEL_RADIUS,
        );
        background.draw_filled(&mut panel, COLOR_PANEL_BASE);
        background.draw_vertical_gradient_filled(
            &mut panel,
            COLOR_TRANSPARENT,
            params.accent_color().with_alpha(77),
        );

        Some(panel)
    }

    fn draw_slider_stack(&self, pixmap: &mut Pixmap, params: &RenderParams) {
        let size = self.button_size as f32;
        let double_h = size * 2.0;
        let slider_y = CORNER_INSET + BAR_OFFSET_Y;
        let slider_h = double_h - CORNER_INSET * 2.0 - BAR_OFFSET_Y;
        let slider_x = (size - BAR_WIDTH) / 2.0;

        let fill_color = params.fill_color();
        let fill_h = (params.volume as f32 / 100.0) * slider_h;
        let bar = Rect::new(slider_x, slider_y, BAR_WIDTH, slider_h, 0.0);
        bar.draw_filled(pixmap, gutter_color_for(fill_color));

        if let Some(color) = fill_color {
            if fill_h > 0.0 {
                Rect::new(
                    slider_x,
                    slider_y + slider_h - fill_h,
                    BAR_WIDTH,
                    fill_h,
                    0.0,
                )
                .draw_filled(pixmap, color);
            }
        }

        bar.draw_stroked(pixmap, COLOR_BLACK, STROKE_WIDTH);
    }

    fn extract_square(&self, pixmap: &Pixmap, is_top: bool) -> Option<Pixmap> {
        let mut result = Pixmap::new(self.button_size, self.button_size)?;
        let y_off = if is_top { 0 } else { self.button_size as usize };
        let row_bytes = self.button_size as usize * 4;

        for y in 0..self.button_size as usize {
            let src = (y + y_off) * row_bytes;
            let dst = y * row_bytes;
            result.data_mut()[dst..dst + row_bytes]
                .copy_from_slice(&pixmap.data()[src..src + row_bytes]);
        }

        Some(result)
    }
}
