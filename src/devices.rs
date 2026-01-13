//! Device types and helpers for working with PipeWeaver audio devices

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use pipeweaver_profile::{
    Devices,
    VirtualSourceDevice,
    PhysicalSourceDevice,
    VirtualTargetDevice,
    PhysicalTargetDevice,
};
use pipeweaver_shared::MuteTarget;

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
/// Uses the same JSON structure as pipeweaver for compatibility
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
    pub devices: Devices,
}

// Use pipeweaver types directly - Devices is the devices tree

impl Status {
    /// Get the devices tree from status
    pub fn devices_tree(&self) -> &Devices {
        &self.audio.profile.devices
    }

    /// Get all source devices
    pub fn get_sources(&self) -> Vec<Device> {
        let tree = self.devices_tree();
        let mut devices = Vec::new();

        for raw in &tree.sources.virtual_devices {
            if let Some(device) = Self::convert_virtual_source(raw) {
                devices.push(device);
            }
        }
        for raw in &tree.sources.physical_devices {
            if let Some(device) = Self::convert_physical_source(raw) {
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
            if let Some(device) = Self::convert_virtual_target(raw) {
                devices.push(device);
            }
        }
        for raw in &tree.targets.physical_devices {
            if let Some(device) = Self::convert_physical_target(raw) {
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

    /// Convert virtual source device
    fn convert_virtual_source(raw: &VirtualSourceDevice) -> Option<Device> {
        Self::convert_source_common(&raw.description, &raw.volumes, &raw.mute_states, false)
    }

    /// Convert physical source device
    fn convert_physical_source(raw: &PhysicalSourceDevice) -> Option<Device> {
        Self::convert_source_common(&raw.description, &raw.volumes, &raw.mute_states, true)
    }

    /// Convert virtual target device
    fn convert_virtual_target(raw: &VirtualTargetDevice) -> Option<Device> {
        Self::convert_target_common(&raw.description, &raw.volume, &raw.mute_state, false)
    }

    /// Convert physical target device
    fn convert_physical_target(raw: &PhysicalTargetDevice) -> Option<Device> {
        Self::convert_target_common(&raw.description, &raw.volume, &raw.mute_state, true)
    }

    /// Common conversion logic for sources
    fn convert_source_common(
        description: &pipeweaver_profile::DeviceDescription,
        volumes: &pipeweaver_profile::Volumes,
        mute_states: &pipeweaver_profile::MuteStates,
        is_physical: bool,
    ) -> Option<Device> {
        let id = description.id.to_string();
        let name = description.name.clone();

        // Get volume for channel A (TargetA) - EnumMap iteration
        // Find the volume for TargetA channel
        let volume_val = volumes.volume
            .iter()
            .find(|(k, _)| format!("{:?}", k).contains("A"))
            .map(|(_, &v)| v)
            .unwrap_or_else(|| volumes.volume.values().next().copied().unwrap_or(50));
        let volume = if volume_val > 100 {
            ((volume_val as u16 * 100) / 255) as u8
        } else {
            volume_val
        };

        let is_muted = mute_states
            .mute_state
            .contains(&MuteTarget::TargetA);

        let color = Some(DeviceColor {
            red: description.colour.red,
            green: description.colour.green,
            blue: description.colour.blue,
        });

        Some(Device {
            id: id.clone(),
            name: name.clone(),
            device_type: DeviceType::Source,
            is_physical,
            volume,
            is_muted,
            color,
        })
    }

    /// Common conversion logic for targets
    fn convert_target_common(
        description: &pipeweaver_profile::DeviceDescription,
        volume: &u8,
        mute_state: &pipeweaver_shared::MuteState,
        is_physical: bool,
    ) -> Option<Device> {
        let id = description.id.to_string();
        let name = description.name.clone();

        let volume = if *volume > 100 {
            ((*volume as u16 * 100) / 255) as u8
        } else {
            *volume
        };

        let is_muted = matches!(mute_state, pipeweaver_shared::MuteState::Muted);

        let color = Some(DeviceColor {
            red: description.colour.red,
            green: description.colour.green,
            blue: description.colour.blue,
        });

        Some(Device {
            id: id.clone(),
            name: name.clone(),
            device_type: DeviceType::Target,
            is_physical,
            volume,
            is_muted,
            color,
        })
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
