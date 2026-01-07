"""Volume up button action for PipeWeaver"""
import os
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, GdkPixbuf, Gtk

from src.backend.DeckManagement.InputIdentifier import Input  # type: ignore

from .action_base import PipeWeaverAction
from .service_monitor import is_service_available


class PipeWeaverVolumeUpButtonAction(PipeWeaverAction):
    def _get_renderer(self):
        from .volume_button_renderer import VolumeButtonRenderer
        return VolumeButtonRenderer(self, is_plus=True)
    
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
        
        return [
            self.device_selector,
            icon_row,
        ]
