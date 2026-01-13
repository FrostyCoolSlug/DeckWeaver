//! Device types and helpers for working with PipeWeaver audio devices

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Device type identifier
#[pyclass]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DeviceType {
    Source,
    Target,
}

#[pymethods]
impl DeviceType {
    #[staticmethod]
    fn source() -> Self {
        DeviceType::Source
    }

    #[staticmethod]
    fn target() -> Self {
        DeviceType::Target
    }

    fn __repr__(&self) -> &'static str {
        match self {
            DeviceType::Source => "DeviceType.Source",
            DeviceType::Target => "DeviceType.Target",
        }
    }

    fn __richcmp__(&self, other: &Self, op: pyo3::basic::CompareOp) -> bool {
        match op {
            pyo3::basic::CompareOp::Eq => self == other,
            pyo3::basic::CompareOp::Ne => self != other,
            _ => false,
        }
    }

    fn __hash__(&self) -> u64 {
        match self {
            DeviceType::Source => 0,
            DeviceType::Target => 1,
        }
    }

    /// Check if this is a source type
    fn is_source(&self) -> bool {
        matches!(self, DeviceType::Source)
    }

    /// Check if this is a target type
    fn is_target(&self) -> bool {
        matches!(self, DeviceType::Target)
    }
}

/// Represents a PipeWeaver audio device
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Device {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub device_type: DeviceType,
    #[pyo3(get)]
    pub is_physical: bool,
    #[pyo3(get)]
    pub volume: u8,
    #[pyo3(get)]
    pub is_muted: bool,
    #[pyo3(get)]
    pub color: Option<DeviceColor>,
}

#[pymethods]
impl Device {
    fn __repr__(&self) -> String {
        format!(
            "Device(id={:?}, name={:?}, type={:?}, vol={}%, muted={})",
            self.id, self.name, self.device_type, self.volume, self.is_muted
        )
    }
}

/// RGB color from device description
#[pyclass]
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct DeviceColor {
    #[pyo3(get)]
    pub red: u8,
    #[pyo3(get)]
    pub green: u8,
    #[pyo3(get)]
    pub blue: u8,
}

#[pymethods]
impl DeviceColor {
    #[new]
    fn new(red: u8, green: u8, blue: u8) -> Self {
        Self { red, green, blue }
    }

    fn rgba(&self) -> (u8, u8, u8, u8) {
        (self.red, self.green, self.blue, 255)
    }

    fn __repr__(&self) -> String {
        format!("DeviceColor({}, {}, {})", self.red, self.green, self.blue)
    }
}

