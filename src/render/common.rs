use ab_glyph::{point, Font, FontArc, GlyphId, PxScale, ScaleFont};
use image::{Rgba as ImageRgba, RgbaImage};
use image::imageops::FilterType;
use imageproc::drawing::draw_text_mut;
use std::fs;
use std::sync::OnceLock;
use tiny_skia::{
    Color, FillRule, GradientStop, LinearGradient, Paint, PathBuilder, Pixmap, Point, SpreadMode,
    Stroke, Transform,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rgba {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

impl Rgba {
    pub const fn new(r: u8, g: u8, b: u8, a: u8) -> Self {
        Self { r, g, b, a }
    }

    pub const fn rgb(r: u8, g: u8, b: u8) -> Self {
        Self::new(r, g, b, 255)
    }

    pub fn as_color(self) -> Color {
        Color::from_rgba8(self.r, self.g, self.b, self.a)
    }

    pub fn invert(self) -> Self {
        Self::new(255 - self.r, 255 - self.g, 255 - self.b, self.a)
    }

    pub fn blend(self, other: Self, amount: f32) -> Self {
        let t = amount.clamp(0.0, 1.0);
        let lerp = |from: u8, to: u8| from as f32 + (to as f32 - from as f32) * t;
        Self::new(
            lerp(self.r, other.r).round() as u8,
            lerp(self.g, other.g).round() as u8,
            lerp(self.b, other.b).round() as u8,
            lerp(self.a, other.a).round() as u8,
        )
    }

    pub fn with_alpha(self, a: u8) -> Self {
        Self { a, ..self }
    }

    pub fn luminance(self) -> f32 {
        fn normalize(val: u8) -> f32 {
            let v = val as f32 / 255.0;
            if v <= 0.03928 {
                v / 12.92
            } else {
                ((v + 0.055) / 1.055).powf(2.4)
            }
        }
        0.2126 * normalize(self.r) + 0.7152 * normalize(self.g) + 0.0722 * normalize(self.b)
    }
}

impl From<(u8, u8, u8)> for Rgba {
    fn from((r, g, b): (u8, u8, u8)) -> Self {
        Self::rgb(r, g, b)
    }
}

impl From<(u8, u8, u8, u8)> for Rgba {
    fn from((r, g, b, a): (u8, u8, u8, u8)) -> Self {
        Self::new(r, g, b, a)
    }
}

pub const COLOR_TRANSPARENT: Rgba = Rgba::new(0, 0, 0, 0);
pub const COLOR_BLACK: Rgba = Rgba::rgb(0, 0, 0);
pub const COLOR_WHITE: Rgba = Rgba::rgb(255, 255, 255);
pub const COLOR_RED: Rgba = Rgba::rgb(255, 0, 0);
pub const COLOR_SOURCE_FILL: Rgba = Rgba::rgb(102, 179, 255);
pub const COLOR_TARGET_FILL: Rgba = Rgba::rgb(102, 255, 102);
pub const COLOR_GUTTER_DARK: Rgba = Rgba::rgb(120, 120, 120);
pub const COLOR_GUTTER_LIGHT: Rgba = Rgba::rgb(220, 220, 220);
const GUTTER_LUMINANCE_THRESHOLD: f32 = 0.1;

#[derive(Debug, Clone, Default)]
pub struct RenderParams {
    pub volume: u8,
    pub is_muted: bool,
    pub is_source: bool,
    pub meter_value: u8,
    pub device_color: Option<(u8, u8, u8)>,
    pub volume_bar_color: Option<(u8, u8, u8, u8)>,
    pub meter_color: Option<(u8, u8, u8, u8)>,
    pub meter_invert: bool,
    pub meters_enabled: bool,
    pub mix_b_active: bool,
    pub source_volumes_linked: bool,
    pub mute_profile: u8,
    pub mute_profile_muted: bool,
}

impl RenderParams {
    pub fn accent_color(&self) -> Rgba {
        self.volume_bar_color
            .map(Rgba::from)
            .or_else(|| self.device_color.map(Rgba::from))
            .unwrap_or(if self.is_source {
                COLOR_SOURCE_FILL
            } else {
                COLOR_TARGET_FILL
            })
    }

    pub fn fill_color(&self) -> Option<Rgba> {
        if self.volume == 0 {
            return None;
        }
        Some(self.accent_color())
    }
}

pub fn gutter_color_for(fill_color: Option<Rgba>) -> Rgba {
    match fill_color {
        Some(c) if c.luminance() < GUTTER_LUMINANCE_THRESHOLD => COLOR_GUTTER_LIGHT,
        _ => COLOR_GUTTER_DARK,
    }
}

fn rounded_rect_path(x: f32, y: f32, w: f32, h: f32, radius: f32) -> Option<tiny_skia::Path> {
    if w <= 0.0 || h <= 0.0 {
        return None;
    }
    let r = radius.min(w / 2.0).min(h / 2.0);
    let mut pb = PathBuilder::new();
    pb.move_to(x + r, y);
    pb.line_to(x + w - r, y);
    pb.quad_to(x + w, y, x + w, y + r);
    pb.line_to(x + w, y + h - r);
    pb.quad_to(x + w, y + h, x + w - r, y + h);
    pb.line_to(x + r, y + h);
    pb.quad_to(x, y + h, x, y + h - r);
    pb.line_to(x, y + r);
    pb.quad_to(x, y, x + r, y);
    pb.close();
    pb.finish()
}

pub fn solid_paint(color: Rgba) -> Paint<'static> {
    let mut paint = Paint::default();
    paint.set_color(color.as_color());
    paint.anti_alias = true;
    paint
}

pub fn fill_background(pixmap: &mut Pixmap, color: Rgba) {
    pixmap.fill(color.as_color());
}

#[derive(Debug, Clone, Copy)]
pub struct Rect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
    pub radius: f32,
}

