"""PipeWeaver action for StreamController"""
import os
from typing import Any, Optional

from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLib", "2.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, GLib, Gdk, Gtk, GdkPixbuf

from src.backend.PluginManager.ActionBase import ActionBase  # type: ignore
import globals as gl
from typing import Final

# Volume settings
DEFAULT_VOLUME: Final[int] = 50  # Default volume percentage when device is first selected
DEFAULT_VOLUME_STEP: Final[int] = 5  # Default volume step size in percentage points (how much volume changes per button press/dial turn)
MIN_VOLUME_STEP: Final[int] = 5  # Minimum allowed volume step size in percentage points
MAX_VOLUME_STEP: Final[int] = 20  # Maximum allowed volume step size in percentage points
VOLUME_MIN: Final[int] = 0  # Minimum volume percentage (0%)
VOLUME_MAX: Final[int] = 100  # Maximum volume percentage (100%)
VOLUME_RAW_MAX: Final[int] = 255  # Maximum raw volume value from PipeWeaver API (0-255 range)

# SVG conversion settings
SVG_DEFAULT_SIZE: Final[tuple[int, int]] = (400, 400)  # Default size (width, height) in pixels for SVG icon conversion

# Color constants
COLOR_METER: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)  # Black color (RGBA) for audio level meter (default, can be overridden)
from .knob_renderer import KnobRenderer
from .volume_button_renderer import VolumeButtonRenderer
from .pipeweaver_helpers import DEVICE_TYPE_SOURCE, DEVICE_TYPE_TARGET, DeviceInfo, get_device_by_id, get_device_list, get_devices_tree
from .service_monitor import add_state_change_callback, is_service_available, remove_state_change_callback
from .svg_converter import is_svg_file, svg_to_pil
from .websocket_client import (
    MeterWebSocketClient,
    PipeWeaverWebSocketClient,
    acquire_shared_meter_client,
    acquire_shared_pipeweaver_client,
    release_shared_meter_client,
    release_shared_pipeweaver_client,
)

class PipeWeaverAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.client = acquire_shared_pipeweaver_client(self._on_patch_update)
        self.devices: list[DeviceInfo] = []
        self.selected_device_id: Optional[str] = None
        self.selected_device_name: Optional[str] = None
        self.selected_device_type: Optional[str] = None
        self.volume: int = DEFAULT_VOLUME
        self.volume_step: int = DEFAULT_VOLUME_STEP
        self.orientation: str = "vertical"  # "vertical" or "horizontal"
        self._is_initializing: bool = True
        self._device_color: dict[str, Any] = {}
        self._last_draw_state: Optional[tuple[Any, ...]] = None
        self.icon_path_from_picker: Optional[str] = None
        self._icon_cache: dict[str, Image.Image] = {}
        self._current_meter_a: int = 0
        self._current_meter_target: int = 0
        self._meter_client: Optional[MeterWebSocketClient] = None
        self._is_muted: bool = False
        self._meter_color: Optional[tuple[int, int, int, int]] = None
        self._volume_bar_color: Optional[tuple[int, int, int, int]] = None
        self._meters_enabled: bool = True
        self._meter_invert_color: bool = True
        self._is_loading_devices: bool = False
        self._cached_service_available: Optional[bool] = None
        
        self._load_settings()
        self._is_initializing = False
        self._start_meter_client()
        add_state_change_callback(self._on_service_state_change)
        self._load_devices_async()
    
    def _get_device_by_id(
        self, device_id: str, device_type: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        status_data = self.client._get_status()
        devices_tree = get_devices_tree(status_data)
        return get_device_by_id(devices_tree, device_id, device_type)
    
    def _toggle_mute(self) -> None:
        if not self.selected_device_id:
            return
        try:
            (self.client.unmute_device if self._is_muted else self.client.mute_device)(self.selected_device_id)
        except Exception as e:
            log.error(f"Error toggling mute: {e}")
    
    def _load_color_tuple(self, settings: dict, key: str, default: Optional[tuple[int, int, int, int]] = None) -> Optional[tuple[int, int, int, int]]:
        """Load color tuple from settings, validating format"""
        color = settings.get(key)
        if color and isinstance(color, (list, tuple)) and len(color) == 4:
            return tuple(int(c) for c in color)
        return default
    
    def _load_settings(self) -> None:
        settings = self.get_settings()
        if self.devices:
            self._load_device_settings(settings)
        
        self.volume_step = settings.get('volume_step', DEFAULT_VOLUME_STEP)
        self.orientation = settings.get('orientation', 'vertical')
        self.icon_path_from_picker = settings.get("icon_path_from_picker")
        
        self._meter_color = self._load_color_tuple(settings, "meter_color", COLOR_METER)
        self._volume_bar_color = self._load_color_tuple(settings, "volume_bar_color", None)
        
        self._meters_enabled = settings.get("meters_enabled", True)
        self._meter_invert_color = settings.get("meter_invert_color", True)
    
    def _load_devices(self) -> list[DeviceInfo]:
        if not self.client.connected:
            return []
        
        try:
            status_data = self.client._get_status()
            devices_tree = get_devices_tree(status_data)
            return get_device_list(devices_tree)
        except Exception as e:
            log.error(f"Error loading devices: {e}")
            return []
    
    def _ensure_connection_and_load_devices(self):
        if not self.devices and self.client.connected:
            self.devices = self._load_devices()
    
    def _load_devices_async(self) -> None:
        """Load devices asynchronously without blocking"""
        if self._is_loading_devices:
            return
        
        def do_load() -> bool:
            try:
                if not is_service_available():
                    return False
                
                if not self.client.connected:
                    GLib.timeout_add(200, do_load)
                    return False
                
                self._is_loading_devices = True
                self._last_draw_state = None
                self.update_image()
                
                self.devices = self._load_devices()
                
                if self.devices:
                    settings = self.get_settings()
                    self._load_device_settings(settings)
                
                self._is_loading_devices = False
                self._last_draw_state = None
                self.update_image()
                
            except Exception as e:
                log.error(f"Error loading devices asynchronously: {e}")
                self._is_loading_devices = False
                self._last_draw_state = None
                self.update_image()
            
            return False
        
        GLib.timeout_add(100, do_load)
    
    def _load_device_settings(self, settings: dict) -> None:
        saved_device_id = settings.get('device_id')
        self.devices = self._load_devices()
        
        if saved_device_id:
            device = next((d for d in self.devices if d['id'] == saved_device_id), None)
            if device:
                self._set_selected_device(device, settings, saved_device_id)
                return
        
        if self.devices:
            self._set_selected_device(self.devices[0], settings)
    
    def _update_device_from_api(self, status_data: Optional[dict[str, Any]] = None) -> None:
        try:
            if status_data is None:
                status_data = self.client._get_status()
            if not status_data:
                self._device_color = {}
                self._is_muted = False
                self._last_draw_state = None
                self._update_volume_bar_color_button()
                return
            
            devices_tree = get_devices_tree(status_data)
            device_data = get_device_by_id(devices_tree, self.selected_device_id, self.selected_device_type)
            if device_data:
                desc = device_data.get("description", {})
                
                new_name = desc.get("name")
                if new_name and new_name != self.selected_device_name:
                    self.selected_device_name = new_name
                    self._last_draw_state = None
                
                color = desc.get("colour", {})
                new_color = color if isinstance(color, dict) else {}
                if self._device_color != new_color:
                    self._device_color = new_color
                    self._last_draw_state = None
                
                if self.selected_device_type == DEVICE_TYPE_SOURCE:
                    mute_states = device_data.get("mute_states", {}).get("mute_state", [])
                    new_muted = "TargetA" in mute_states
                else:
                    new_muted = device_data.get("mute_state") == "Muted"
                
                if self._is_muted != new_muted:
                    self._is_muted = new_muted
                    self._last_draw_state = None
                
                new_volume = self._extract_volume_from_device_data(device_data)
                if self.volume != new_volume:
                    self.volume = new_volume
                    self._last_draw_state = None
            else:
                self._device_color = {}
                self._is_muted = False
                self._last_draw_state = None
            
            self._update_volume_bar_color_button()
        except Exception:
            self._device_color = {}
            self._is_muted = False
            self._last_draw_state = None
            self._update_volume_bar_color_button()
    
    def _create_rgba_from_color(self, color: Optional[tuple[int, int, int, int]] = None, device_color: Optional[dict[str, Any]] = None) -> Gdk.RGBA:
        """Create Gdk.RGBA from tuple color or device color dict"""
        rgba = Gdk.RGBA()
        if color:
            rgba.red = color[0] / 255.0
            rgba.green = color[1] / 255.0
            rgba.blue = color[2] / 255.0
            rgba.alpha = color[3] / 255.0
        elif device_color and 'red' in device_color and 'green' in device_color and 'blue' in device_color:
            rgba.red = device_color['red'] / 255.0
            rgba.green = device_color['green'] / 255.0
            rgba.blue = device_color['blue'] / 255.0
            rgba.alpha = 1.0
        else:
            rgba.red = 1.0
            rgba.green = 1.0
            rgba.blue = 1.0
            rgba.alpha = 1.0
        return rgba
    
    def _get_device_name_display(self, max_length: int = 25) -> str:
        """Get device name truncated for display"""
        return (self.selected_device_name[:max_length] if self.selected_device_name else "Loading...")
    
    def _set_all_labels(self, text: str, font_size: int = 14, only_if_service_available: bool = False) -> None:
        """Set text on all available labels (top, middle, bottom)"""
        if only_if_service_available and not is_service_available():
            text = ""
        if hasattr(self, 'set_top_label'):
            self.set_top_label(text, font_size=font_size)
        if hasattr(self, 'set_middle_label'):
            self.set_middle_label(text, font_size=font_size)
        if hasattr(self, 'set_bottom_label'):
            self.set_bottom_label(text, font_size=font_size)
    
    def _update_volume_bar_color_button(self) -> None:
        """Update the volume bar color button to show device color if no override is set"""
        if not hasattr(self, 'volume_bar_color_button') or self._volume_bar_color is not None:
            return
        
        self.volume_bar_color_button.set_rgba(
            self._create_rgba_from_color(device_color=self._device_color or {})
        )
    
    def _set_selected_device(
        self, device: DeviceInfo, settings: dict[str, Any], saved_device_id: Optional[str] = None
    ) -> None:
        self.selected_device_id = device['id']
        self.selected_device_name = device['name']
        self.selected_device_type = device['type']
        self._reset_meter_values()
        self._update_device_from_api()
        self._last_draw_state = None
        
        if saved_device_id != device['id']:
            settings['device_id'] = device['id']
            settings.pop('device_name', None)
            if not self._is_initializing:
                self.set_settings(settings)
    
    def _reset_meter_values(self) -> None:
        self._current_meter_a = 0
        self._current_meter_target = 0
    
    def _convert_raw_volume_with_step(self, vol_raw: int) -> int:
        volume = int((vol_raw / VOLUME_RAW_MAX) * 100) if vol_raw > 100 else vol_raw
        volume = round(volume / self.volume_step) * self.volume_step
        if volume >= 99:
            return VOLUME_MAX
        if volume <= 1:
            return VOLUME_MIN
        return volume
    
    def get_config_rows(self):
        if not is_service_available():
            error_row = Adw.ActionRow()
            error_row.set_title(self.plugin_base.lm.get("ui.error.not_running.title"))
            error_row.set_subtitle(self.plugin_base.lm.get("ui.error.not_running.subtitle"))
            error_row.add_css_class("warning")
            return [error_row]
        
        self._ensure_connection_and_load_devices()
        
        self._load_settings()
        
        self.device_model = Gtk.StringList()
        self.device_selector = Adw.ComboRow(
            model=self.device_model, 
            title=self.plugin_base.lm.get("ui.device.title")
        )
        
        self.device_selector.connect("notify::selected-item", self.on_device_changed)
        self._populate_device_list()
        
        refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=self.plugin_base.lm.get("ui.refresh_devices.button")
        )
        refresh_button.connect("clicked", self.on_refresh_clicked)
        self.device_selector.add_suffix(refresh_button)
        
        icon_row = Adw.ActionRow()
        icon_row.set_title(self.plugin_base.lm.get("ui.custom_icon.title"))
        
        icon_content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, valign=Gtk.Align.CENTER)
        
        self.icon_preview = Gtk.Image()
        self.icon_preview.set_size_request(20, 20)
        self.icon_preview.set_hexpand(False)
        self.icon_preview.set_vexpand(False)
        self.icon_preview.set_pixel_size(20)
        
        if self.icon_path_from_picker and os.path.exists(self.icon_path_from_picker):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    self.icon_path_from_picker,
                    width=20,
                    height=20,
                    preserve_aspect_ratio=True
                )
                self.icon_preview.set_from_pixbuf(pixbuf)
                icon_name = os.path.splitext(os.path.basename(self.icon_path_from_picker))[0]
                icon_row.set_subtitle(f"Selected: {icon_name}")
            except Exception:
                icon_row.set_subtitle("Select an icon from StreamController's icon packs")
                self.icon_preview.set_visible(False)
        else:
            icon_row.set_subtitle("Select an icon from StreamController's icon packs")
            self.icon_preview.set_visible(False)
        
        icon_content_box.append(self.icon_preview)
        
        icon_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon_picker_button = Gtk.Button(icon_name="folder-symbolic", valign=Gtk.Align.CENTER)
        icon_picker_button.set_tooltip_text("Choose icon")
        icon_picker_button.add_css_class("suggested-action")
        icon_picker_button.connect("clicked", self.on_icon_picker_clicked)
        icon_button_box.append(icon_picker_button)
        
        remove_icon_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        remove_icon_button.set_tooltip_text("Remove icon")
        remove_icon_button.connect("clicked", self.on_remove_icon_clicked)
        icon_button_box.append(remove_icon_button)
        
        icon_content_box.append(icon_button_box)
        icon_row.add_suffix(icon_content_box)
        self.icon_row = icon_row
        
        self.volume_step_row = Adw.SpinRow.new_with_range(MIN_VOLUME_STEP, MAX_VOLUME_STEP, 1)
        self.volume_step_row.set_title(self.plugin_base.lm.get("ui.volume_step.title"))
        self.volume_step_row.set_subtitle(self.plugin_base.lm.get("ui.volume_step.subtitle"))
        self.volume_step_row.set_value(self.get_settings().get("volume_step", DEFAULT_VOLUME_STEP))
        self.volume_step_row.connect("notify::value", self.on_volume_step_changed)

        meters_enabled_row = Adw.ActionRow()
        meters_enabled_row.set_title("Meters Enabled")
        meters_enabled_row.set_subtitle("Show audio level meters")
        
        self.meters_enabled_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meters_enabled_switch.set_active(self._meters_enabled)
        self.meters_enabled_switch.connect("notify::active", self.on_meters_enabled_changed)
        meters_enabled_row.add_suffix(self.meters_enabled_switch)

        meter_color_row = Adw.ActionRow()
        meter_color_row.set_title("Meter Color")
        meter_color_row.set_subtitle("Invert volume color or use custom color")
        
        meter_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.meter_invert_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meter_invert_switch.set_active(self._meter_invert_color)
        self.meter_invert_switch.connect("notify::active", self.on_meter_invert_changed)
        self.meter_invert_switch.set_sensitive(self._meters_enabled)
        meter_color_box.append(self.meter_invert_switch)
        
        self.meter_color_button = Gtk.ColorButton(valign=Gtk.Align.CENTER)
        self.meter_color_button.set_rgba(self._create_rgba_from_color(self._meter_color or COLOR_METER))
        self.meter_color_button.connect("color-set", self.on_meter_color_changed)
        self.meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        meter_color_box.append(self.meter_color_button)
        
        self.clear_meter_color_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.clear_meter_color_button.set_tooltip_text("Reset to default")
        self.clear_meter_color_button.connect("clicked", self.on_clear_meter_color_clicked)
        self.clear_meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        meter_color_box.append(self.clear_meter_color_button)
        
        meter_color_row.add_suffix(meter_color_box)

        volume_bar_color_row = Adw.ActionRow()
        volume_bar_color_row.set_title("Volume Bar Color")
        volume_bar_color_row.set_subtitle("Override the volume bar color")
        
        volume_bar_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.volume_bar_color_button = Gtk.ColorButton(valign=Gtk.Align.CENTER)
        
        device_color = self._device_color or {} if not self._volume_bar_color else None
        self.volume_bar_color_button.set_rgba(self._create_rgba_from_color(self._volume_bar_color, device_color))
        
        self.volume_bar_color_button.connect("color-set", self.on_volume_bar_color_changed)
        volume_bar_color_box.append(self.volume_bar_color_button)
        
        clear_volume_bar_color_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        clear_volume_bar_color_button.set_tooltip_text("Clear override")
        clear_volume_bar_color_button.connect("clicked", self.on_clear_volume_bar_color_clicked)
        volume_bar_color_box.append(clear_volume_bar_color_button)
        
        volume_bar_color_row.add_suffix(volume_bar_color_box)
        
        return [
            self.device_selector,
            icon_row,
            self.volume_step_row,
            meters_enabled_row,
            meter_color_row,
            volume_bar_color_row
        ]
    
    def _update_device_selection(self, device: DeviceInfo) -> None:
        self.selected_device_id = device['id']
        self.selected_device_name = device['name']
        self.selected_device_type = device['type']
        self._reset_meter_values()
        self._update_device_from_api()
        
        self._last_draw_state = None
        self.update_image()
        
        self._set_all_labels(self._get_device_name_display())
    
    def _populate_device_list(self) -> None:
        handler_blocked = False
        if hasattr(self, 'device_selector'):
            try:
                self.device_selector.handler_block_by_func(self.on_device_changed)
                handler_blocked = True
            except (AttributeError, TypeError):
                pass
        
        if hasattr(self, 'device_model'):
            while self.device_model.get_n_items() > 0:
                self.device_model.remove(0)
        
        self.devices = self._load_devices()
        
        for device in self.devices:
            self.device_model.append(device['name'])
        
        if self.selected_device_id:
            for i, device in enumerate(self.devices):
                if device['id'] == self.selected_device_id:
                    self.device_selector.set_selected(i)
                    if handler_blocked:
                        self.device_selector.handler_unblock_by_func(self.on_device_changed)
                    return
        
        if self.devices:
            self.device_selector.set_selected(0)
            if not self.selected_device_id:
                settings = self.get_settings()
                device = self.devices[0]
                settings["device_id"] = device['id']
                settings.pop("device_name", None)
                if not self._is_initializing:
                    self.set_settings(settings)
                    self._update_device_selection(device)
        
        if handler_blocked:
            self.device_selector.handler_unblock_by_func(self.on_device_changed)
    
    def on_device_changed(self, combo_row: Adw.ComboRow, *args: Any) -> None:
        selected_index = combo_row.get_selected()
        if selected_index is not None and selected_index < len(self.devices):
            device = self.devices[selected_index]
            settings = self.get_settings()
            settings["device_id"] = device['id']
            settings.pop("device_name", None)
            self.set_settings(settings)
            self._update_device_selection(device)
    
    def on_volume_step_changed(self, spin_row: Adw.SpinRow, *args: Any) -> None:
        volume_step = int(spin_row.get_value())
        settings = self.get_settings()
        settings["volume_step"] = volume_step
        self.set_settings(settings)
        self.volume_step = volume_step
    
    def on_meters_enabled_changed(self, switch: Gtk.Switch, *args: Any) -> None:
        self._meters_enabled = switch.get_active()
        settings = self.get_settings()
        settings["meters_enabled"] = self._meters_enabled
        self.set_settings(settings)
        
        if hasattr(self, 'meter_color_button'):
            self.meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        if hasattr(self, 'clear_meter_color_button'):
            self.clear_meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        if hasattr(self, 'meter_invert_switch'):
            self.meter_invert_switch.set_sensitive(self._meters_enabled)
        
        if self._meters_enabled:
            self._start_meter_client()
        else:
            self._current_meter_a = 0
            self._current_meter_target = 0
            self._stop_meter_client()
        
        self._last_draw_state = None
        self.update_image()
    
    def on_meter_invert_changed(self, switch: Gtk.Switch, *args: Any) -> None:
        self._meter_invert_color = switch.get_active()
        settings = self.get_settings()
        settings["meter_invert_color"] = self._meter_invert_color
        self.set_settings(settings)
        
        if hasattr(self, 'meter_color_button'):
            self.meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        if hasattr(self, 'clear_meter_color_button'):
            self.clear_meter_color_button.set_sensitive(self._meters_enabled and not self._meter_invert_color)
        
        self._last_draw_state = None
        self.update_image()
    
    def on_meter_color_changed(self, button: Gtk.ColorButton) -> None:
        rgba = button.get_rgba()
        self._meter_color = (
            int(rgba.red * 255),
            int(rgba.green * 255),
            int(rgba.blue * 255),
            int(rgba.alpha * 255)
        )
        settings = self.get_settings()
        settings["meter_color"] = list(self._meter_color)
        self.set_settings(settings)
        self._last_draw_state = None
        self.update_image()
    
    def on_clear_meter_color_clicked(self, button: Gtk.Button) -> None:
        self._meter_color = COLOR_METER
        settings = self.get_settings()
        settings["meter_color"] = list(self._meter_color)
        self.set_settings(settings)
        self._last_draw_state = None
        self.update_image()
        if hasattr(self, 'meter_color_button'):
            self.meter_color_button.set_rgba(self._create_rgba_from_color(COLOR_METER))
    
    def on_volume_bar_color_changed(self, button: Gtk.ColorButton) -> None:
        rgba = button.get_rgba()
        self._volume_bar_color = (
            int(rgba.red * 255),
            int(rgba.green * 255),
            int(rgba.blue * 255),
            int(rgba.alpha * 255)
        )
        settings = self.get_settings()
        settings["volume_bar_color"] = list(self._volume_bar_color)
        self.set_settings(settings)
        self._last_draw_state = None
        self.update_image()
    
    def on_clear_volume_bar_color_clicked(self, button: Gtk.Button) -> None:
        self._volume_bar_color = None
        settings = self.get_settings()
        settings.pop("volume_bar_color", None)
        self.set_settings(settings)
        self._last_draw_state = None
        self.update_image()
        if hasattr(self, 'volume_bar_color_button'):
            self.volume_bar_color_button.set_rgba(
                self._create_rgba_from_color(device_color=self._device_color or {})
            )

    def on_remove_icon_clicked(self, button: Gtk.Button, *args: Any) -> None:
        settings = self.get_settings()
        settings["icon_path_from_picker"] = None
        self.icon_path_from_picker = None
        self._icon_cache.clear()
        self.set_settings(settings)
        
        if hasattr(self, 'icon_preview'):
            self.icon_preview.set_visible(False)
            if hasattr(self, 'icon_row'):
                self.icon_row.set_subtitle("Select an icon from StreamController's icon packs")
        
        self._last_draw_state = None
        self.update_image()
        
    def on_icon_picker_clicked(self, button: Gtk.Button, *args: Any) -> None:
        try:
            if gl.app is None:
                return
            
            gl.app.let_user_select_asset(
                default_path="",
                callback_func=self.on_icon_selected_from_picker,
                callback_args=(),
                callback_kwargs={}
            )
        except Exception as e:
            log.error(f"Error opening icon picker: {e}")
    
    def on_icon_selected_from_picker(self, icon_path: str, *args: Any, **kwargs: Any) -> None:
        if not icon_path:
            return
        
        old_icon_path = self.icon_path_from_picker
        icon_changed = old_icon_path != icon_path
        
        settings = self.get_settings()
        settings["icon_path_from_picker"] = icon_path
        self.set_settings(settings)
        self.icon_path_from_picker = icon_path
        
        if old_icon_path and icon_changed:
            self._icon_cache.pop(old_icon_path, None)
        
        if hasattr(self, 'icon_preview') and os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    icon_path, width=20, height=20, preserve_aspect_ratio=True
                )
                self.icon_preview.set_from_pixbuf(pixbuf)
                self.icon_preview.set_visible(True)
                if hasattr(self, 'icon_row'):
                    icon_name = os.path.splitext(os.path.basename(icon_path))[0]
                    self.icon_row.set_subtitle(f"Selected: {icon_name}")
            except Exception:
                pass
        
        if icon_changed:
            self._last_draw_state = None
            self.update_image()
    
    def _get_icon(self) -> Optional[Image.Image]:
        if not self.icon_path_from_picker or not os.path.exists(self.icon_path_from_picker):
            return None
        
        if self.icon_path_from_picker in self._icon_cache:
            return self._icon_cache[self.icon_path_from_picker]
        
        try:
            if is_svg_file(self.icon_path_from_picker):
                image = svg_to_pil(self.icon_path_from_picker, SVG_DEFAULT_SIZE)
            else:
                image = Image.open(self.icon_path_from_picker)
                max_dimension = max(image.size)
                if max_dimension < 200:
                    scale = 400 / max_dimension
                    image = image.resize(
                        (int(image.width * scale), int(image.height * scale)),
                        Image.Resampling.LANCZOS
                    )
            
            self._icon_cache[self.icon_path_from_picker] = image
            return image
        except Exception as e:
            log.error(f"Error loading picker icon: {e}")
            return None
    
    def on_refresh_clicked(self, button: Gtk.Button) -> None:
        try:
            self._populate_device_list()
        except Exception as e:
            log.error(f"Error refreshing devices: {e}")
    
    def on_settings_changed(self, settings: dict[str, Any]) -> None:
        device_id = settings.get('device_id')
        if device_id:
            device = next((d for d in self.devices if d['id'] == device_id), None)
            if device:
                self._update_device_selection(device)
    
    def _set_volume(self, volume: int) -> None:
        if not self.selected_device_id or self._is_muted:
            return
        
        volume = max(VOLUME_MIN, min(VOLUME_MAX, int(volume)))
        
        try:
            self.client.set_volume(self.selected_device_id, volume)
        except Exception as e:
            log.error(f"Error setting volume: {e}")
    
    def _set_volume_relative(self, delta: int) -> None:
        if not self.selected_device_id or self._is_muted:
            return
        
        try:
            delta = int(delta)
        except (ValueError, TypeError):
            return

        try:
            current_volume = self._get_current_volume() or 0
            if (current_volume >= VOLUME_MAX and delta > 0) or (current_volume <= VOLUME_MIN and delta < 0):
                return
            
            self.client.set_volume_relative(self.selected_device_id, delta, current_volume)
        except Exception as e:
            log.error(f"Error setting volume relative: {e}")
    
    def _extract_volume_from_device_data(self, device_data: dict[str, Any]) -> int:
        if self.selected_device_type == DEVICE_TYPE_SOURCE:
            volumes_dict = device_data.get("volumes", {})
            volume_dict = volumes_dict.get("volume", {}) if isinstance(volumes_dict, dict) else {}
            if isinstance(volume_dict, dict):
                vol_raw = volume_dict.get("A", 0)
                return self._convert_raw_volume_with_step(vol_raw)
            return 0
        else:
            vol_raw = device_data.get("volume", 0)
            return self._convert_raw_volume_with_step(vol_raw)
    
    def _get_current_volume(self) -> Optional[int]:
        if not self.selected_device_id:
            return None
        
        try:
            device_data = self._get_device_by_id(self.selected_device_id, self.selected_device_type)
            if device_data:
                return self._extract_volume_from_device_data(device_data)
        except Exception as e:
            log.error(f"Error getting current volume: {e}")
        
        return None
    
    def on_enable(self):
        self.devices = []
        self._load_settings()
        self._last_draw_state = None
        self._load_devices_async()
        self.update_image()
    
    def on_ready(self):
        self.on_enable()
        
        self._set_all_labels(self._get_device_name_display())
        
        self._start_meter_client()
        self._last_draw_state = None
        
        if not self.devices and not self._is_loading_devices:
            self._load_devices_async()
        
        self.update_image()
    
    def on_disable(self):
        release_shared_pipeweaver_client(self._on_patch_update)
        remove_state_change_callback(self._on_service_state_change)
        self._stop_meter_client()
    
    def _on_service_state_change(self, available: bool) -> None:
        # Update cached service availability
        self._cached_service_available = available
        if available:
            self._load_devices_async()
        else:
            self._last_draw_state = None
            self.update_image()
    
    def _meter_callback(self, node_id: str, percent: int) -> None:
        if not self._meters_enabled:
            return
        
        if node_id != self.selected_device_id:
            return

        # Only update if meter value actually changed
        if self.selected_device_type == DEVICE_TYPE_SOURCE:
            if self._current_meter_a == percent:
                return
            self._current_meter_a = percent
        elif self.selected_device_type == DEVICE_TYPE_TARGET:
            if self._current_meter_target == percent:
                return
            self._current_meter_target = percent

        self.update_image()
    
    def _start_meter_client(self):
        if not self._meters_enabled:
            return
        try:
            if self._meter_client is None:
                self._meter_client = acquire_shared_meter_client(self._meter_callback)
        except Exception as e:
            log.error(f"Error starting meter client: {e}")
    
    def _stop_meter_client(self):
        try:
            if self._meter_client:
                release_shared_meter_client(self._meter_callback)
                self._meter_client = None
        except Exception as e:
            log.error(f"Error stopping meter client: {e}")
    
    def _on_patch_update(self, status: dict[str, Any]) -> None:
        if not self.selected_device_id:
            return
        try:
            devices_tree = get_devices_tree(status)
            device_data = get_device_by_id(devices_tree, self.selected_device_id, self.selected_device_type)
            if device_data:
                self.volume = self._extract_volume_from_device_data(device_data)
                old_name = self.selected_device_name
                self._update_device_from_api(status)
                if old_name != self.selected_device_name:
                    self._set_all_labels(self._get_device_name_display())
                self.update_image()
        except Exception as e:
            log.error(f"Error handling patch update: {e}")
    
    def update_image(self):
        icon_path = self.icon_path_from_picker
        if icon_path:
            try:
                icon_path = os.path.abspath(os.path.normpath(icon_path))
            except Exception:
                pass

        device_color_tuple = tuple(sorted(self._device_color.items())) if self._device_color else ()
        
        # Cache service availability to avoid calling it on every update
        # Only refresh if we don't have a cached value or if it might have changed
        service_available = getattr(self, '_cached_service_available', None)
        if service_available is None:
            service_available = is_service_available()
            self._cached_service_available = service_available
        
        current_state = (
            self.selected_device_id,
            self.selected_device_type,
            self.selected_device_name,
            self.volume,
            self._current_meter_a,
            self._current_meter_target,
            self._is_muted,
            icon_path,
            self._meter_color,
            self._volume_bar_color,
            device_color_tuple,
            service_available,
            self.orientation,
        )

        if self._last_draw_state == current_state:
            return

        self._last_draw_state = current_state

        def _do_render():
            try:
                self._set_all_labels(self._get_device_name_display(), only_if_service_available=True)

                # Use appropriate renderer based on action type
                from .volume_up_button_action import PipeWeaverVolumeUpButtonAction
                from .volume_down_button_action import PipeWeaverVolumeDownButtonAction
                from .slider_action import PipeWeaverSliderAction
                from .slider_button_renderer import SliderButtonRenderer
                from .volume_button_renderer import VolumeButtonRenderer
                
                if isinstance(self, PipeWeaverVolumeUpButtonAction):
                    image_renderer = VolumeButtonRenderer(self, is_plus=True)
                elif isinstance(self, PipeWeaverVolumeDownButtonAction):
                    image_renderer = VolumeButtonRenderer(self, is_plus=False)
                elif isinstance(self, PipeWeaverSliderAction):
                    image_renderer = SliderButtonRenderer(self)
                else:
                    image_renderer = KnobRenderer(self)
                
                image_renderer.render_image()
            except Exception as e:
                log.error(f"Error rendering image: {e}")
            return False

        GLib.idle_add(_do_render)
