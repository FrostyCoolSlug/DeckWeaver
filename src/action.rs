//! Action state management for Stream Deck buttons/dials

use crate::devices::Device;
use pyo3::prelude::*;
use std::sync::atomic::{AtomicU8, Ordering};

/// Type of action (determines rendering)
#[pyclass]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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

/// Configuration for an action (set from Python)
#[pyclass]
#[derive(Debug, Clone)]
pub struct ActionConfig {
    /// Unique action ID (from Python)
    #[pyo3(get, set)]
    pub action_id: String,

    /// Type of action
    #[pyo3(get, set)]
    pub action_type: ActionType,

    /// Target device ID
    #[pyo3(get, set)]
    pub device_id: Option<String>,

    /// Volume step for adjustments
    #[pyo3(get, set)]
    pub volume_step: i8,

    /// Image dimensions
    #[pyo3(get, set)]
    pub width: u32,
    #[pyo3(get, set)]
    pub height: u32,

    /// Whether meters are enabled
    #[pyo3(get, set)]
    pub meters_enabled: bool,

    /// Whether to invert meter color
    #[pyo3(get, set)]
    pub meter_invert: bool,

    /// Custom volume bar color (RGBA)
    #[pyo3(get, set)]
    pub volume_bar_color: Option<(u8, u8, u8, u8)>,

    /// Custom meter color (RGBA)
    #[pyo3(get, set)]
    pub meter_color: Option<(u8, u8, u8, u8)>,

    /// Orientation for slider ("vertical" or "horizontal")
    #[pyo3(get, set)]
    pub orientation: String,

    /// Is this the top part of a slider (positive volume step)
    #[pyo3(get, set)]
    pub is_top: bool,

    /// Custom icon PNG bytes
    #[pyo3(get, set)]
    pub icon_png: Option<Vec<u8>>,
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
        }
    }
}

/// Runtime state for an action (managed by Rust)
#[derive(Debug)]
pub struct ActionState {
    pub config: ActionConfig,
    pub device: Option<Device>,
    pub meter_value: AtomicU8,
    pub last_render_hash: AtomicU8, // Simple hash to detect changes
    pub last_label: parking_lot::RwLock<Option<String>>, // Track label changes
}

impl ActionState {
    pub fn new(config: ActionConfig) -> Self {
        Self {
            config,
            device: None,
            meter_value: AtomicU8::new(0),
            last_render_hash: AtomicU8::new(0),
            last_label: parking_lot::RwLock::new(None),
        }
    }

    /// Check if the label changed and update tracking
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

    /// Calculate a simple hash of render state to detect changes
    pub fn render_hash(&self) -> u8 {
        let mut hash: u8 = 0;
        if let Some(ref device) = self.device {
            hash = hash.wrapping_add(device.volume);
            hash = hash.wrapping_add(if device.is_muted { 128 } else { 0 });
        }
        hash = hash.wrapping_add(self.get_meter());
        hash
    }

    pub fn needs_render(&self) -> bool {
        let current = self.render_hash();
        let last = self.last_render_hash.swap(current, Ordering::Relaxed);
        current != last
    }
}