impl Rect {
    pub const fn new(x: f32, y: f32, w: f32, h: f32, radius: f32) -> Self {
        Self { x, y, w, h, radius }
    }

    pub fn draw_filled(self, pixmap: &mut Pixmap, color: Rgba) {
        if let Some(path) = rounded_rect_path(self.x, self.y, self.w, self.h, self.radius) {
            pixmap.fill_path(
                &path,
                &solid_paint(color),
                FillRule::Winding,
                Transform::identity(),
                None,
            );
        }
    }

    pub fn draw_vertical_gradient_filled(self, pixmap: &mut Pixmap, top: Rgba, bottom: Rgba) {
        let Some(path) = rounded_rect_path(self.x, self.y, self.w, self.h, self.radius) else {
            return;
        };

        let Some(shader) = LinearGradient::new(
            Point::from_xy(self.x, self.y),
            Point::from_xy(self.x, self.y + self.h),
            vec![
                GradientStop::new(0.0, top.as_color()),
                GradientStop::new(1.0, bottom.as_color()),
            ],
            SpreadMode::Pad,
            Transform::identity(),
        ) else {
            return;
        };

        let paint = Paint {
            anti_alias: true,
            shader,
            ..Default::default()
        };
        pixmap.fill_path(
            &path,
            &paint,
            FillRule::Winding,
            Transform::identity(),
            None,
        );
    }

    pub fn draw_stroked(self, pixmap: &mut Pixmap, color: Rgba, width: f32) {
        if let Some(path) = rounded_rect_path(self.x, self.y, self.w, self.h, self.radius) {
            let stroke = Stroke {
                width,
                ..Default::default()
            };
            pixmap.stroke_path(
                &path,
                &solid_paint(color),
                &stroke,
                Transform::identity(),
                None,
            );
        }
    }
}

fn stroke_line(pixmap: &mut Pixmap, x1: f32, y1: f32, x2: f32, y2: f32, width: f32, color: Rgba) {
    let mut pb = PathBuilder::new();
    pb.move_to(x1, y1);
    pb.line_to(x2, y2);
    if let Some(path) = pb.finish() {
        let stroke = Stroke {
            width,
            line_cap: tiny_skia::LineCap::Round,
            ..Default::default()
        };
        pixmap.stroke_path(
            &path,
            &solid_paint(color),
            &stroke,
            Transform::identity(),
            None,
        );
    }
}

pub fn draw_symbol(
    pixmap: &mut Pixmap,
    cx: f32,
    cy: f32,
    size: f32,
    width: f32,
    color: Rgba,
    is_plus: bool,
) {
    let half = size / 2.0;
    stroke_line(pixmap, cx - half, cy, cx + half, cy, width, color);
    if is_plus {
        stroke_line(pixmap, cx, cy - half, cx, cy + half, width, color);
    }
}

pub fn draw_diagonal_line(
    pixmap: &mut Pixmap,
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
    width: f32,
    color: Rgba,
) {
    stroke_line(pixmap, x1, y1, x2, y2, width, color);
}

const TEXT_SUPERSAMPLE: u32 = 2;

pub fn draw_right_text(
    pixmap: &mut Pixmap,
    text: &str,
    rect: Rect,
    font_size: f32,
    color: Rgba,
) {
    let Some(font) = mix_font() else {
        return;
    };

    let scale = PxScale::from(font_size * TEXT_SUPERSAMPLE as f32);
    let width = (rect.w.ceil().max(1.0) as u32) * TEXT_SUPERSAMPLE;
    let height = (rect.h.ceil().max(1.0) as u32) * TEXT_SUPERSAMPLE;
    let Some((min_x, min_y, max_x, max_y)) = text_pixel_bounds(font, scale, text) else {
        return;
    };

    let text_w = (max_x - min_x).ceil().max(1.0);
    let text_h = (max_y - min_y).ceil().max(1.0);
    let text_x = (width as f32 - text_w - min_x).round() as i32;
    let text_y = ((height as f32 - text_h) * 0.5 - min_y).round() as i32;

    let mut rgba = RgbaImage::from_pixel(width, height, ImageRgba([0, 0, 0, 0]));
    draw_text_mut(
        &mut rgba,
        ImageRgba([color.r, color.g, color.b, color.a]),
        text_x,
        text_y,
        scale,
        font,
        text,
    );

    let scaled = image::imageops::resize(
        &rgba,
        width / TEXT_SUPERSAMPLE,
        height / TEXT_SUPERSAMPLE,
        FilterType::Lanczos3,
    );
    blend_rgba_image(pixmap, &scaled, rect.x.round() as i32, rect.y.round() as i32);
}

