use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;

const DESIGN_WIDTH: f32 = 200.0;
const DESIGN_HEIGHT: f32 = 100.0;
const ICON_MAX_SIZE: f32 = 52.0;
const BAR_HEIGHT: f32 = 14.0;
const STROKE_WIDTH: f32 = 2.0;
const METER_LIGHTEN_AMOUNT: f32 = 0.42;
const MIX_LABEL_X: f32 = 144.0;
const MIX_LABEL_Y: f32 = 10.0;
const MIX_LABEL_W: f32 = 46.0;
const MIX_LABEL_H: f32 = 18.0;
const PANEL_INSET: f32 = 4.0;
const SOURCE_PANEL_X: f32 = PANEL_INSET;
const SOURCE_PANEL_Y: f32 = PANEL_INSET;
const SOURCE_PANEL_RADIUS: f32 = 0.0;
const SOURCE_BAR_X: f32 = 20.0;
const SOURCE_BAR_Y: f32 = 74.0;
const SOURCE_ICON_Y: f32 = 16.0;
const PAGE_MARGIN_X: f32 = 10.0;
const PAGE_SOURCE_BUTTON_W: f32 = 56.0;
const PAGE_SOURCE_BUTTON_H: f32 = 38.0;
const PAGE_TARGET_BUTTON_W: f32 = 56.0;
const PAGE_TARGET_BUTTON_H: f32 = 56.0;
const PAGE_SOURCE_TOP_Y: f32 = 9.0;
const PAGE_SOURCE_BOTTOM_Y: f32 = 53.0;
const PAGE_COL_2_X: f32 = 72.0;
const PAGE_COL_3_X: f32 = 134.0;
const PAGE_TARGET_Y: f32 = 22.0;
const PAGE_TARGET_COL_2_X: f32 = 72.0;
const PAGE_TARGET_COL_3_X: f32 = 134.0;
const COLOR_MIX_A: Rgba = Rgba::rgb(106, 196, 205);
const COLOR_MIX_B: Rgba = Rgba::rgb(242, 146, 44);
const COLOR_PANEL_SLOT: Rgba = Rgba::rgb(40, 43, 41);
const COLOR_BUTTON_IDLE: Rgba = Rgba::rgb(58, 61, 58);
const COLOR_MUTE: Rgba = Rgba::rgb(237, 90, 72);
const COLOR_LINK_ACTIVE: Rgba = Rgba::rgb(238, 238, 238);
const COLOR_PANEL_BASE: Rgba = Rgba::rgb(45, 50, 48);

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
    ) -> PyResult<(Vec<u8>, u32, u32)> {
        let params = RenderParams {
            volume,
            is_muted,
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
        self.encode_pixmap(self.render_internal(&params, icon_png, None))
    }

    pub fn render_unavailable(&self) -> PyResult<(Vec<u8>, u32, u32)> {
        self.encode_pixmap(create_unavailable_pixmap(self.width, self.height))
    }

    pub fn render_loading(&self) -> PyResult<(Vec<u8>, u32, u32)> {
        self.encode_pixmap(create_filled_pixmap(
            self.width,
            self.height,
            COLOR_TRANSPARENT,
        ))
    }
}

impl KnobRenderer {
    fn scale_x(&self, value: f32) -> f32 {
        value * (self.width as f32 / DESIGN_WIDTH)
    }

    fn scale_y(&self, value: f32) -> f32 {
        value * (self.height as f32 / DESIGN_HEIGHT)
    }

    fn scale_uniform(&self, value: f32) -> f32 {
        value * (self.width as f32 / DESIGN_WIDTH).min(self.height as f32 / DESIGN_HEIGHT)
    }

    fn scale_rect(&self, x: f32, y: f32, w: f32, h: f32, radius: f32) -> Rect {
        Rect::new(
            self.scale_x(x),
            self.scale_y(y),
            self.scale_x(w),
            self.scale_y(h),
            self.scale_uniform(radius),
        )
    }

