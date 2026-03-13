use crate::devices::Device;
use parking_lot::RwLock;
use pyo3::prelude::*;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};

#[pyclass]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ActionType {
    Knob,
    Slider,
    Button,
}

#[pymethods]
impl ActionType {
    #[staticmethod]
    fn knob() -> Self {
        ActionType::Knob
    }

    #[staticmethod]
    fn slider() -> Self {
        ActionType::Slider
    }

    #[staticmethod]
    fn button() -> Self {
        ActionType::Button
    }
}

#[pyclass]
#[derive(Debug, Clone)]
pub struct ActionConfig {
    #[pyo3(get, set)]
    pub action_id: String,
    #[pyo3(get, set)]
    pub action_type: ActionType,
    #[pyo3(get, set)]
    pub device_id: Option<String>,
    #[pyo3(get, set)]
    pub volume_step: i8,
    #[pyo3(get, set)]
    pub width: u32,
    #[pyo3(get, set)]
    pub height: u32,
    #[pyo3(get, set)]
    pub meters_enabled: bool,
    #[pyo3(get, set)]
    pub meter_invert: bool,
    #[pyo3(get, set)]
    pub volume_bar_color: Option<(u8, u8, u8, u8)>,
    #[pyo3(get, set)]
    pub meter_color: Option<(u8, u8, u8, u8)>,
    #[pyo3(get, set)]
    pub orientation: String,
    #[pyo3(get, set)]
    pub is_top: bool,
    #[pyo3(get, set)]
    pub icon_png: Option<Vec<u8>>,
    #[pyo3(get, set)]
    pub button_overlay: bool,
}

