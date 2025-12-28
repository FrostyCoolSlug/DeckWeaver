"""PipeWeaver action for StreamController"""
import os
import time
from typing import Any, Optional

from PIL import Image  # type: ignore
from loguru import logger as log  # type: ignore

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLib", "2.0")
from gi.repository import Adw, GLib, Gtk

from src.backend.PluginManager.ActionBase import ActionBase  # type: ignore
import globals as gl

from .constants import (
    DEFAULT_VOLUME,
    DEFAULT_VOLUME_STEP,
    DEVICE_TYPE_SOURCE,
    DEVICE_TYPE_TARGET,
    MAX_VOLUME_STEP,
    MIN_VOLUME_STEP,
    SVG_DEFAULT_SIZE,
    VOLUME_MAX,
    VOLUME_MIN,
    VOLUME_RAW_MAX,
)
from .image_renderer import ImageRenderer
from .pipeweaver_helpers import DeviceInfo, get_device_by_id, get_device_list, get_devices_tree
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
        self._is_initializing: bool = True
        self._device_color: dict[str, Any] = {}
        self._render_idle_source: Optional[int] = None
        self._last_draw_state: Optional[tuple[Any, ...]] = None
        self.icon_path_from_picker: Optional[str] = None
        self._icon_cache: dict[str, Image.Image] = {}
        self._current_meter_a: int = 0
        self._current_meter_target: int = 0
        self._meter_client: Optional[MeterWebSocketClient] = None
        self._is_muted: bool = False
        self.client: PipeWeaverWebSocketClient
        
        self._load_settings()
        self._is_initializing = False
        self._start_meter_client()
        add_state_change_callback(self._on_service_state_change)
    
    def _get_device_by_id(
        self, device_id: str, device_type: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        status_data = self.client._get_status()
        devices_tree = get_devices_tree(status_data)
        return get_device_by_id(devices_tree, device_id, device_type)
    
    def _toggle_mute_source(self) -> None:
        if self._is_muted:
            self.client.unmute_device(self.selected_device_id)
        else:
            self.client.mute_device(self.selected_device_id)
    
    def _toggle_mute_target(self) -> None:
        if self._is_muted:
            self.client.unmute_device(self.selected_device_id)
        else:
            self.client.mute_device(self.selected_device_id)
    
    def _toggle_mute(self) -> None:
        if not self.selected_device_id:
            return
        try:
            if self.selected_device_type == DEVICE_TYPE_SOURCE:
                self._toggle_mute_source()
            else:
                self._toggle_mute_target()
        except Exception as e:
            log.error(f"Error toggling mute: {e}")
    
    def _load_settings(self) -> None:
        settings = self.get_settings()
        self._ensure_connection_and_load_devices()
        self._load_device_settings(settings)
        self.volume_step = settings.get('volume_step', DEFAULT_VOLUME_STEP)
        self.icon_path_from_picker = settings.get("icon_path_from_picker")
    
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
    
    def _update_device_from_api(self) -> None:
        try:
            status_data = self.client._get_status()
            if not status_data:
                self._device_color = {}
                self._is_muted = False
                return
            
            device_data = self._get_device_by_id(self.selected_device_id, self.selected_device_type)
            if device_data:
                desc = device_data.get("description", {})
                color = desc.get("colour", {})
                self._device_color = color if isinstance(color, dict) else {}
                
                if self.selected_device_type == DEVICE_TYPE_SOURCE:
                    mute_states = device_data.get("mute_states", {}).get("mute_state", [])
                    self._is_muted = "TargetA" in mute_states
                else:
                    self._is_muted = device_data.get("mute_state") == "Muted"
            else:
                self._device_color = {}
                self._is_muted = False
        except Exception:
            self._device_color = {}
            self._is_muted = False
    
    def _set_selected_device(
        self, device: DeviceInfo, settings: dict[str, Any], saved_device_id: Optional[str] = None
    ) -> None:
        self.selected_device_id = device['id']
        self.selected_device_name = device['name']
        self.selected_device_type = device['type']
        self._reset_meter_values()
        self._update_device_from_api()
        
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
            volume = VOLUME_MAX
        elif volume <= 1:
            volume = VOLUME_MIN
        return volume
    
    def get_config_rows(self):
        self._ensure_connection_and_load_devices()
        
        test_devices = []
        if self.client.connected:
            for _ in range(3):
                test_devices = self._load_devices()
                if test_devices:
                    break
                time.sleep(0.2)
        
        if not test_devices:
            error_row = Adw.ActionRow()
            error_row.set_title(self.plugin_base.lm.get("ui.error.not_running.title"))
            error_row.set_subtitle(self.plugin_base.lm.get("ui.error.not_running.subtitle"))
            error_row.add_css_class("warning")
            return [error_row]
        
        self._load_settings()
        
        self.device_model = Gtk.StringList()
        self.device_selector = Adw.ComboRow(
            model=self.device_model, 
            title=self.plugin_base.lm.get("ui.device.title")
        )
        
        self.device_selector.connect("notify::selected-item", self.on_device_changed)
        self._populate_device_list()
        
        icon_expander = Adw.ExpanderRow()
        icon_expander.set_title(self.plugin_base.lm.get("ui.custom_icon.title"))
        icon_expander.set_subtitle(self.plugin_base.lm.get("ui.custom_icon.subtitle"))
        
        icon_picker_row = Adw.ActionRow()
        icon_picker_row.set_title("Browse Icon Library")
        
        if self.icon_path_from_picker:
            icon_name = os.path.splitext(os.path.basename(self.icon_path_from_picker))[0]
            icon_picker_row.set_subtitle(f"Selected: {icon_name}")
        else:
            icon_picker_row.set_subtitle("Select an icon from StreamController's icon packs")
        
        icon_picker_button = Gtk.Button(label="Choose Icon")
        icon_picker_button.add_css_class("suggested-action")
        icon_picker_button.connect("clicked", self.on_icon_picker_clicked)
        icon_picker_row.add_suffix(icon_picker_button)
        icon_expander.add_row(icon_picker_row)
        
        remove_icon_row = Adw.ActionRow()
        remove_icon_row.set_title("Remove Icon")
        remove_icon_row.set_subtitle("Clear the selected icon")
        
        remove_icon_button = Gtk.Button(label="Remove")
        remove_icon_button.add_css_class("destructive-action")
        remove_icon_button.connect("clicked", self.on_remove_icon_clicked)
        remove_icon_row.add_suffix(remove_icon_button)
        icon_expander.add_row(remove_icon_row)
        
        self.volume_step_row = Adw.SpinRow.new_with_range(MIN_VOLUME_STEP, MAX_VOLUME_STEP, 1)
        self.volume_step_row.set_title(self.plugin_base.lm.get("ui.volume_step.title"))
        self.volume_step_row.set_subtitle(self.plugin_base.lm.get("ui.volume_step.subtitle"))
        
        settings = self.get_settings()
        volume_step = settings.get("volume_step", DEFAULT_VOLUME_STEP)
        self.volume_step_row.set_value(volume_step)
        self.volume_step_row.connect("notify::value", self.on_volume_step_changed)

        refresh_btn = Gtk.Button.new_with_label(self.plugin_base.lm.get("ui.refresh_devices.button"))
        refresh_btn.add_css_class("suggested-action")
        refresh_btn.set_margin_top(24)
        refresh_btn.set_margin_bottom(12)
        refresh_btn.connect("clicked", self.on_refresh_clicked)
        
        return [
            self.device_selector,
            icon_expander,
            self.volume_step_row,
            refresh_btn
        ]
    
    def _update_device_selection(self, device: DeviceInfo) -> None:
        self.selected_device_id = device['id']
        self.selected_device_name = device['name']
        self.selected_device_type = device['type']
        self._reset_meter_values()
        self._update_device_from_api()
        
        self._last_draw_state = None
        self.update_image()
        
        if hasattr(self, 'set_top_label'):
            device_name = (self.selected_device_name[:25] 
                          if self.selected_device_name else "Unknown")
            self.set_top_label(device_name, font_size=14)
    
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

    def on_remove_icon_clicked(self, button: Gtk.Button, *args: Any) -> None:
        settings = self.get_settings()
        settings["icon_path_from_picker"] = None
        self.icon_path_from_picker = None
        self._icon_cache.clear()
        self.set_settings(settings)
        
        # Clear last draw state to force redraw without icon
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
        self.icon_path_from_picker = icon_path
        settings = self.get_settings()
        settings["icon_path_from_picker"] = icon_path
        self.set_settings(settings)
        
        # Clear last draw state to force redraw with new icon
        self._last_draw_state = None
        self.update_image()
    
    def _get_icon(self) -> Optional[Image.Image]:
        if not self.icon_path_from_picker or not os.path.exists(self.icon_path_from_picker):
            return None
        
        try:
            cache_key = self.icon_path_from_picker
            if cache_key in self._icon_cache:
                return self._icon_cache[cache_key]
            
            if is_svg_file(self.icon_path_from_picker):
                image = svg_to_pil(self.icon_path_from_picker, SVG_DEFAULT_SIZE)
            else:
                image = Image.open(self.icon_path_from_picker)
                width, height = image.size
                max_dimension = max(width, height)
                
                if max_dimension < 200:
                    upscale_factor = 400 / max_dimension
                    new_width = int(width * upscale_factor)
                    new_height = int(height * upscale_factor)
                    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            self._icon_cache[cache_key] = image
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
        if self.client.connected:
            self.devices = self._load_devices()
        else:
            self.devices = []

        self._load_settings()
        self._last_draw_state = None
        self._render_idle_source = None
        self.update_image()
    
    def on_ready(self):
        self.on_enable()
        
        if hasattr(self, 'set_top_label'):
            device_name = self.selected_device_name[:25] if self.selected_device_name else "Unknown"
            self.set_top_label(device_name, font_size=14)
        
        self._start_meter_client()
        self._last_draw_state = None
        self.update_image()
    
    def on_disable(self):
        release_shared_pipeweaver_client(self._on_patch_update)
        remove_state_change_callback(self._on_service_state_change)
        self._stop_meter_client()
    
    def _on_service_state_change(self, available: bool) -> None:
        if available:
            def refresh_after_service_available() -> bool:
                try:
                    self.devices = self._load_devices()
                    
                    if self.selected_device_id:
                        self._update_device_from_api()
                        current_volume = self._get_current_volume()
                        if current_volume is not None:
                            self.volume = current_volume
                    
                    self._last_draw_state = None
                    self.update_image()
                except Exception as e:
                    log.warning(f"Error refreshing after service became available: {e}")
                return False
            
            GLib.timeout_add(500, refresh_after_service_available)
        else:
            self._last_draw_state = None
            self.update_image()
    
    def _meter_callback(self, node_id: str, percent: int) -> None:
        if node_id != self.selected_device_id:
            return

        if self.selected_device_type == DEVICE_TYPE_SOURCE:
            self._current_meter_a = percent
        elif self.selected_device_type == DEVICE_TYPE_TARGET:
            self._current_meter_target = percent

        self.update_image()
    
    def _start_meter_client(self):
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
            device_data = self._get_device_by_id(self.selected_device_id, self.selected_device_type)
            if device_data:
                self.volume = self._extract_volume_from_device_data(device_data)
                self._update_device_from_api()
                self.update_image()
        except Exception as e:
            log.error(f"Error handling patch update: {e}")
    
    def update_image(self):
        try:
            selected_mixes_tuple = tuple(sorted(self.selected_mixes)) if hasattr(self, "selected_mixes") else tuple()
        except Exception:
            selected_mixes_tuple = tuple()

        current_state = (
            self.selected_device_id,
            self.selected_device_type,
            getattr(self, "volume", None),
            getattr(self, "_current_meter_a", None),
            getattr(self, "_current_meter_target", None),
            getattr(self, "_is_muted", None),
            getattr(self, "icon_path_from_picker", None),
            selected_mixes_tuple,
            is_service_available(),
        )

        if getattr(self, "_last_draw_state", None) == current_state:
            return

        if getattr(self, "_render_idle_source", None) is not None:
            return

        def _do_render(state_snapshot=current_state):
            render_success = False
            try:
                if hasattr(self, 'set_top_label'):
                    device_name = self.selected_device_name[:25] if self.selected_device_name else "Unknown"
                    self.set_top_label(device_name, font_size=14)

                if not hasattr(self, '_image_renderer'):
                    self._image_renderer = ImageRenderer(self)
                self._image_renderer.render_image()
                render_success = True
            except Exception as e:
                log.error(f"Error rendering image: {e}")
                try:
                    if not is_service_available():
                        if not hasattr(self, '_image_renderer'):
                            self._image_renderer = ImageRenderer(self)
                        image = self._image_renderer._render_service_unavailable()
                        if image:
                            self._image_renderer._set_image_on_action(image)
                            render_success = True
                except Exception:
                    pass
            finally:
                self._render_idle_source = None
                if render_success:
                    self._last_draw_state = state_snapshot
            return False

        self._render_idle_source = GLib.idle_add(_do_render)
