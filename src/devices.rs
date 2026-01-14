use parking_lot::RwLock;
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use pipeweaver_profile::{
    Devices,
    VirtualSourceDevice,
    PhysicalSourceDevice,
    VirtualTargetDevice,
    PhysicalTargetDevice,
};
use pipeweaver_shared::MuteTarget;

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

    fn is_source(&self) -> bool {
        matches!(self, DeviceType::Source)
    }

    fn is_target(&self) -> bool {
        matches!(self, DeviceType::Target)
    }
}

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

#[derive(Debug, Serialize, Deserialize)]
pub struct Status {
    #[serde(default)]
    pub audio: AudioStatus,
    #[serde(skip)]
    device_index: RwLock<Option<HashMap<String, Device>>>,
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

impl Default for Status {
    fn default() -> Self {
        Self {
            audio: AudioStatus::default(),
            device_index: RwLock::new(None),
        }
    }
}

impl Clone for Status {
    fn clone(&self) -> Self {
        Self {
            audio: self.audio.clone(),
            device_index: RwLock::new(None),
        }
    }
}

impl Status {
    pub fn devices_tree(&self) -> &Devices {
        &self.audio.profile.devices
    }

    pub(crate) fn rebuild_index(&self) {
        let mut index = HashMap::new();
        for device in self.get_all_devices() {
            index.insert(device.id.clone(), device);
        }
        *self.device_index.write() = Some(index);
    }


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

    pub fn get_all_devices(&self) -> Vec<Device> {
        let mut devices = self.get_sources();
        devices.extend(self.get_targets());
        devices
    }

    pub fn get_device(&self, device_id: &str, device_type: Option<DeviceType>) -> Option<Device> {
        {
            let index_guard = self.device_index.read();
            if index_guard.is_none() {
                drop(index_guard);
                self.rebuild_index();
            }
        }
        
        let index_guard = self.device_index.read();
        if let Some(ref index) = *index_guard {
            index.get(device_id).and_then(|d| {
                if device_type.is_none_or(|t| d.device_type == t) {
                    Some(d.clone())
                } else {
                    None
                }
            })
        } else {
            self.get_all_devices()
                .into_iter()
                .find(|d| d.id == device_id && device_type.is_none_or(|t| d.device_type == t))
        }
    }

    fn convert_virtual_source(raw: &VirtualSourceDevice) -> Option<Device> {
        Self::convert_source_common(&raw.description, &raw.volumes, &raw.mute_states, false)
    }

    fn convert_physical_source(raw: &PhysicalSourceDevice) -> Option<Device> {
        Self::convert_source_common(&raw.description, &raw.volumes, &raw.mute_states, true)
    }

    fn convert_virtual_target(raw: &VirtualTargetDevice) -> Option<Device> {
        Self::convert_target_common(&raw.description, &raw.volume, &raw.mute_state, false)
    }

    fn convert_physical_target(raw: &PhysicalTargetDevice) -> Option<Device> {
        Self::convert_target_common(&raw.description, &raw.volume, &raw.mute_state, true)
    }

    fn convert_source_common(
        description: &pipeweaver_profile::DeviceDescription,
        volumes: &pipeweaver_profile::Volumes,
        mute_states: &pipeweaver_profile::MuteStates,
        is_physical: bool,
    ) -> Option<Device> {
        let id = description.id.to_string();
        let name = description.name.clone();

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

pub(crate) fn apply_patch_op(doc: &mut serde_json::Value, op: &serde_json::Value) -> Result<(), String> {
    let operation = op.get("op").and_then(|v| v.as_str()).ok_or("Missing op")?;
    let path = op
        .get("path")
        .and_then(|v| v.as_str())
        .ok_or("Missing path")?;

    let (parent, key) = resolve_pointer_parent(doc, path)?;

    match operation {
        "add" | "replace" => {
            let value = op.get("value").cloned().ok_or("Missing value")?;
            match parent {
                serde_json::Value::Array(arr) => {
                    if key == "-" {
                        arr.push(value);
                    } else {
                        let idx: usize = key.parse().map_err(|_| "Invalid array index")?;
                        if idx >= arr.len() {
                            arr.push(value);
                        } else {
                            arr[idx] = value;
                        }
                    }
                }
                serde_json::Value::Object(obj) => {
                    obj.insert(key, value);
                }
                _ => return Err("Parent is not a container".into()),
            }
        }
        "remove" => match parent {
            serde_json::Value::Array(arr) => {
                let idx: usize = key.parse().map_err(|_| "Invalid array index")?;
                if idx < arr.len() {
                    arr.remove(idx);
                }
            }
            serde_json::Value::Object(obj) => {
                obj.remove(&key);
            }
            _ => return Err("Parent is not a container".into()),
        },
        _ => {
            tracing::warn!("Unsupported patch operation: {}", operation);
        }
    }

    Ok(())
}

fn resolve_pointer_parent<'a>(
    doc: &'a mut serde_json::Value,
    path: &str,
) -> Result<(&'a mut serde_json::Value, String), String> {
    if !path.starts_with('/') {
        return Err("Path must start with /".into());
    }

    let parts: Vec<String> = path[1..]
        .split('/')
        .map(|p| p.replace("~1", "/").replace("~0", "~"))
        .collect();

    if parts.is_empty() {
        return Err("Empty path".into());
    }

    let key = parts.last().ok_or("Empty path")?.clone();
    let parent_path = &parts[..parts.len() - 1];

    let mut current = doc;
    for part in parent_path {
        current = match current {
            serde_json::Value::Array(arr) => {
                let idx: usize = part.parse().map_err(|_| "Invalid array index")?;
                arr.get_mut(idx).ok_or("Array index out of bounds")?
            }
            serde_json::Value::Object(obj) => obj.entry(part.as_str()).or_insert(serde_json::Value::Object(Default::default())),
            _ => return Err("Cannot traverse non-container".into()),
        };
    }

    Ok((current, key))
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
