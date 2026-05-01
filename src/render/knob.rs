use super::common::*;
use pyo3::prelude::*;
use tiny_skia::Pixmap;

const ICON_MAX_SIZE: f32 = 52.0;
const BAR_HEIGHT: f32 = 14.0;
const STROKE_WIDTH: f32 = 2.0;
const MIX_LABEL_X: f32 = 130.0;
const MIX_LABEL_Y: f32 = 5.0;
const MIX_LABEL_W: f32 = 60.0;
const MIX_LABEL_H: f32 = 16.0;
const MUTE_LABEL_X: f32 = 130.0;
const MUTE_LABEL_Y: f32 = 23.0;
const MUTE_LABEL_W: f32 = 60.0;
const MUTE_LABEL_H: f32 = 16.0;
const LINK_LABEL_X: f32 = 130.0;
const LINK_LABEL_Y: f32 = 41.0;
const LINK_LABEL_W: f32 = 60.0;
const LINK_LABEL_H: f32 = 14.0;
const PANEL_INSET: f32 = 4.0;
const SOURCE_PANEL_X: f32 = PANEL_INSET;
const SOURCE_PANEL_Y: f32 = PANEL_INSET;
const SOURCE_PANEL_RADIUS: f32 = 0.0;
const SOURCE_BAR_X: f32 = 20.0;
const SOURCE_BAR_Y: f32 = 74.0;
const SOURCE_ICON_Y: f32 = 16.0;
const COLOR_MIX_A: Rgba = Rgba::rgb(106, 196, 205);
const COLOR_MIX_B: Rgba = Rgba::rgb(242, 146, 44);
const COLOR_PANEL_SLOT: Rgba = Rgba::rgb(40, 43, 41);
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
            source_volumes_linked: false,
            mute_profile: 0,
            mute_profile_muted: false,
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

        if params.meters_enabled && params.meter_value > 0 {
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
        self.render_main_page(params, icon_png, cached_icon)
    }

    pub fn render_meter_overlay(&self, pixmap: &mut Pixmap, params: &RenderParams) {
        let (bar_x, bar_y, bar_w) = self.main_bar_bounds();
        let inset = STROKE_WIDTH * 0.5;
        let inner_x = bar_x + inset;
        let inner_y = bar_y + inset;
        let inner_h = (BAR_HEIGHT - inset * 2.0).max(0.0);

        let fill_color = Some(if params.is_source && params.source_volumes_linked {
            params.accent_color()
        } else {
            self.mix_color(params.mix_b_active)
        });
        let fill_width = ((params.volume as f32 / 100.0) * bar_w - inset * 2.0).max(0.0);

        if params.meter_value > 0 && fill_width > 0.0 && inner_h > 0.0 {
            if let Some(fc) = fill_color {
                let meter_w = (params.meter_value as f32 / 100.0) * fill_width;
                if meter_w > 0.0 {
                    let meter_color = meter_overlay_color(fc);
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

        draw_right_text(
            &mut pixmap,
            if params.mix_b_active { "MB" } else { "MA" },
            Rect::new(MIX_LABEL_X, MIX_LABEL_Y, MIX_LABEL_W, MIX_LABEL_H, 0.0),
            12.5,
            if params.mix_b_active { COLOR_MIX_B } else { COLOR_MIX_A },
        );

        let mute_rect = Rect::new(MUTE_LABEL_X, MUTE_LABEL_Y, MUTE_LABEL_W, MUTE_LABEL_H, 2.0);
        if params.mute_profile_muted {
            mute_rect.draw_filled(&mut pixmap, COLOR_RED);
        }
        let mute_text = format!("M{}", params.mute_profile + 1);
        draw_right_text(
            &mut pixmap,
            &mute_text,
            Rect::new(MUTE_LABEL_X, MUTE_LABEL_Y, MUTE_LABEL_W, MUTE_LABEL_H, 0.0),
            12.5,
            if params.mute_profile_muted {
                COLOR_WHITE
            } else {
                Rgba::rgb(200, 200, 200)
            },
        );

        if params.is_source && params.source_volumes_linked {
            draw_right_text(
                &mut pixmap,
                "LINKED",
                Rect::new(LINK_LABEL_X, LINK_LABEL_Y, LINK_LABEL_W, LINK_LABEL_H, 0.0),
                11.0,
                Rgba::rgb(238, 238, 238),
            );
        }

        let (bar_x, bar_y, bar_w) = self.main_bar_bounds();
        let fill_width = (params.volume as f32 / 100.0) * bar_w;
        let bar_color = if params.is_source && params.source_volumes_linked {
            params.accent_color()
        } else {
            self.mix_color(params.mix_b_active)
        };
        let bar = Rect::new(bar_x, bar_y, bar_w, BAR_HEIGHT, 0.0);
        bar.draw_filled(&mut pixmap, COLOR_PANEL_SLOT);
        if fill_width > 0.0 {
            Rect::new(bar_x, bar_y, fill_width, BAR_HEIGHT, 0.0)
                .draw_filled(&mut pixmap, bar_color);
        }
        bar.draw_stroked(&mut pixmap, COLOR_BLACK, STROKE_WIDTH);

        Some(pixmap)
    }

    fn main_bar_bounds(&self) -> (f32, f32, f32) {
        (
            SOURCE_BAR_X,
            SOURCE_BAR_Y,
            self.width as f32 - SOURCE_BAR_X * 2.0,
        )
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

    fn mix_color(&self, mix_b: bool) -> Rgba {
        if mix_b {
            COLOR_MIX_B
        } else {
            COLOR_MIX_A
        }
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
