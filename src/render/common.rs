use tiny_skia::{Color, FillRule, Paint, PathBuilder, Pixmap, Stroke, Transform};

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
pub const COLOR_SERVICE_UNAVAILABLE_BG: Rgba = Rgba::rgb(255, 193, 7);

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
}

impl RenderParams {
    pub fn fill_color(&self) -> Option<Rgba> {
        if self.volume == 0 {
            return None;
        }
        Some(
            self.volume_bar_color
                .map(Rgba::from)
                .or_else(|| self.device_color.map(Rgba::from))
                .unwrap_or(if self.is_source {
                    COLOR_SOURCE_FILL
                } else {
                    COLOR_TARGET_FILL
                }),
        )
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
            pixmap.fill_path(&path, &solid_paint(color), FillRule::Winding, Transform::identity(), None);
        }
    }

    pub fn draw_stroked(self, pixmap: &mut Pixmap, color: Rgba, width: f32) {
        if let Some(path) = rounded_rect_path(self.x, self.y, self.w, self.h, self.radius) {
            let stroke = Stroke { width, ..Default::default() };
            pixmap.stroke_path(&path, &solid_paint(color), &stroke, Transform::identity(), None);
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
        pixmap.stroke_path(&path, &solid_paint(color), &stroke, Transform::identity(), None);
    }
}

pub fn draw_symbol(pixmap: &mut Pixmap, cx: f32, cy: f32, size: f32, width: f32, color: Rgba, is_plus: bool) {
    let half = size / 2.0;
    stroke_line(pixmap, cx - half, cy, cx + half, cy, width, color);
    if is_plus {
        stroke_line(pixmap, cx, cy - half, cx, cy + half, width, color);
    }
}

pub fn draw_diagonal_line(pixmap: &mut Pixmap, x1: f32, y1: f32, x2: f32, y2: f32, width: f32, color: Rgba) {
    stroke_line(pixmap, x1, y1, x2, y2, width, color);
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
