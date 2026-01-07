"""Unified slider button action for PipeWeaver - shows top/bottom portion based on step sign"""
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from src.backend.DeckManagement.InputIdentifier import Input  # type: ignore

from .action_base import (
    COLOR_METER,
    DEFAULT_VOLUME_STEP,
    MAX_VOLUME_STEP,
    PipeWeaverAction,
)
from .pipeweaver_helpers import DEVICE_TYPE_SOURCE
from .service_monitor import is_service_available


class PipeWeaverSliderAction(PipeWeaverAction):
    @property
    def is_top_slider(self) -> bool:
        return self.volume_step > 0
    
    def _get_renderer(self):
        from .slider_button_renderer import SliderButtonRenderer
        return SliderButtonRenderer(self)
    
    def event_callback(self, event: Any, data: Any) -> None:
        if event == Input.Key.Events.SHORT_UP or str(event) == "Key Short Up" or "Short Up" in str(event):
            if not self.selected_device_id:
                return
            self._set_volume_relative(self.volume_step)
    
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
        
        self._populate_device_list(DEVICE_TYPE_SOURCE)
        
        refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=self.plugin_base.lm.get("ui.refresh_devices.button")
        )
        refresh_button.connect("clicked", self.on_refresh_clicked)
        self.device_selector.add_suffix(refresh_button)
        
        self.volume_step_row = Adw.SpinRow.new_with_range(-MAX_VOLUME_STEP, MAX_VOLUME_STEP, 1)
        self.volume_step_row.set_title(self.plugin_base.lm.get("ui.volume_step.title"))
        self.volume_step_row.set_subtitle("Positive step = top slider, Negative step = bottom slider")
        self.volume_step_row.set_value(self.get_settings().get("volume_step", DEFAULT_VOLUME_STEP))
        self.volume_step_row.connect("notify::value", self.on_volume_step_changed)

        # Horizontal/Vertical orientation option
        orientation_row = Adw.ActionRow()
        orientation_row.set_title("Orientation")
        orientation_row.set_subtitle("Choose slider orientation")
        
        self.orientation_combo = Gtk.ComboBoxText()
        self.orientation_combo.append("vertical", "Vertical")
        self.orientation_combo.append("horizontal", "Horizontal")
        current_orientation = self.get_settings().get("orientation", "vertical")
        self.orientation_combo.set_active_id(current_orientation)
        self.orientation_combo.connect("changed", self.on_orientation_changed)
        orientation_row.add_suffix(self.orientation_combo)

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
            self.volume_step_row,
            orientation_row,
            meters_enabled_row,
            meter_color_row,
            volume_bar_color_row,
        ]
    
    def on_refresh_clicked(self, button: Gtk.Button) -> None:
        self._ensure_connection_and_load_devices()
        self._populate_device_list(DEVICE_TYPE_SOURCE)
    
    def on_volume_step_changed(self, spin_row: Adw.SpinRow, *args: Any) -> None:
        volume_step = int(spin_row.get_value())
        settings = self.get_settings()
        settings['volume_step'] = volume_step
        self.set_settings(settings)
        self.volume_step = volume_step
    
    def on_orientation_changed(self, combo: Gtk.ComboBoxText, *args: Any) -> None:
        orientation = combo.get_active_id()
        settings = self.get_settings()
        settings["orientation"] = orientation
        self.set_settings(settings)
        
        self.orientation = orientation
        self._last_draw_state = None
        if hasattr(self, '_image_cache'):
            self._image_cache.clear()
        self.update_image()
