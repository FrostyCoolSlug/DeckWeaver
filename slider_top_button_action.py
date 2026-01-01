"""Slider top button action for PipeWeaver - shows upper portion of continuous slider"""
import os
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gtk

from src.backend.DeckManagement.InputIdentifier import Input  # type: ignore

from .action_base import (
    COLOR_METER,
    DEFAULT_VOLUME_STEP,
    DEVICE_TYPE_SOURCE,
    MAX_VOLUME_STEP,
    MIN_VOLUME_STEP,
    PipeWeaverAction,
)
from .service_monitor import is_service_available
from loguru import logger as log  # type: ignore


class PipeWeaverSliderTopButtonAction(PipeWeaverAction):
    def event_callback(self, event: Any, data: Any) -> None:
        # Handle button press events - SHORT_UP is the event for button press/release
        if event == Input.Key.Events.SHORT_UP or str(event) == "Key Short Up" or "Short Up" in str(event):
            if not self.selected_device_id:
                log.warning("Volume up button pressed but no device selected")
                return
            self._set_volume_relative(self.volume_step)
    
    def get_config_rows(self):
        """Config - device (source only), volume step"""
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
        self._populate_device_list_source_only()
        
        refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=self.plugin_base.lm.get("ui.refresh_devices.button")
        )
        refresh_button.connect("clicked", self.on_refresh_clicked)
        self.device_selector.add_suffix(refresh_button)
        
        self.volume_step_row = Adw.SpinRow.new_with_range(MIN_VOLUME_STEP, MAX_VOLUME_STEP, 1)
        self.volume_step_row.set_title(self.plugin_base.lm.get("ui.volume_step.title"))
        self.volume_step_row.set_subtitle(self.plugin_base.lm.get("ui.volume_step.subtitle"))
        
        settings = self.get_settings()
        volume_step = settings.get("volume_step", DEFAULT_VOLUME_STEP)
        self.volume_step_row.set_value(volume_step)
        self.volume_step_row.connect("notify::value", self.on_volume_step_changed)

        meters_enabled_row = Adw.ActionRow()
        meters_enabled_row.set_title("Meters Enabled")
        meters_enabled_row.set_subtitle("Show audio level meters")
        
        self.meters_enabled_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meters_enabled_switch.set_active(getattr(self, "_meters_enabled", True))
        self.meters_enabled_switch.connect("notify::active", self.on_meters_enabled_changed)
        meters_enabled_row.add_suffix(self.meters_enabled_switch)

        meter_color_row = Adw.ActionRow()
        meter_color_row.set_title("Meter Color")
        meter_color_row.set_subtitle("Invert volume color or use custom color")
        
        meter_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.meter_invert_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meter_invert_switch.set_active(getattr(self, "_meter_invert_color", True))
        self.meter_invert_switch.connect("notify::active", self.on_meter_invert_changed)
        self.meter_invert_switch.set_sensitive(self._meters_enabled)
        meter_color_box.append(self.meter_invert_switch)
        
        self.meter_color_button = Gtk.ColorButton(valign=Gtk.Align.CENTER)
        meter_color = getattr(self, "_meter_color", None) or COLOR_METER
        rgba = Gdk.RGBA()
        rgba.red = meter_color[0] / 255.0
        rgba.green = meter_color[1] / 255.0
        rgba.blue = meter_color[2] / 255.0
        rgba.alpha = meter_color[3] / 255.0
        self.meter_color_button.set_rgba(rgba)
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
        
        volume_bar_color = getattr(self, "_volume_bar_color", None)
        if not volume_bar_color:
            device_color = getattr(self, "_device_color", {}) or {}
            if device_color and 'red' in device_color and 'green' in device_color and 'blue' in device_color:
                rgba = Gdk.RGBA()
                rgba.red = device_color['red'] / 255.0
                rgba.green = device_color['green'] / 255.0
                rgba.blue = device_color['blue'] / 255.0
                rgba.alpha = 1.0
                self.volume_bar_color_button.set_rgba(rgba)
            else:
                rgba = Gdk.RGBA()
                rgba.red = 1.0
                rgba.green = 1.0
                rgba.blue = 1.0
                rgba.alpha = 1.0
                self.volume_bar_color_button.set_rgba(rgba)
        else:
            rgba = Gdk.RGBA()
            rgba.red = volume_bar_color[0] / 255.0
            rgba.green = volume_bar_color[1] / 255.0
            rgba.blue = volume_bar_color[2] / 255.0
            rgba.alpha = volume_bar_color[3] / 255.0
            self.volume_bar_color_button.set_rgba(rgba)
        
        self.volume_bar_color_button.connect("color-set", self.on_volume_bar_color_changed)
        volume_bar_color_box.append(self.volume_bar_color_button)
        
        clear_volume_bar_color_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        clear_volume_bar_color_button.set_tooltip_text("Clear override")
        clear_volume_bar_color_button.connect("clicked", self.on_clear_volume_bar_color_clicked)
        volume_bar_color_box.append(clear_volume_bar_color_button)
        
        volume_bar_color_row.add_suffix(volume_bar_color_box)
        
        return [
            self.device_selector,
            self.volume_step_row,
            meters_enabled_row,
            meter_color_row,
            volume_bar_color_row,
        ]
    
    def _populate_device_list_source_only(self) -> None:
        """Populate device list with source devices only"""
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
        
        all_devices = self._load_devices()
        # Filter to source devices only
        self.devices = [d for d in all_devices if d['type'] == DEVICE_TYPE_SOURCE]
        
        # Ensure device type is set to source
        self.selected_device_type = DEVICE_TYPE_SOURCE
        # Update settings to ensure device_type is saved
        if self.selected_device_id:
            settings = self.get_settings()
            settings["device_type"] = DEVICE_TYPE_SOURCE
            self.set_settings(settings)
        
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
                settings["device_type"] = DEVICE_TYPE_SOURCE  # Force source type
                settings.pop("device_name", None)
                if not self._is_initializing:
                    self.set_settings(settings)
                    self._update_device_selection(device)
        
        if handler_blocked:
            self.device_selector.handler_unblock_by_func(self.on_device_changed)
    
    def on_device_changed(self, combo_row: Adw.ComboRow, *args: Any) -> None:
        """Handle device selection change - ensure source type"""
        selected_index = combo_row.get_selected()
        if selected_index is not None and selected_index < len(self.devices):
            device = self.devices[selected_index]
            settings = self.get_settings()
            settings["device_id"] = device['id']
            settings["device_type"] = DEVICE_TYPE_SOURCE  # Force source type
            settings.pop("device_name", None)
            self.set_settings(settings)
            self._update_device_selection(device)
    
    def on_refresh_clicked(self, button: Gtk.Button) -> None:
        """Refresh device list"""
        self._ensure_connection_and_load_devices()
        self._populate_device_list_source_only()
    
    def on_volume_step_changed(self, spin_row: Adw.SpinRow, *args: Any) -> None:
        """Handle volume step change"""
        volume_step = int(spin_row.get_value())
        settings = self.get_settings()
        settings['volume_step'] = volume_step
        self.set_settings(settings)
        self.volume_step = volume_step