pub fn create_unavailable_pixmap(width: u32, height: u32) -> Option<Pixmap> {
    let mut pixmap = Pixmap::new(width, height)?;
    fill_background(&mut pixmap, COLOR_TRANSPARENT);

    let min_side = width.min(height) as f32;
    let inset = (min_side * 0.22).max(8.0);
    let stroke_width = (min_side * 0.12).max(4.0);
    let w = width as f32;
    let h = height as f32;

    draw_diagonal_line(
        &mut pixmap,
        inset,
        inset,
        w - inset,
        h - inset,
        stroke_width,
        COLOR_RED,
    );
    draw_diagonal_line(
        &mut pixmap,
        w - inset,
        inset,
        inset,
        h - inset,
        stroke_width,
        COLOR_RED,
    );

    Some(pixmap)
}

/// Convert Pixmap to raw RGBA bytes (no PNG encoding - much faster!)
pub fn pixmap_to_rgba(pixmap: &Pixmap) -> Option<(Vec<u8>, u32, u32)> {
    let data = pixmap.data();
    Some((data.to_vec(), pixmap.width(), pixmap.height()))
}

pub fn create_filled_pixmap(width: u32, height: u32, color: Rgba) -> Option<Pixmap> {
    let mut pixmap = Pixmap::new(width, height)?;
    fill_background(&mut pixmap, color);
    Some(pixmap)
}

fn mix_font() -> Option<&'static FontArc> {
    static FONT: OnceLock<Option<FontArc>> = OnceLock::new();
    const FONT_PATHS: &[&str] = &[
        "/usr/share/fonts/TTF/Inter-Bold.ttf",
        "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ];

    FONT.get_or_init(|| {
        for path in FONT_PATHS {
            let Ok(bytes) = fs::read(path) else {
                continue;
            };
            if let Ok(font) = FontArc::try_from_vec(bytes) {
                return Some(font);
            }
        }
        None
    })
    .as_ref()
}

fn text_pixel_bounds(font: &FontArc, scale: PxScale, text: &str) -> Option<(f32, f32, f32, f32)> {
    let scaled = font.as_scaled(scale);
    let mut pen_x = 0.0f32;
    let mut last: Option<GlyphId> = None;
    let mut min_x = f32::INFINITY;
    let mut min_y = f32::INFINITY;
    let mut max_x = f32::NEG_INFINITY;
    let mut max_y = f32::NEG_INFINITY;

    for c in text.chars() {
        let glyph_id = scaled.glyph_id(c);
        let glyph = glyph_id.with_scale_and_position(scale, point(pen_x, scaled.ascent()));
        pen_x += scaled.h_advance(glyph_id);
        if let Some(prev) = last {
            pen_x += scaled.kern(glyph_id, prev);
        }
        last = Some(glyph_id);

        if let Some(outlined) = scaled.outline_glyph(glyph) {
            let bb = outlined.px_bounds();
            min_x = min_x.min(bb.min.x);
            min_y = min_y.min(bb.min.y);
            max_x = max_x.max(bb.max.x);
            max_y = max_y.max(bb.max.y);
        }
    }

    if min_x.is_finite() && min_y.is_finite() && max_x.is_finite() && max_y.is_finite() {
        Some((min_x, min_y, max_x, max_y))
    } else {
        None
    }
}

fn blend_rgba_image(pixmap: &mut Pixmap, rgba: &RgbaImage, dest_x: i32, dest_y: i32) {
    for (ix, iy, pixel) in rgba.enumerate_pixels() {
        let px = dest_x + ix as i32;
        let py = dest_y + iy as i32;
        if px < 0 || py < 0 || px >= pixmap.width() as i32 || py >= pixmap.height() as i32 {
            continue;
        }

        let src_a = pixel[3] as f32 / 255.0;
        if src_a <= 0.0 {
            continue;
        }

        let idx = ((py as u32 * pixmap.width() + px as u32) * 4) as usize;
        let data = pixmap.data_mut();
        let dst_r = data[idx] as f32;
        let dst_g = data[idx + 1] as f32;
        let dst_b = data[idx + 2] as f32;
        let dst_a = data[idx + 3] as f32 / 255.0;
        let out_a = src_a + dst_a * (1.0 - src_a);

        let blend = |src: u8, dst: f32| -> u8 {
            if out_a <= 0.0 {
                0
            } else {
                (((src as f32 * src_a) + (dst * dst_a * (1.0 - src_a))) / out_a).round() as u8
            }
        };

        data[idx] = blend(pixel[0], dst_r);
        data[idx + 1] = blend(pixel[1], dst_g);
        data[idx + 2] = blend(pixel[2], dst_b);
        data[idx + 3] = (out_a * 255.0).round() as u8;
    }
}