    fn encode_pixmap(&self, pixmap: Option<Pixmap>) -> PyResult<(Vec<u8>, u32, u32)> {
        let pixmap =
            pixmap.ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to render"))?;
        pixmap_to_rgba(&pixmap)
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("Failed to encode RGBA"))
    }

    pub fn render_internal_png(
        &self,
        params: &RenderParams,
        icon_png: Option<Vec<u8>>,
    ) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&self.render_internal(params, icon_png, None)?)
    }

    pub fn render_internal_png_with_cached(
        &self,
        params: &RenderParams,
        cached_icon: Option<&crate::action::CachedIcon>,
    ) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&self.render_internal(params, None, cached_icon)?)
    }

    pub fn render_unavailable_internal(&self) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&create_unavailable_pixmap(self.width, self.height)?)
    }

    pub fn render_loading_internal(&self) -> Option<(Vec<u8>, u32, u32)> {
        pixmap_to_rgba(&create_filled_pixmap(
            self.width,
            self.height,
            COLOR_TRANSPARENT,
        )?)
    }

    fn render_internal(
        &self,
        params: &RenderParams,
        icon_png: Option<Vec<u8>>,
        cached_icon: Option<&crate::action::CachedIcon>,
    ) -> Option<Pixmap> {
        let mut pixmap = self.render_base(params, icon_png, cached_icon)?;

        if !params.show_action_page && params.meters_enabled && params.meter_value > 0 {
            self.render_meter_overlay(&mut pixmap, params);
        }

        Some(pixmap)
    }

    pub fn render_base(
        &self,
        params: &RenderParams,
        icon_png: Option<Vec<u8>>,
        cached_icon: Option<&crate::action::CachedIcon>,
    ) -> Option<Pixmap> {
        if params.show_action_page {
            return self.render_options_page(params);
        }
        self.render_main_page(params, icon_png, cached_icon)
    }

    pub fn render_meter_overlay(&self, pixmap: &mut Pixmap, params: &RenderParams) {
        let (bar_x, bar_y, bar_w) = self.main_bar_bounds();
        let inset = STROKE_WIDTH * 0.5;
        let inner_x = bar_x + inset;
        let inner_y = bar_y + inset;
        let inner_h = (BAR_HEIGHT - inset * 2.0).max(0.0);

        let fill_color = if !params.show_action_page {
            Some(self.mix_color(params.mix_b_active))
        } else {
            params.fill_color()
        };
        let fill_width = ((params.volume as f32 / 100.0) * bar_w - inset * 2.0).max(0.0);

        if params.meter_value > 0 && fill_width > 0.0 && inner_h > 0.0 {
            if let Some(fc) = fill_color {
                let meter_w = (params.meter_value as f32 / 100.0) * fill_width;
                if meter_w > 0.0 {
                    let meter_color = fc.blend(COLOR_WHITE, METER_LIGHTEN_AMOUNT);
                    Rect::new(inner_x, inner_y, meter_w, inner_h, 0.0)
                        .draw_filled(pixmap, meter_color);
                }
            }
        }
    }

    fn render_main_page(
        &self,
        params: &RenderParams,
        icon_png: Option<Vec<u8>>,
        cached_icon: Option<&crate::action::CachedIcon>,
    ) -> Option<Pixmap> {
        let width = self.width as f32;
        let height = self.height as f32;
        let mut pixmap = Pixmap::new(self.width, self.height)?;
        fill_background(&mut pixmap, COLOR_TRANSPARENT);

        self.draw_main_panel(&mut pixmap, width, height, params.accent_color());
        if let Some(cached) = cached_icon {
            self.composite_rgba8(
                &mut pixmap,
                &cached.rgba8,
                cached.width,
                cached.height,
                (width - ICON_MAX_SIZE) * 0.5,
                SOURCE_ICON_Y,
            );
        } else if let Some(png_data) = icon_png {
            self.composite_icon(
                &mut pixmap,
                &png_data,
                (width - ICON_MAX_SIZE) * 0.5,
                SOURCE_ICON_Y,
            );
        }

        draw_centered_text(
            &mut pixmap,
            if params.mix_b_active {
                "MIX B"
            } else {
                "MIX A"
            },
            Rect::new(MIX_LABEL_X, MIX_LABEL_Y, MIX_LABEL_W, MIX_LABEL_H, 0.0),
            12.5,
            if params.mix_b_active {
                COLOR_MIX_B
            } else {
                COLOR_MIX_A
            },
        );

        let (bar_x, bar_y, bar_w) = self.main_bar_bounds();
        let fill_width = (params.volume as f32 / 100.0) * bar_w;
        let mix_color = self.mix_color(params.mix_b_active);
        let bar = Rect::new(bar_x, bar_y, bar_w, BAR_HEIGHT, 0.0);
        bar.draw_filled(&mut pixmap, COLOR_PANEL_SLOT);
        if fill_width > 0.0 {
            Rect::new(bar_x, bar_y, fill_width, BAR_HEIGHT, 0.0)
                .draw_filled(&mut pixmap, mix_color);
        }
        bar.draw_stroked(&mut pixmap, COLOR_BLACK, STROKE_WIDTH);

        if params.is_muted {
            let icon_x = (width - ICON_MAX_SIZE) * 0.5;
            draw_diagonal_line(
                &mut pixmap,
                icon_x,
                SOURCE_ICON_Y,
                icon_x + ICON_MAX_SIZE,
                SOURCE_ICON_Y + ICON_MAX_SIZE,
                6.0,
                COLOR_RED,
            );
        }

        Some(pixmap)
    }

    fn main_bar_bounds(&self) -> (f32, f32, f32) {
        (
            SOURCE_BAR_X,
            SOURCE_BAR_Y,
            self.width as f32 - SOURCE_BAR_X * 2.0,
        )
    }

    fn render_options_page(&self, params: &RenderParams) -> Option<Pixmap> {
        let width = self.width as f32;
        let height = self.height as f32;
        let mut pixmap = Pixmap::new(self.width, self.height)?;
        fill_background(&mut pixmap, COLOR_TRANSPARENT);

        self.draw_main_panel(&mut pixmap, width, height, params.accent_color());
        if params.is_source {
            let mix_a_rect = self.scale_rect(
                PAGE_MARGIN_X,
                PAGE_SOURCE_TOP_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );
            let mix_b_rect = self.scale_rect(
                PAGE_COL_2_X,
                PAGE_SOURCE_TOP_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );
            let link_rect = self.scale_rect(
                PAGE_COL_3_X,
                PAGE_SOURCE_TOP_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );
            let mute_a_rect = self.scale_rect(
                PAGE_MARGIN_X,
                PAGE_SOURCE_BOTTOM_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );
            let mute_b_rect = self.scale_rect(
                PAGE_COL_2_X,
                PAGE_SOURCE_BOTTOM_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );
            let close_rect = self.scale_rect(
                PAGE_COL_3_X,
                PAGE_SOURCE_BOTTOM_Y,
                PAGE_SOURCE_BUTTON_W,
                PAGE_SOURCE_BUTTON_H,
                12.0,
            );

            self.draw_link_button(&mut pixmap, link_rect, params.source_volumes_linked);
            self.draw_mix_button(
                &mut pixmap,
                mix_a_rect,
                !params.mix_b_active,
                false,
                Some("MIX A"),
            );
            self.draw_mix_button(
                &mut pixmap,
                mix_b_rect,
                params.mix_b_active,
                true,
                Some("MIX B"),
            );
            self.draw_source_mute_button(
                &mut pixmap,
                mute_a_rect,
                params.source_mute_a,
                params.source_mute_a_all,
                params.source_mute_a_target_count,
                "MUTE 1",
            );
            self.draw_source_mute_button(
                &mut pixmap,
                mute_b_rect,
                params.source_mute_b,
                params.source_mute_b_all,
                params.source_mute_b_target_count,
                "MUTE 2",
            );
            self.draw_text_button(&mut pixmap, close_rect, false, COLOR_LINK_ACTIVE, "CLOSE");
        } else {
            let mute_rect = self.scale_rect(
                PAGE_MARGIN_X,
                PAGE_TARGET_Y,
                PAGE_TARGET_BUTTON_W,
                PAGE_TARGET_BUTTON_H,
                12.0,
            );
            let mix_a_rect = self.scale_rect(
                PAGE_TARGET_COL_2_X,
                PAGE_TARGET_Y,
                PAGE_TARGET_BUTTON_W,
                PAGE_TARGET_BUTTON_H,
                12.0,
            );
            let mix_b_rect = self.scale_rect(
                PAGE_TARGET_COL_3_X,
                PAGE_TARGET_Y,
                PAGE_TARGET_BUTTON_W,
                PAGE_TARGET_BUTTON_H,
                12.0,
            );

            self.draw_text_button(&mut pixmap, mute_rect, params.is_muted, COLOR_MUTE, "MUTE");
            self.draw_mix_button(
                &mut pixmap,
                mix_a_rect,
                !params.mix_b_active,
                false,
                Some("PLAY A"),
            );
            self.draw_mix_button(
                &mut pixmap,
                mix_b_rect,
                params.mix_b_active,
                true,
                Some("PLAY B"),
            );
        }

        Some(pixmap)
    }

    fn draw_main_panel(&self, pixmap: &mut Pixmap, width: f32, height: f32, accent: Rgba) {
        let panel = Rect::new(
            SOURCE_PANEL_X,
            SOURCE_PANEL_Y,
            width - SOURCE_PANEL_X * 2.0,
            height - SOURCE_PANEL_Y * 2.0,
            SOURCE_PANEL_RADIUS,
        );
        panel.draw_filled(pixmap, COLOR_PANEL_BASE);
        panel.draw_vertical_gradient_filled(pixmap, COLOR_TRANSPARENT, accent.with_alpha(77));
    }

    fn draw_link_button(&self, pixmap: &mut Pixmap, rect: Rect, active: bool) {
        let fill = if active {
            COLOR_LINK_ACTIVE
        } else {
            COLOR_BUTTON_IDLE
        };
        let border = if active {
            COLOR_BLACK
        } else {
            COLOR_LINK_ACTIVE
        };
        let text_color = if fill.luminance() > 0.35 {
            COLOR_BLACK
        } else {
            COLOR_WHITE
        };

        rect.draw_filled(pixmap, fill);
        rect.draw_stroked(pixmap, border, STROKE_WIDTH);
        draw_centered_text(
            pixmap,
            "LINK",
            Rect::new(rect.x, rect.y - 1.0, rect.w, rect.h, 0.0),
            self.scale_uniform(14.0),
            text_color,
        );
    }

    fn mix_color(&self, mix_b: bool) -> Rgba {
        if mix_b {
            COLOR_MIX_B
        } else {
            COLOR_MIX_A
        }
    }

    fn draw_mix_button(
        &self,
        pixmap: &mut Pixmap,
        rect: Rect,
        active: bool,
        mix_b: bool,
        label: Option<&str>,
    ) {
        let mix_color = self.mix_color(mix_b);
        let fill = if active { mix_color } else { COLOR_BUTTON_IDLE };
        let glyph_color = if active { COLOR_BLACK } else { mix_color };

        rect.draw_filled(pixmap, fill);
        rect.draw_stroked(
            pixmap,
            if active { COLOR_BLACK } else { mix_color },
            STROKE_WIDTH,
        );

        if let Some(label) = label {
            draw_centered_text(
                pixmap,
                label,
                Rect::new(rect.x, rect.y - 1.0, rect.w, rect.h, 0.0),
                self.scale_uniform(14.0),
                glyph_color,
            );
        } else {
            draw_mix_letter(
                pixmap,
                Rect::new(rect.x, rect.y - 1.0, rect.w, rect.h, 0.0),
                glyph_color,
                mix_b,
            );
        }
    }

    fn draw_text_button(
        &self,
        pixmap: &mut Pixmap,
        rect: Rect,
        active: bool,
        active_color: Rgba,
        label: &str,
    ) {
        let fill = if active {
            active_color
        } else {
            COLOR_BUTTON_IDLE
        };
        let text_color = if active { COLOR_BLACK } else { active_color };

        rect.draw_filled(pixmap, fill);
        rect.draw_stroked(
            pixmap,
            if active { COLOR_BLACK } else { active_color },
            STROKE_WIDTH,
        );
        draw_centered_text(
            pixmap,
            label,
            Rect::new(rect.x, rect.y - 1.0, rect.w, rect.h, 0.0),
            self.scale_uniform(13.5),
            text_color,
        );
    }

    fn draw_source_mute_button(
        &self,
        pixmap: &mut Pixmap,
        rect: Rect,
        active: bool,
        mute_all: bool,
        target_count: u8,
        label: &str,
    ) {
        let fill = if active {
            COLOR_MUTE
        } else {
            COLOR_BUTTON_IDLE
        };
        let accent = if active { COLOR_BLACK } else { COLOR_MUTE };
        let detail = if mute_all {
            "ALL".to_string()
        } else {
            format!("{} TGT", target_count.max(1))
        };

        rect.draw_filled(pixmap, fill);
        rect.draw_stroked(pixmap, accent, STROKE_WIDTH);
        draw_centered_text(
            pixmap,
            label,
            Rect::new(
                rect.x,
                rect.y + self.scale_y(1.0),
                rect.w,
                rect.h * 0.48,
                0.0,
            ),
            self.scale_uniform(12.5),
            accent,
        );
        draw_centered_text(
            pixmap,
            &detail,
            Rect::new(rect.x, rect.y + rect.h * 0.45, rect.w, rect.h * 0.34, 0.0),
            self.scale_uniform(10.5),
            accent,
        );
    }

    fn composite_icon(&self, pixmap: &mut Pixmap, png_data: &[u8], x: f32, y: f32) {
        let Ok(img) = image::load_from_memory(png_data) else {
            return;
        };

        let (iw, ih) = (img.width() as f32, img.height() as f32);
        let scale = (ICON_MAX_SIZE / iw).min(ICON_MAX_SIZE / ih).min(1.0);
        let (sw, sh) = ((iw * scale) as u32, (ih * scale) as u32);

        let resized = img
            .resize(sw, sh, image::imageops::FilterType::Triangle)
            .to_rgba8();
        self.composite_rgba8(pixmap, &resized, sw, sh, x, y);
    }

    fn composite_rgba8(
        &self,
        pixmap: &mut Pixmap,
        rgba8: &image::RgbaImage,
        sw: u32,
        sh: u32,
        x: f32,
        y: f32,
    ) {
        let (fx, fy) = (
            (x + (ICON_MAX_SIZE - sw as f32) / 2.0) as i32,
            (y + (ICON_MAX_SIZE - sh as f32) / 2.0) as i32,
        );
        for (ix, iy, pixel) in rgba8.enumerate_pixels() {
            let (px, py) = (fx + ix as i32, fy + iy as i32);
            if px < 0 || py < 0 || px >= self.width as i32 || py >= self.height as i32 {
                continue;
            }
            let src_a = pixel[3] as f32 / 255.0;
            if src_a == 0.0 {
                continue;
            }

            let idx = (py as usize * self.width as usize + px as usize) * 4;
            let data = pixmap.data_mut();
            if idx + 3 >= data.len() {
                continue;
            }

            let dst_a = data[idx + 3] as f32 / 255.0;
            let out_a = src_a + dst_a * (1.0 - src_a);
            if out_a > 0.0 {
                let blend = |s: u8, d: u8| {
                    ((s as f32 * src_a + d as f32 * dst_a * (1.0 - src_a)) / out_a) as u8
                };
                data[idx] = blend(pixel[0], data[idx]);
                data[idx + 1] = blend(pixel[1], data[idx + 1]);
                data[idx + 2] = blend(pixel[2], data[idx + 2]);
                data[idx + 3] = (out_a * 255.0) as u8;
            }
        }
    }
}
