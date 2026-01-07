"""Helper functions for working with PipeWeaver devices"""
from typing import Any, Final, Optional

# Device types
DEVICE_TYPE_SOURCE: Final[str] = "source"  # Device type identifier for input/source devices
DEVICE_TYPE_TARGET: Final[str] = "target"  # Device type identifier for output/target devices


DeviceInfo = dict[str, str]
DeviceData = dict[str, Any]
DevicesTree = dict[str, Any]
StatusData = dict[str, Any]


def get_devices_tree(status: Optional[StatusData]) -> DevicesTree:
    if not status:
        return {}
    return status.get("audio", {}).get("profile", {}).get("devices", {})


def _extract_device_info(device_data: DeviceData, device_type: str, is_physical: bool = False) -> Optional[DeviceInfo]:
    device_id = device_data.get("description", {}).get("id")
    device_name = device_data.get("description", {}).get("name")
    
    if device_id and device_name and "Monitor" not in device_name:
        return {"id": device_id, "name": device_name, "type": device_type, "is_physical": is_physical}
    return None


def get_device_list(devices_tree: DevicesTree) -> list[DeviceInfo]:
    if not devices_tree:
        return []
    
    devices: list[DeviceInfo] = []
    try:
        for subsection in ("virtual_devices", "physical_devices"):
            is_physical = subsection == "physical_devices"
            for device_data in devices_tree.get("sources", {}).get(subsection, []):
                device_info = _extract_device_info(device_data, DEVICE_TYPE_SOURCE, is_physical)
                if device_info:
                    devices.append(device_info)
        
        for subsection in ("virtual_devices", "physical_devices"):
            is_physical = subsection == "physical_devices"
            for device_data in devices_tree.get("targets", {}).get(subsection, []):
                device_info = _extract_device_info(device_data, DEVICE_TYPE_TARGET, is_physical)
                if device_info:
                    devices.append(device_info)
    except Exception:
        pass
    
    return devices

def sort_device_list(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """Sort devices consistently by type, physical status, and name"""
    if not devices:
        return devices
    
    # Sort by: type (source first), physical status (physical first), then name alphabetically
    return sorted(devices, key=lambda x: (x['type'], not x.get('is_physical', False), x['name'].lower()))


def get_device_by_id(
    devices_tree: DevicesTree,
    device_id: str,
    device_type: Optional[str] = None
) -> Optional[DeviceData]:
    if not devices_tree or not device_id:
        return None
    
    sections: list[tuple[str, str]] = [
        ("sources", "virtual_devices"),
        ("sources", "physical_devices"),
        ("targets", "virtual_devices"),
        ("targets", "physical_devices")
    ]
    if device_type == DEVICE_TYPE_SOURCE:
        sections = [("sources", "virtual_devices"), ("sources", "physical_devices")]
    elif device_type == DEVICE_TYPE_TARGET:
        sections = [("targets", "virtual_devices"), ("targets", "physical_devices")]
    
    for section, subsection in sections:
        for device in devices_tree.get(section, {}).get(subsection, []):
            if device.get("description", {}).get("id") == device_id:
                return device
    
    return None