/// Status data from PipeWeaver API
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Status {
    #[serde(default)]
    pub audio: AudioStatus,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AudioStatus {
    #[serde(default)]
    pub profile: ProfileStatus,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProfileStatus {
    #[serde(default)]
    pub devices: DevicesTree,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DevicesTree {
    #[serde(default)]
    pub sources: DeviceCategory,
    #[serde(default)]
    pub targets: DeviceCategory,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DeviceCategory {
    #[serde(default)]
    pub virtual_devices: Vec<RawDevice>,
    #[serde(default)]
    pub physical_devices: Vec<RawDevice>,
}

/// Raw device data as received from PipeWeaver API
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RawDevice {
    #[serde(default)]
    pub description: DeviceDescription,
    #[serde(default)]
    pub volume: Option<u8>,
    #[serde(default)]
    pub volumes: Option<VolumeSet>,
    #[serde(default)]
    pub mute_state: Option<String>,
    #[serde(default)]
    pub mute_states: Option<MuteStates>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DeviceDescription {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub colour: Option<ColorData>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ColorData {
    #[serde(default)]
    pub red: u8,
    #[serde(default)]
    pub green: u8,
    #[serde(default)]
    pub blue: u8,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VolumeSet {
    #[serde(default)]
    pub volume: BTreeMap<String, u8>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MuteStates {
    #[serde(default)]
    pub mute_state: Vec<String>,
}

impl Status {
    /// Get the devices tree from status
    pub fn devices_tree(&self) -> &DevicesTree {
        &self.audio.profile.devices
    }

    /// Get all source devices
    pub fn get_sources(&self) -> Vec<Device> {
        let tree = self.devices_tree();
        let mut devices = Vec::new();

        for raw in &tree.sources.virtual_devices {
            if let Some(device) = Self::convert_device(raw, DeviceType::Source, false) {
                devices.push(device);
            }
        }
        for raw in &tree.sources.physical_devices {
            if let Some(device) = Self::convert_device(raw, DeviceType::Source, true) {
                devices.push(device);
            }
        }

        devices
    }

    /// Get all target devices
    pub fn get_targets(&self) -> Vec<Device> {
        let tree = self.devices_tree();
        let mut devices = Vec::new();

        for raw in &tree.targets.virtual_devices {
            if let Some(device) = Self::convert_device(raw, DeviceType::Target, false) {
                devices.push(device);
            }
        }
        for raw in &tree.targets.physical_devices {
            if let Some(device) = Self::convert_device(raw, DeviceType::Target, true) {
                devices.push(device);
            }
        }

        devices
    }

    /// Get all devices as a flat list
    pub fn get_all_devices(&self) -> Vec<Device> {
        let mut devices = self.get_sources();
        devices.extend(self.get_targets());
        devices
    }

    /// Find a device by ID
    pub fn get_device(&self, device_id: &str, device_type: Option<DeviceType>) -> Option<Device> {
        self.get_all_devices()
            .into_iter()
            .find(|d| d.id == device_id && device_type.is_none_or(|t| d.device_type == t))
    }

    /// Convert raw device data to Device
    fn convert_device(raw: &RawDevice, device_type: DeviceType, is_physical: bool) -> Option<Device> {
        let id = raw.description.id.as_ref()?;
        let name = raw.description.name.as_ref()?;

        let volume = Self::extract_volume(raw, device_type);
        let is_muted = Self::extract_mute_state(raw, device_type);
        let color = raw.description.colour.as_ref().map(|c| DeviceColor {
            red: c.red,
            green: c.green,
            blue: c.blue,
        });

        Some(Device {
            id: id.clone(),
            name: name.clone(),
            device_type,
            is_physical,
            volume,
            is_muted,
            color,
        })
    }

    /// Extract volume from raw device, converting from 0-255 to 0-100 for sources
    fn extract_volume(raw: &RawDevice, device_type: DeviceType) -> u8 {
        match device_type {
            DeviceType::Source => {
                raw.volumes
                    .as_ref()
                    .and_then(|v| v.volume.get("A"))
                    .map(|&v| {
                        if v > 100 {
                            ((v as u16 * 100) / 255) as u8
                        } else {
                            v
                        }
                    })
                    .unwrap_or(50)
            }
            DeviceType::Target => {
                raw.volume.map(|v| {
                    if v > 100 {
                        ((v as u16 * 100) / 255) as u8
                    } else {
                        v
                    }
                }).unwrap_or(50)
            }
        }
    }

    /// Extract mute state from raw device
    fn extract_mute_state(raw: &RawDevice, device_type: DeviceType) -> bool {
        match device_type {
            DeviceType::Source => {
                raw.mute_states
                    .as_ref()
                    .is_some_and(|m| m.mute_state.contains(&"TargetA".to_string()))
            }
            DeviceType::Target => {
                raw.mute_state.as_ref().is_some_and(|s| s == "Muted")
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_device_type() {
        assert_eq!(DeviceType::source(), DeviceType::Source);
        assert_eq!(DeviceType::target(), DeviceType::Target);
    }

    #[test]
    fn test_device_color_rgba() {
        let color = DeviceColor::new(100, 150, 200);
        assert_eq!(color.rgba(), (100, 150, 200, 255));
    }
}
