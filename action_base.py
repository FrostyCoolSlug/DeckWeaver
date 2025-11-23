from src.backend.PluginManager.ActionBase import ActionBase  # type: ignore
import os
import traceback
import time
from loguru import logger as log  # type: ignore
from PIL import Image  # type: ignore

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, Adw, GLib

import globals as gl

from .websocket_client import PipeWeaverWebSocketClient, MeterWebSocketClient
from .image_renderer import ImageRenderer
from .svg_converter import svg_to_pil, is_svg_file

class PipeWeaverAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.client = PipeWeaverWebSocketClient()
        self.client.start()
        self.devices = []
        self.selected_device_id = None
        self.selected_device_name = None
        self.selected_device_type = None
        self.selected_mixes = set()
        self.mute_configurations = []
        self.volume = 50
        self.volume_step = 5
        self._is_initializing = True
        self.icon_path_from_picker = None
        self._icon_cache = {}
        self._current_meter_a = 0
        self._current_meter_b = 0
        self._current_meter_target = 0
        self._meter_client = None
        
        self._load_settings()
        
        self._is_initializing = False
        
        self.client.patch_callback = self._on_patch_update
        
        self._start_meter_client()
        
        GLib.idle_add(self.update_image)
    
    def _get_status_data(self):
        """Fetch and parse PipeWeaver status data"""
        return self.client._get_status()
    
    def _get_device_by_id(self, device_id, device_type=None):
        """Get device data from status by ID"""
        status_data = self._get_status_data()
        if not status_data:
            return None
        
        devices = status_data.get("audio", {}).get("profile", {}).get("devices", {})
        
        search_sections = []
        if device_type == "source":
            search_sections.append(("sources", "virtual_devices"))
        elif device_type == "target":
            search_sections.append(("targets", "virtual_devices"))
        else:
            search_sections = [("sources", "virtual_devices"), ("targets", "virtual_devices")]
        
        for section, subsection in search_sections:
            for device in devices.get(section, {}).get(subsection, []):
                if device["description"]["id"] == device_id:
                    return device
        
        return None
    
    def _get_all_targets(self):
        """Get all available targets (virtual + physical)"""
        status_data = self._get_status_data()
        if not status_data:
            return []
        
        devices = status_data.get("audio", {}).get("profile", {}).get("devices", {})
        virtual_targets = devices.get("targets", {}).get("virtual_devices", [])
        physical_targets = devices.get("targets", {}).get("physical_devices", [])
        return virtual_targets + physical_targets
    
    def _get_source_mix_states(self, selected_mixes):
        """Get mute states for selected mixes"""
        device_data = self._get_device_by_id(self.selected_device_id, "source")
        if not device_data:
            return {}, False
        
        mute_states = device_data.get("mute_states", {}).get("mute_state", [])
        mix_states = {}
        overall_muted = False
        
        for mix in selected_mixes:
            mix_states[mix] = f"Target{mix}" in mute_states
            if mix_states[mix]:
                overall_muted = True
        
        return mix_states, overall_muted
    
    def _toggle_mute(self):
        """Toggle mute state for selected device and mixes"""
        if not self.selected_device_id:
            return
        
        try:
            if self.selected_device_type == "source":
                selected_mixes = list(self.selected_mixes)
                mix_states, overall_muted = self._get_source_mix_states(selected_mixes)
                
                if overall_muted:
                    for mix in selected_mixes:
                        if mix_states.get(mix, False):
                            self.client.unmute_device(self.selected_device_id, mix)
                else:
                    for mix in selected_mixes:
                        if not mix_states.get(mix, False):
                            self.client.mute_device(self.selected_device_id, mix)
            else:
                device_data = self._get_device_by_id(self.selected_device_id, "target")
                if device_data:
                    is_muted = device_data.get("mute_state") == "Muted"
                    if is_muted:
                        self.client.unmute_device(self.selected_device_id)
                    else:
                        self.client.mute_device(self.selected_device_id)
            
        except Exception as e:
            log.error(f"Error toggling mute: {e}")
    
    def _is_device_muted(self):
        """Check if selected device is muted"""
        if self.selected_device_type == "source":
            selected_mixes = list(self.selected_mixes)
            _, overall_muted = self._get_source_mix_states(selected_mixes)
            return overall_muted
        else:
            device_data = self._get_device_by_id(self.selected_device_id, "target")
            if device_data:
                return device_data.get("mute_state") == "Muted"
        return False
    
    def _load_settings(self):
        """Load all settings from StreamController"""
        settings = self.get_settings()
        
        self._ensure_connection_and_load_devices()
        
        self._load_device_settings(settings)
        
        self.volume_step = settings.get('volume_step', 5)
        self.icon_path_from_picker = settings.get("icon_path_from_picker", None)
    
    def _ensure_connection_and_load_devices(self):
        """Wait for connection and load devices"""
        if not self.devices:
            max_wait = 5.0
            wait_time = 0.0
            while not self.client.connected and wait_time < max_wait:
                time.sleep(0.1)
                wait_time += 0.1
            
            self.devices = self.client.get_devices() if self.client.connected else []
    
    def _load_device_settings(self, settings):
        """Load and validate device settings"""
        saved_device_name = settings.get('device_name')
        saved_device_id = settings.get('device_id')
        
        if saved_device_name and self.devices:
            device = next((d for d in self.devices if d['name'] == saved_device_name), None)
            if device:
                self._set_selected_device(device, settings, saved_device_id)
                return
        
        if self.devices:
            self._set_selected_device(self.devices[0], settings)
    
    def _set_selected_device(self, device, settings, saved_device_id=None):
        """Set the selected device and initialize ALL state from API"""
        self.selected_device_id = device['id']
        self.selected_device_name = device['name']
        self.selected_device_type = device['type']
        self._reset_meter_values()
        
        # Initialize ALL state from API
        status_data = self._get_status_data()
        if status_data and self.selected_device_type == "source":
            device_data = self._get_device_by_id(self.selected_device_id, "source")
            if device_data:
                # Initialize mute configurations from API (2 mute configurations)
                mute_targets = device_data.get("mute_states", {}).get("mute_targets", {})
                self.mute_configurations = [
                    mute_targets.get("TargetA", []),
                    mute_targets.get("TargetB", [])
                ]
                
                # Default to Mix A for volume control
                self.selected_mixes = set(["A"])
        
        if saved_device_id != device['id']:
            settings['device_id'] = device['id']
            if not self._is_initializing:
                self.set_settings(settings)
    
    def _reset_meter_values(self):
        """Reset meter values"""
        self._current_meter_a = 0
        self._current_meter_b = 0
        self._current_meter_target = 0
    
    def get_config_rows(self):
        """Get configuration UI rows"""
        self._ensure_connection_and_load_devices()
        
        if self.client.connected and (not self.devices or len(self.devices) == 0):
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries and (not self.devices or len(self.devices) == 0):
                time.sleep(0.2)
                self.devices = self.client.get_devices()
                retry_count += 1
        
        if not self.devices or len(self.devices) == 0:
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
        
        for device in self.devices:
            self.device_model.append(f"{device['name']} ({device['type']})")
        
        if self.selected_device_name:
            for i, device in enumerate(self.devices):
                if device['name'] == self.selected_device_name:
                    self.device_selector.set_selected(i)
                    break
        
        self.device_selector.connect("notify::selected-item", self.on_device_changed)
        
                
        icon_expander = Adw.ExpanderRow()
        icon_expander.set_title(self.plugin_base.lm.get("ui.custom_icon.title"))
        icon_expander.set_subtitle(self.plugin_base.lm.get("ui.custom_icon.subtitle"))
        
        icon_picker_row = Adw.ActionRow()
        icon_picker_row.set_title("Browse Icon Library")
        
        if hasattr(self, 'icon_path_from_picker') and self.icon_path_from_picker:
            import os
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
        
        self.volume_step_row = Adw.SpinRow.new_with_range(1, 20, 1)
        self.volume_step_row.set_title(self.plugin_base.lm.get("ui.volume_step.title"))
        self.volume_step_row.set_subtitle(self.plugin_base.lm.get("ui.volume_step.subtitle"))
        
        settings = self.get_settings()
        volume_step = settings.get("volume_step", 5)
        self.volume_step_row.set_value(volume_step)
        
        self.volume_step_row.connect("notify::value", self.on_volume_step_changed)

        refresh_btn = Gtk.Button.new_with_label(self.plugin_base.lm.get("ui.refresh_devices.button"))
        refresh_btn.add_css_class("suggested-action")
        refresh_btn.set_margin_top(24)
        refresh_btn.set_margin_bottom(12)
        refresh_btn.connect("clicked", self.on_refresh_clicked)
        
        config_rows = [self.device_selector]

        config_rows.append(icon_expander)
        config_rows.append(self.volume_step_row)
        config_rows.append(refresh_btn)
        
        return config_rows
    
    def on_device_changed(self, combo_row, *args):
        """Handle device selection change"""
        selected_index = combo_row.get_selected()
        if selected_index is not None and selected_index < len(self.devices):
            device = self.devices[selected_index]
            settings = self.get_settings()
            settings["device_id"] = device['id']
            settings["device_name"] = device['name']
            self.set_settings(settings)
            
            self.selected_device_id = device['id']
            self.selected_device_name = device['name']
            self.selected_device_type = device['type']
            
            status_data = self._get_status_data()
            if status_data and self.selected_device_type == "source":
                device_data = self._get_device_by_id(self.selected_device_id, "source")
                if device_data:
                    mute_targets = device_data.get("mute_states", {}).get("mute_targets", {})
                    self.mute_configurations = [
                        mute_targets.get("TargetA", []),
                        mute_targets.get("TargetB", [])
                    ]
                    
                    self.selected_mixes = set(["A"])
            
            if hasattr(self, 'set_top_label'):
                device_name = self.selected_device_name[:25] if self.selected_device_name else "Unknown"
                self.set_top_label(device_name, font_size=14)
            
            self.update_image()
    
    
    def on_volume_step_changed(self, spin_row, *args):
        """Handle volume step change"""
        volume_step = int(spin_row.get_value())
        settings = self.get_settings()
        settings["volume_step"] = volume_step
        self.set_settings(settings)
        self.volume_step = volume_step

    
    def on_remove_icon_clicked(self, button, *args):
        """Handle remove icon button click"""
        settings = self.get_settings()
        settings["icon_path_from_picker"] = None
        self.icon_path_from_picker = None
        
        self._icon_cache.clear()
        self.set_settings(settings)
        self._update_icon_display()
        
        GLib.idle_add(self.update_image)
        
    def on_icon_picker_clicked(self, button, *args):
        """Handle icon picker button click - opens StreamController's asset manager"""
        try:
            if gl.app is None:
                log.warning("App not available")
                return
            
            gl.app.let_user_select_asset(
                default_path="",
                callback_func=self.on_icon_selected_from_picker,
                callback_args=(),
                callback_kwargs={}
            )
            
        except Exception as e:
            log.error(f"Error opening icon picker: {e}")
            log.error(traceback.format_exc())
    
    def on_icon_selected_from_picker(self, icon_path, *args, **kwargs):
        """Handle icon selection from picker"""
        self.icon_path_from_picker = icon_path
        self.set_settings({"icon_path_from_picker": icon_path})
        self.update_image()
    
    def _update_icon_display(self):
        """Update the icon display based on current settings"""
        pass
    
    def _get_icon(self):
        """Get the icon to display - returns PIL Image or None"""
        if hasattr(self, 'icon_path_from_picker') and self.icon_path_from_picker and os.path.exists(self.icon_path_from_picker):
            try:
                cache_key = self.icon_path_from_picker
                if cache_key in self._icon_cache:
                    return self._icon_cache[cache_key]
                
                if is_svg_file(self.icon_path_from_picker):
                    image = svg_to_pil(self.icon_path_from_picker, (400, 400))
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
        return None
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        try:
            self.devices = self.client.get_devices()
            
            current_selection = self.device_selector.get_selected()
            current_device_name = None
            if current_selection is not None and current_selection < len(self.devices):
                current_device_name = self.devices[current_selection]['name']
            
            saved_device_name = self.selected_device_name
            
            settings = self.get_settings()
            saved_device_id = settings.get('device_id')
            
            device_name_to_restore = current_device_name or saved_device_name

            self.device_selector.handler_block_by_func(self.on_device_changed)
            
            while self.device_model.get_n_items() > 0:
                self.device_model.remove(0)
            for device in self.devices:
                self.device_model.append(f"{device['name']} ({device['type']})")
            
            self.device_selector.queue_draw()
            
            if device_name_to_restore:
                for i, device in enumerate(self.devices):
                    if device['name'] == device_name_to_restore:
                        self.device_selector.set_selected(i)
                        self.selected_device_id = device['id']
                        self.selected_device_name = device['name']
                        self.selected_device_type = device['type']
                        
                        if saved_device_id != device['id']:
                            settings['device_id'] = device['id']
                            self.set_settings(settings)
                        
                        break
            else:
                if self.devices:
                    self.device_selector.set_selected(0)
                    self.selected_device_id = self.devices[0]['id']
                    self.selected_device_name = self.devices[0]['name']
                    self.selected_device_type = self.devices[0]['type']
                    
                    settings['device_id'] = self.devices[0]['id']
                    settings['device_name'] = self.devices[0]['name']
                    self.set_settings(settings)
            
            self.device_selector.handler_unblock_by_func(self.on_device_changed)
            
            self.device_selector.queue_draw()
            
        except Exception as e:
            log.error(f"PipeWeaverAction: Error refreshing devices: {e}")
    
    def on_settings_changed(self, settings):
        """Handle settings changes"""
        if 'device_name' in settings:
            saved_device_name = settings['device_name']
            for device in self.devices:
                if device['name'] == saved_device_name:
                    self.selected_device_id = device['id']
                    self.selected_device_name = device['name']
                    self.selected_device_type = device['type']
                    self._current_meter_a = 0
                    self._current_meter_b = 0
                    self._current_meter_target = 0
                    break
            self.update_image()
        elif 'device_id' in settings:
            self.selected_device_id = settings['device_id']
            self._current_meter_a = 0
            self._current_meter_b = 0
            self._current_meter_target = 0
            for device in self.devices:
                if device['id'] == self.selected_device_id:
                    self.selected_device_name = device['name']
                    self.selected_device_type = device['type']
                    break
            self.update_image()
    
    def _verify_and_update_device_id(self):
        """Verify device ID is still valid, update if PipeWeaver restarted"""
        if not self.selected_device_name:
            return False
        
        try:
            self.devices = self.client.get_devices()
        except Exception as e:
            log.error(f"Failed to refresh device list: {e}")
            return False
        
        for device in self.devices:
            if device['name'] == self.selected_device_name:
                if device['id'] != self.selected_device_id:
                    old_id = self.selected_device_id
                    self.selected_device_id = device['id']
                    
                    settings = self.get_settings()
                    settings['device_id'] = device['id']
                    self.set_settings(settings)
                
                return True
        
        return False
    
    def _toggle_volume_linking(self):
        """Toggle volume linking for source devices"""
        if not self.selected_device_id:
            log.error("Cannot toggle volume linking: selected_device_id is None")
            return
        
        if self.selected_device_type != "source":
            log.error(f"Cannot toggle volume linking: device type is {self.selected_device_type}, not 'source'")
            return
        
        if not self.client:
            log.error("Cannot toggle volume linking: CLI client not available")
            return
        
        if not self._verify_and_update_device_id():
            log.warning(f"Device ID verification failed for {self.selected_device_name}, continuing anyway")
        
        try:
            is_linked = self.client.is_volume_linked(self.selected_device_id)
            new_linked_state = not is_linked
            success = self.client.set_volume_linked(self.selected_device_id, new_linked_state)
            
            if success:
                self.devices = self.client.get_devices()
                time.sleep(0.1)
                updated_is_linked = self.client.is_volume_linked(self.selected_device_id)
                self.update_image()
            else:
                log.error(f"Failed to toggle volume linking for {self.selected_device_name}")
        
        except Exception as e:
            log.error(f"Error toggling volume linking: {e}")
        
        
    def _set_volume(self, volume):
        """Set volume for selected device (send change to API, let patches handle UI)"""
        if not self.selected_device_id or self._is_device_muted():
            return
        
        self._verify_and_update_device_id()
        
        try:
            if self.selected_device_type == "source":
                is_linked = self.client.is_volume_linked(self.selected_device_id)
                
                if is_linked and "A" in self.selected_mixes and "B" in self.selected_mixes:
                    self.client.set_volume(self.selected_device_id, volume, "A")
                else:
                    for mix in self.selected_mixes:
                        current_volume = self._get_current_volume_for_mix(mix) or 0
                        
                        if current_volume >= 100 and volume >= current_volume:
                            continue
                        if current_volume <= 0 and volume <= current_volume:
                            continue
                            
                        self.client.set_volume(self.selected_device_id, volume, mix)
            else:
                self.client.set_volume(self.selected_device_id, volume)
            
        except Exception as e:
            log.error(f"Error setting volume: {e}")
    
    def _set_volume_relative(self, delta):
        """Set volume relative to current for selected device (send change to API, let patches handle UI)"""
        if not self.selected_device_id or self._is_device_muted():
            return
        
        self._verify_and_update_device_id()
        
        try:
            if self.selected_device_type == "source":
                is_linked = self.client.is_volume_linked(self.selected_device_id)
                
                if is_linked and "A" in self.selected_mixes and "B" in self.selected_mixes:
                    current_volume = self._get_current_volume_for_mix("A") or 0
                    
                    if current_volume >= 100 and delta > 0:
                        return
                    
                    self.client.set_volume_relative(self.selected_device_id, delta, "A", current_volume)
                else:
                    for mix in self.selected_mixes:
                        current_volume = self._get_current_volume_for_mix(mix) or 0
                        
                        if current_volume >= 100 and delta > 0:
                            continue
                        if current_volume <= 0 and delta < 0:
                            continue
                            
                        self.client.set_volume_relative(self.selected_device_id, delta, mix, current_volume)
            else:
                current_volume = self._get_current_volume_for_mix(None) or 0
                self.client.set_volume_relative(self.selected_device_id, delta, None, current_volume)
            
        except Exception as e:
            log.error(f"Error setting volume relative: {e}")
    
    def _get_current_volume_for_mix(self, mix):
        """Get current volume for a specific mix, forcing a fresh status read"""
        if not self.selected_device_id:
            return None
        
        try:
            status_data = self._get_status_data()
            if not status_data:
                return None
            
            if self.selected_device_type == "source":
                devices = status_data.get("audio", {}).get("profile", {}).get("devices", {})
                for device in devices.get("sources", {}).get("virtual_devices", []):
                    if device["description"]["id"] == self.selected_device_id:
                        volumes_dict = device.get("volumes", {})
                        if isinstance(volumes_dict, dict):
                            volume_dict = volumes_dict.get("volume", {})
                            if isinstance(volume_dict, dict):
                                vol_raw = volume_dict.get(mix, 0)
                                volume = int((vol_raw / 255.0) * 100) if vol_raw > 100 else vol_raw
                                step_size = getattr(self, 'volume_step', 5)
                                volume = round(volume / step_size) * step_size
                                if volume >= 99:
                                    volume = 100
                                elif volume <= 1:
                                    volume = 0
                                return volume
            else:
                devices = status_data.get("audio", {}).get("profile", {}).get("devices", {})
                for device in devices.get("targets", {}).get("virtual_devices", []):
                    if device["description"]["id"] == self.selected_device_id:
                        vol_raw = device.get("volume", 0)
                        volume = int((vol_raw / 255.0) * 100) if vol_raw > 100 else vol_raw
                        # Round to nearest step boundary for accurate visual representation
                        step_size = getattr(self, 'volume_step', 5)
                        volume = round(volume / step_size) * step_size
                        # Clamp to ensure we reach 0 and 100 properly
                        if volume >= 99:
                            volume = 100
                        elif volume <= 1:
                            volume = 0
                        return volume
        except Exception as e:
            log.error(f"Error getting current volume for mix {mix}: {e}")
        
        return None
    
    def _sync_pipeweaver_state(self):
        """Sync PipeWeaver state to match plugin settings"""
        if not self.selected_device_id or self.selected_device_type != "source":
            return
        
        try:
            device_data = self._get_device_by_id(self.selected_device_id, "source")
            if not device_data:
                return
            
            current_mute_states = device_data.get("mute_states", {}).get("mute_state", [])
            
            if "A" in self.selected_mixes and "B" in self.selected_mixes:
                mix_a_muted = "TargetA" in current_mute_states
                mix_b_muted = "TargetB" in current_mute_states
                
                if mix_a_muted != mix_b_muted:
                    if mix_a_muted:
                        self.client.mute_device(self.selected_device_id, "B")
                    else:
                        self.client.unmute_device(self.selected_device_id, "B")
            
        except Exception as e:
            log.error(f"Error syncing PipeWeaver state: {e}")
    
    def on_enable(self):
        """Called when action is enabled"""
        for _ in range(50):
            if self.client.connected:
                break
            time.sleep(0.1)
        
        if self.client.connected:
            self.devices = self.client.get_devices()
        else:
            log.warning("WebSocket not connected, devices may not be available")
            self.devices = []
        
        self._load_settings()
        self._sync_pipeweaver_state()
        self.update_image()
        
    
    def on_ready(self):
        """Called when action is ready"""
        self.on_enable()
        
        if hasattr(self, 'set_top_label'):
            device_name = self.selected_device_name[:25] if self.selected_device_name else "Unknown"
            self.set_top_label(device_name, font_size=14)
        
        self._start_meter_client()
    
    def on_disable(self):
        """Called when action is disabled"""
        if self.client:
            self.client.patch_callback = None
        
        self._stop_meter_client()
    
    def _meter_callback(self, node_id, percent):
        """Callback for meter updates from WebSocket"""
        device_id = node_id
        if device_id != self.selected_device_id:
            return

        device_data_source = self._get_device_by_id(device_id, "source")
        device_data_target = self._get_device_by_id(device_id, "target")

        meter_changed = False
        
        if device_data_source:
            if self._current_meter_a != percent or self._current_meter_b != percent:
                self._current_meter_a = percent
                self._current_meter_b = percent
                meter_changed = True
        elif device_data_target:
            if self._current_meter_target != percent:
                self._current_meter_target = percent
                meter_changed = True
        else:
            if self._current_meter_a != percent or self._current_meter_b != percent or self._current_meter_target != percent:
                self._current_meter_a = percent
                self._current_meter_b = percent
                self._current_meter_target = percent
                meter_changed = True

        if meter_changed:
            self.update_image()

    
    def _start_meter_client(self):
        """Start WebSocket client for meter data"""
        try:
            if self._meter_client is None:
                self._meter_client = MeterWebSocketClient(self._meter_callback)
                self._meter_client.start()
        except Exception as e:
            log.error(f"Error starting meter client: {e}")
    
    def _stop_meter_client(self):
        """Stop WebSocket client for meter data"""
        try:
            if self._meter_client:
                self._meter_client.stop()
                self._meter_client = None
        except Exception as e:
            log.error(f"Error stopping meter client: {e}")
    
    def _on_patch_update(self, status):
        """Callback when status is updated via patches - update UI from API state"""
        if not self.selected_device_id:
            return
        
        try:
            device_data = self._get_device_by_id(self.selected_device_id, self.selected_device_type)
            if not device_data:
                return
            
            if self.selected_device_type == "source":
                volumes_dict = device_data.get("volumes", {})
                volume_dict = volumes_dict.get("volume", {}) if isinstance(volumes_dict, dict) else {}
                if isinstance(volume_dict, dict):
                    volume_a_raw = volume_dict.get("A", 0)
                    volume_b_raw = volume_dict.get("B", 0)
                    volume_a = int((volume_a_raw / 255.0) * 100) if volume_a_raw > 100 else volume_a_raw
                    volume_b = int((volume_b_raw / 255.0) * 100) if volume_b_raw > 100 else volume_b_raw
                    
                    if "B" in self.selected_mixes:
                        self.volume = volume_b
                    elif "A" in self.selected_mixes:
                        self.volume = volume_a
                else:
                    self.volume = 0
            else:
                volume_raw = device_data.get("volume", 0)
                volume = int((volume_raw / 255.0) * 100) if volume_raw > 100 else volume_raw
                self.volume = volume
            
            self.update_image()
        
        except Exception as e:
            log.error(f"Error handling patch update: {e}")
    
    def update_image(self):
        """Update button image - shows mute state or volume bars"""
        if hasattr(self, 'set_top_label'):
            device_name = self.selected_device_name[:25] if self.selected_device_name else "Unknown"
            self.set_top_label(device_name, font_size=14)
        
        if not hasattr(self, '_image_renderer'):
            self._image_renderer = ImageRenderer(self)
        self._image_renderer.render_image()