#[pymethods]
impl ActionConfig {
    #[new]
    #[pyo3(signature = (
        action_id,
        action_type,
        width=200,
        height=100
    ))]
    fn new(action_id: String, action_type: ActionType, width: u32, height: u32) -> Self {
        Self {
            action_id,
            action_type,
            device_id: None,
            volume_step: 5,
            width,
            height,
            meters_enabled: true,
            meter_invert: true,
            volume_bar_color: None,
            meter_color: None,
            orientation: "vertical".to_string(),
            is_top: true,
            icon_png: None,
            button_overlay: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct CachedIcon {
    pub rgba8: image::RgbaImage,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone)]
pub struct CachedBaseRender {
    pub pixmap: tiny_skia::Pixmap,
    pub base_hash: u64,
}

#[derive(Debug)]
pub struct ActionState {
    pub config: ActionConfig,
    pub device: Option<Device>,
    pub meter_value: AtomicU8,
    pub last_render_hash: AtomicU64,
    pub last_label: parking_lot::RwLock<Option<String>>,
    pub cached_icon: RwLock<Option<(u64, CachedIcon)>>,
    pub cached_base: RwLock<Option<CachedBaseRender>>,
    pub cached_base_hash: parking_lot::RwLock<Option<u64>>,
}

impl ActionState {
    pub fn new(config: ActionConfig) -> Self {
        Self {
            config,
            device: None,
            meter_value: AtomicU8::new(0),
            // Force first frame to render even when device/meter state hashes to 0.
            last_render_hash: AtomicU64::new(u64::MAX),
            last_label: parking_lot::RwLock::new(None),
            cached_icon: RwLock::new(None),
            cached_base: RwLock::new(None),
            cached_base_hash: parking_lot::RwLock::new(None),
        }
    }

    pub fn base_hash(&self) -> u64 {
        let mut hasher = DefaultHasher::new();
        if let Some(ref device) = self.device {
            device.volume.hash(&mut hasher);
            device.is_muted.hash(&mut hasher);
            if let Some(color) = &device.color {
                color.red.hash(&mut hasher);
                color.green.hash(&mut hasher);
                color.blue.hash(&mut hasher);
            }
        }
        self.config.volume_bar_color.hash(&mut hasher);
        self.config.meter_color.hash(&mut hasher);
        self.config.meter_invert.hash(&mut hasher);
        self.config.meters_enabled.hash(&mut hasher);
        if let Some(ref icon_png) = self.config.icon_png {
            icon_png.hash(&mut hasher);
        }
        if self.config.action_type == crate::action::ActionType::Slider {
            self.config.orientation.hash(&mut hasher);
            self.config.is_top.hash(&mut hasher);
        }
        if self.config.action_type == crate::action::ActionType::Button {
            self.config.button_overlay.hash(&mut hasher);
        }
        let current_hash = hasher.finish();

        let mut cached_hash_guard = self.cached_base_hash.write();
        if let Some(cached) = *cached_hash_guard {
            if cached == current_hash {
                return cached;
            }
        }
        *cached_hash_guard = Some(current_hash);
        current_hash
    }

    pub fn needs_base_rebuild(&self) -> bool {
        let current_hash = self.base_hash();
        let cached = self.cached_base.read();
        cached
            .as_ref()
            .map_or(true, |c| c.base_hash != current_hash)
    }

    pub fn get_cached_icon(&self, png_data: Option<&[u8]>, max_size: f32) -> Option<CachedIcon> {
        let Some(png_data) = png_data else {
            *self.cached_icon.write() = None;
            return None;
        };

        let mut hasher = DefaultHasher::new();
        png_data.hash(&mut hasher);
        let icon_hash = hasher.finish();

        {
            let cached = self.cached_icon.read();
            if let Some((cached_hash, cached_icon)) = cached.as_ref() {
                if *cached_hash == icon_hash {
                    return Some(cached_icon.clone());
                }
            }
        }

        let Ok(img) = image::load_from_memory(png_data) else {
            return None;
        };

        let (iw, ih) = (img.width() as f32, img.height() as f32);
        let scale = (max_size / iw).min(max_size / ih).min(1.0);
        let (sw, sh) = ((iw * scale) as u32, (ih * scale) as u32);

        let resized = img
            .resize(sw, sh, image::imageops::FilterType::Triangle)
            .to_rgba8();

        let cached = CachedIcon {
            rgba8: resized,
            width: sw,
            height: sh,
        };

        *self.cached_icon.write() = Some((icon_hash, cached.clone()));

        Some(cached)
    }

    pub fn label_changed(&self, new_label: Option<&str>) -> bool {
        let mut last = self.last_label.write();
        let changed = last.as_deref() != new_label;
        if changed {
            *last = new_label.map(|s| s.to_string());
        }
        changed
    }

    pub fn get_meter(&self) -> u8 {
        self.meter_value.load(Ordering::Relaxed)
    }

    pub fn set_meter(&self, value: u8) {
        self.meter_value.store(value, Ordering::Relaxed);
    }

    pub fn render_hash(&self) -> u64 {
        let mut hasher = DefaultHasher::new();
        self.config.action_type.hash(&mut hasher);
        self.config.device_id.hash(&mut hasher);
        self.config.meters_enabled.hash(&mut hasher);
        self.config.orientation.hash(&mut hasher);
        self.config.is_top.hash(&mut hasher);
        self.config.button_overlay.hash(&mut hasher);
        self.get_meter().hash(&mut hasher);

        if let Some(ref device) = self.device {
            device.id.hash(&mut hasher);
            device.volume.hash(&mut hasher);
            device.is_muted.hash(&mut hasher);
        } else {
            0u8.hash(&mut hasher);
        }

        hasher.finish()
    }

    pub fn needs_render(&self) -> bool {
        let current = self.render_hash();
        let last = self.last_render_hash.swap(current, Ordering::Relaxed);
        current != last
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> ActionConfig {
        ActionConfig::new("test-action".to_string(), ActionType::Knob, 200, 100)
    }

    #[test]
    fn first_frame_requires_render() {
        let state = ActionState::new(config());
        assert!(state.needs_render());
        assert!(!state.needs_render());
    }

    #[test]
    fn meter_change_triggers_render() {
        let state = ActionState::new(config());
        assert!(state.needs_render());
        state.set_meter(17);
        assert!(state.needs_render());
    }
}
