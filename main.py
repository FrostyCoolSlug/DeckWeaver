"""StreamController plugin entry point - thin wrapper over Rust core"""

from io import BytesIO
import logging
import os
from typing import Any, Optional

from PIL import Image
from loguru import logger as log

from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.DeckManagement.InputIdentifier import Input
import globals as gl

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk

# Configure logging for Rust before importing the module
# This routes Rust's tracing::info!, warn!, error! to Python's logging
logging.getLogger("deckweaver").setLevel(logging.DEBUG)

from .deckweaver import (
    VERSION,
    DeckWeaverCore,
    ActionConfig,
    ActionType,
    Device,
    load_icon_to_png,
)

# Single shared core instance
_core: Optional[DeckWeaverCore] = None
_poll_timeout_id: Optional[int] = None
_action_callbacks: dict[str, tuple[Any, Any]] = {}  # action_id -> (image_callback, label_callback)


def _poll_updates() -> bool:
    """Poll for pending updates from Rust core and process them"""
    global _core, _action_callbacks
    if _core is None:
        return True  # Continue polling
    
    try:
        updates = _core.get_pending_updates()
        for action_id, update_dict in updates.items():
            image_cb, label_cb = _action_callbacks.get(action_id, (None, None))
            
            # Process image update
            if image_cb is not None and "image" in update_dict:
                image_data = update_dict["image"]
                if image_data is not None:
                    image_cb(image_data)
            
            # Process label update
            if label_cb is not None and "label" in update_dict:
                label_data = update_dict["label"]
                if label_data is not None:
                    label_cb(label_data)
    except Exception as e:
        log.error(f"Error polling updates: {e}")
    
    return True  # Continue polling


def _get_core() -> DeckWeaverCore:
    """Get or create the shared core instance"""
    global _core, _poll_timeout_id
    if _core is None:
        _core = DeckWeaverCore()
        _core.start()
        # Start polling timer (~30fps = ~33ms interval, matches render rate)
        if _poll_timeout_id is None:
            _poll_timeout_id = GLib.timeout_add(33, _poll_updates)
    return _core


def _release_core():
    """Stop and release the core"""
    global _core, _poll_timeout_id, _action_callbacks
    if _poll_timeout_id is not None:
        GLib.source_remove(_poll_timeout_id)
        _poll_timeout_id = None
    if _core is not None:
        _core.stop()
        _core = None
    _action_callbacks.clear()


class DeckWeaver(PluginBase):
    """Main plugin class for StreamController"""

    def __init__(self):
        super().__init__()
        self.lm = self.locale_manager
        self._core = _get_core()
        self._load_settings()
        self._register_actions()

    def _load_settings(self):
        settings = self.get_settings()
        language = settings.get("language", "auto")
        if language != "auto":
            self._set_language(language)
        else:
            self.lm.set_to_os_default()

    def _set_language(self, language: str):
        """Set the language for the locale manager"""
        if hasattr(self.lm, "set_language"):
            try:
                self.lm.set_language(language)
                return
            except (AttributeError, TypeError):
                pass
        if hasattr(self.lm, "set_locale"):
            try:
                self.lm.set_locale(language)
                return
            except (AttributeError, TypeError):
                pass
        if hasattr(self.lm, "language"):
            self.lm.language = language
        else:
            self.lm.set_to_os_default()

    def _register_actions(self):
        self.register(
            plugin_name=self.lm.get("plugin.name"),
            github_repo="https://github.com/designgears/DeckWeaver",
            plugin_version=VERSION,
            app_version="1.5.0-beta",
        )

        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=KnobAction,
                action_id_suffix="Knob",
                action_name=self.lm.get("actions.knob.name"),
                action_support={
                    Input.Key: ActionInputSupport.UNSUPPORTED,
                    Input.Dial: ActionInputSupport.SUPPORTED,
                    Input.Touchscreen: ActionInputSupport.SUPPORTED,
                },
            )
        )

        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=ButtonAction,
                action_id_suffix="Button",
                action_name=self.lm.get("actions.button.name", "PipeWeaver Button"),
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.SUPPORTED,
                },
            )
        )

        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=SliderAction,
                action_id_suffix="Slider",
                action_name=self.lm.get("actions.slider.name", "PipeWeaver Slider"),
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.SUPPORTED,
                },
            )
        )

    def get_settings_area(self) -> Adw.PreferencesGroup:
        languages = [
            ("auto", self.lm.get("settings.language.name.auto")),
            ("en_US", self.lm.get("settings.language.name.en_US")),
            ("es_ES", self.lm.get("settings.language.name.es_ES")),
            ("fr_FR", self.lm.get("settings.language.name.fr_FR")),
            ("de_DE", self.lm.get("settings.language.name.de_DE")),
        ]

        self.language_model = Gtk.StringList.new([name for _, name in languages])
        self.language_dropdown = Adw.ComboRow(
            model=self.language_model,
            title=self.lm.get("settings.language.label"),
        )

        current = self.get_settings().get("language", "auto")
        for i, (code, _) in enumerate(languages):
            if code == current:
                self.language_dropdown.set_selected(i)
                break

        self.language_dropdown.connect("notify::selected", self._on_language_changed)

        version_row = Adw.ActionRow(
            title=self.lm.get("settings.version.label"), subtitle=VERSION
        )
        version_row.set_activatable(False)

        group = Adw.PreferencesGroup()
        group.add(self.language_dropdown)
        group.add(version_row)
        return group

    def _on_language_changed(self, combo: Adw.ComboRow, _):
        idx = combo.get_selected()
        languages = ["auto", "en_US", "es_ES", "fr_FR", "de_DE"]
        if idx < len(languages):
            code = languages[idx]
            settings = self.get_settings()
            settings["language"] = code
            self.set_settings(settings)
            self._load_settings()

    def on_disable(self):
        _release_core()


class BaseAction(ActionBase):
    """Base action with shared Rust core functionality"""

    ACTION_TYPE = ActionType.knob()  # Override in subclasses
    MIN_VOLUME_STEP = 1
    MAX_VOLUME_STEP = 20
    DEFAULT_VOLUME_STEP = 5
    COLOR_METER = (0, 0, 0, 255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._core = _get_core()
        self._action_id = f"{id(self)}"  # Unique ID for this action instance
        self._device_id: Optional[str] = None
        self._device_name: Optional[str] = None
        self._volume_step = self.DEFAULT_VOLUME_STEP
        self._meters_enabled = True
        self._meter_invert_color = True
        self._meter_color: Optional[tuple[int, int, int, int]] = None
        self._volume_bar_color: Optional[tuple[int, int, int, int]] = None
        self._icon_path: Optional[str] = None
        self._devices: list = []

    def _get_button_size(self) -> int:
        try:
            inp = self.get_input()
            fmt = inp.deck_controller.deck.key_image_format()
            return fmt["size"][0]
        except Exception:
            return 72

    def _get_dimensions(self) -> tuple[int, int]:
        """Get width, height for this action type"""
        if self.ACTION_TYPE == ActionType.knob():
            return 200, 100
        else:
            size = self._get_button_size()
            return size, size

    def _load_color_tuple(self, settings: dict, key: str, default: Optional[tuple[int, int, int, int]] = None) -> Optional[tuple[int, int, int, int]]:
        """Load color tuple from settings, validating format"""
        color = settings.get(key)
        if color and isinstance(color, (list, tuple)) and len(color) >= 3:
            if len(color) == 3:
                return (int(color[0]), int(color[1]), int(color[2]), 255)
            return (int(color[0]), int(color[1]), int(color[2]), int(color[3]))
        return default

    def _load_icon_as_png(self, path: str) -> Optional[bytes]:
        """Load an icon file and convert to PNG bytes (delegates to Rust)"""
        if not path or not os.path.exists(path):
            return None
        
        try:
            return load_icon_to_png(path)
        except Exception as e:
            log.error(f"Error loading icon from {path}: {e}")
            return None

    def _build_config(self) -> ActionConfig:
        """Build ActionConfig from current settings"""
        w, h = self._get_dimensions()
        config = ActionConfig(self._action_id, self.ACTION_TYPE, w, h)
        config.device_id = self._device_id
        config.volume_step = self._volume_step
        config.meters_enabled = self._meters_enabled
        config.meter_invert = self._meter_invert_color
        
        if self._volume_bar_color:
            config.volume_bar_color = self._volume_bar_color
        if self._meter_color:
            config.meter_color = self._meter_color
        
        # Load custom icon if set (convert to PNG if needed)
        if self._icon_path and os.path.exists(self._icon_path):
            try:
                icon_data = self._load_icon_as_png(self._icon_path)
                if icon_data:
                    config.icon_png = icon_data
            except Exception as e:
                log.error(f"Error loading icon: {e}")

        return config

    def _load_settings(self):
        settings = self.get_settings()
        self._device_id = settings.get("device_id")
        self._volume_step = settings.get("volume_step", self.DEFAULT_VOLUME_STEP)
        self._meters_enabled = settings.get("meters_enabled", True)
        self._meter_invert_color = settings.get("meter_invert_color", True)
        self._meter_color = self._load_color_tuple(settings, "meter_color", self.COLOR_METER)
        self._volume_bar_color = self._load_color_tuple(settings, "volume_bar_color")
        self._icon_path = settings.get("icon_path_from_picker")
        
        # Try to get device name from core if we have device_id
        if self._device_id and not self._device_name:
            self._device_name = self._core.get_action_device_name(self._action_id)
            if not self._device_name:
                # Fallback: look through devices list
                device = self._core.get_device(self._device_id)
                if device:
                    self._device_name = device.name

    def _register_with_core(self):
        """Register this action with the Rust core"""
        global _action_callbacks
        self._load_settings()
        config = self._build_config()
        self._core.register_action(config)
        # Store callbacks locally for polling mechanism
        _action_callbacks[self._action_id] = (self._on_image_update, self._on_label_update)

    def _unregister_from_core(self):
        """Unregister this action from the Rust core"""
        global _action_callbacks
        _action_callbacks.pop(self._action_id, None)
        self._core.unregister_action(self._action_id)

    def _update_config(self):
        """Update the Rust core with new config"""
        config = self._build_config()
        self._core.update_action(self._action_id, config)

    def _on_image_update(self, png_bytes: bytes):
        """Called when a new image is ready for this action (from polling)"""
        def update():
            try:
                image = Image.open(BytesIO(png_bytes))
                self.set_media(image=image, update=True)
                if inp := self.get_input():
                    inp.update()
            except Exception as e:
                log.error(f"Error setting image: {e}")

        GLib.idle_add(update)

    def _on_label_update(self, label: str):
        """Called when the device name changes (from polling)"""
        def update():
            self._set_label(label[:25] if label else "")
        GLib.idle_add(update)

    def _set_label(self, text: str):
        """Set the label below the dial (top label for Stream Deck+)"""
        if hasattr(self, 'set_top_label'):
            self.set_top_label(text, font_size=14)

    def _create_rgba_from_color(self, color: Optional[tuple] = None) -> Gdk.RGBA:
        """Create Gdk.RGBA from tuple color"""
        rgba = Gdk.RGBA()
        if color and len(color) >= 3:
            rgba.red = color[0] / 255.0
            rgba.green = color[1] / 255.0
            rgba.blue = color[2] / 255.0
            rgba.alpha = color[3] / 255.0 if len(color) > 3 else 1.0
        else:
            rgba.red = rgba.green = rgba.blue = rgba.alpha = 1.0
        return rgba

    def get_config_rows(self):
        """Return configuration UI rows - matching original GitHub style"""
        lm = self.plugin_base.lm
        self._load_settings()
        self._devices = self._core.get_devices()

        if not self._core.is_available():
            error_row = Adw.ActionRow()
            error_row.set_title(lm.get("ui.error.not_running.title"))
            error_row.set_subtitle(lm.get("ui.error.not_running.subtitle"))
            error_row.add_css_class("warning")
            return [error_row]

        # Device Expander Row (original style)
        self.device_expander = Adw.ExpanderRow()
        self.device_expander.set_title(lm.get("ui.device.title"))
        self.device_expander.set_subtitle(self._device_name or "No device selected")
        
        self.device_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.device_container.set_margin_start(30)
        self.device_container.set_margin_end(30)
        self.device_container.set_margin_bottom(12)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(300)
        scrolled.set_child(self.device_container)
        
        self.device_expander.add_row(scrolled)
        self.device_expander.connect("notify::expanded", self._on_device_expander_expanded)
        self._populate_device_list()
        
        refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=lm.get("ui.refresh_devices.button")
        )
        refresh_button.connect("clicked", self._on_refresh_clicked)
        self.device_expander.add_suffix(refresh_button)

        # Custom Icon Row
        icon_row = Adw.ActionRow()
        icon_row.set_title(lm.get("ui.custom_icon.title"))
        
        icon_content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, valign=Gtk.Align.CENTER)
        
        self.icon_preview = Gtk.Image()
        self.icon_preview.set_size_request(20, 20)
        self.icon_preview.set_pixel_size(20)
        
        if self._icon_path and os.path.exists(self._icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    self._icon_path, width=20, height=20, preserve_aspect_ratio=True
                )
                self.icon_preview.set_from_pixbuf(pixbuf)
                icon_name = os.path.splitext(os.path.basename(self._icon_path))[0]
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
        icon_picker_button.connect("clicked", self._on_icon_picker_clicked)
        icon_button_box.append(icon_picker_button)
        
        remove_icon_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        remove_icon_button.set_tooltip_text("Remove icon")
        remove_icon_button.connect("clicked", self._on_remove_icon_clicked)
        icon_button_box.append(remove_icon_button)
        
        icon_content_box.append(icon_button_box)
        icon_row.add_suffix(icon_content_box)
        self.icon_row = icon_row

        # Volume Step Row
        # For ButtonAction and SliderAction, use signed range (-20 to 20)
        # For KnobAction, use positive range (5 to 20)
        class_name = self.__class__.__name__
        if class_name == "ButtonAction" or class_name == "SliderAction":
            self.volume_step_row = Adw.SpinRow.new_with_range(-20, 20, 1)
            self.volume_step_row.set_value(self._volume_step)
            if class_name == "ButtonAction":
                self.volume_step_row.set_subtitle("Positive = vol up, Negative = vol down, Zero = mute toggle")
            else:
                self.volume_step_row.set_subtitle("Positive = top slider, Negative = bottom")
        else:
            # KnobAction
            self.volume_step_row = Adw.SpinRow.new_with_range(5, self.MAX_VOLUME_STEP, 1)
            self.volume_step_row.set_value(abs(self._volume_step))
            self.volume_step_row.set_subtitle(lm.get("ui.volume_step.subtitle"))
        self.volume_step_row.set_title(lm.get("ui.volume_step.title"))
        self.volume_step_row.connect("notify::value", self._on_volume_step_changed)

        # Volume Bar Color Row
        volume_bar_color_row = Adw.ActionRow()
        volume_bar_color_row.set_title("Volume Bar Color")
        volume_bar_color_row.set_subtitle("Override the volume bar color")
        
        volume_bar_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.volume_bar_color_button = Gtk.ColorButton(valign=Gtk.Align.CENTER)
        self.volume_bar_color_button.set_rgba(self._create_rgba_from_color(self._volume_bar_color))
        self.volume_bar_color_button.connect("color-set", self._on_volume_bar_color_changed)
        volume_bar_color_box.append(self.volume_bar_color_button)
        
        clear_volume_bar_color_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        clear_volume_bar_color_button.set_tooltip_text("Clear override")
        clear_volume_bar_color_button.connect("clicked", self._on_clear_volume_bar_color_clicked)
        volume_bar_color_box.append(clear_volume_bar_color_button)
        
        volume_bar_color_row.add_suffix(volume_bar_color_box)

        # Meters Enabled Row
        meters_enabled_row = Adw.ActionRow()
        meters_enabled_row.set_title("Meters Enabled")
        meters_enabled_row.set_subtitle("Show audio level meters")
        
        self.meters_enabled_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meters_enabled_switch.set_active(self._meters_enabled)
        self.meters_enabled_switch.connect("notify::active", self._on_meters_enabled_changed)
        meters_enabled_row.add_suffix(self.meters_enabled_switch)

        # Meter Color Row (with invert switch and color button)
        meter_color_row = Adw.ActionRow()
        meter_color_row.set_title("Meter Color")
        meter_color_row.set_subtitle("Invert volume color or use custom color")
        
        meter_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.meter_invert_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.meter_invert_switch.set_active(self._meter_invert_color)
        self.meter_invert_switch.connect("notify::active", self._on_meter_invert_changed)
        meter_color_box.append(self.meter_invert_switch)
        
        self.meter_color_button = Gtk.ColorButton(valign=Gtk.Align.CENTER)
        self.meter_color_button.set_rgba(self._create_rgba_from_color(self._meter_color or self.COLOR_METER))
        self.meter_color_button.connect("color-set", self._on_meter_color_changed)
        meter_color_box.append(self.meter_color_button)
        
        self.clear_meter_color_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.clear_meter_color_button.set_tooltip_text("Reset to default")
        self.clear_meter_color_button.connect("clicked", self._on_clear_meter_color_clicked)
        meter_color_box.append(self.clear_meter_color_button)
        
        meter_color_row.add_suffix(meter_color_box)

        # Set initial sensitivity after UI is created
        self._update_meter_color_sensitivity()
        
        rows = [
            self.device_expander,
            icon_row,
            self.volume_step_row,
        ]
        
        # Only add meter and volume bar settings for KnobAction and SliderAction (not ButtonAction)
        class_name = self.__class__.__name__
        if class_name != "ButtonAction":
            rows.extend([
                volume_bar_color_row,
                meters_enabled_row,
                meter_color_row,
            ])
        
        return rows

    def _populate_device_list(self, retry_count: int = 0):
        """Populate the device list in the expander"""
        # Clear existing children
        child = self.device_container.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.device_container.remove(child)
            child = next_child
        
        self._devices = self._core.get_devices()
        
        if not self._devices:
            # Retry a few times if devices not loaded yet
            if retry_count < 5:
                loading_row = Adw.ActionRow()
                loading_row.set_title("Loading devices...")
                loading_row.set_sensitive(False)
                self.device_container.append(loading_row)
                GLib.timeout_add(500, lambda: self._populate_device_list(retry_count + 1) or False)
                return
            
            no_devices_row = Adw.ActionRow()
            no_devices_row.set_title("No devices found")
            no_devices_row.set_subtitle("Check that PipeWeaver is running")
            no_devices_row.set_sensitive(False)
            self.device_container.append(no_devices_row)
            return
        
        # Update device name if we have a selected device
        if self._device_id and not self._device_name:
            for d in self._devices:
                if d.id == self._device_id:
                    self._device_name = d.name
                    if hasattr(self, 'device_expander'):
                        self.device_expander.set_subtitle(d.name)
                    break
        
        # Get sources and targets directly from Rust
        sources = self._core.get_sources()
        targets = self._core.get_targets()
        
        for section_title, devices in [("Sources", sources), ("Targets", targets)]:
            if not devices:
                continue
            group = Adw.PreferencesGroup()
            group.set_margin_top(12)
            group.set_margin_bottom(6)
            for device in devices:
                row = self._create_device_row(device)
                group.add(row)
                if device.id == self._device_id:
                    row.add_css_class("selected")
            self.device_container.append(group)

    def _create_device_row(self, device) -> Adw.ActionRow:
        """Create a styled device row"""
        row = Adw.ActionRow()
        row.set_title(device.name)
        
        device_type = "Source" if int(device.device_type) == 0 else "Target"
        hw_type = "Physical" if device.is_physical else "Virtual"
        row.set_subtitle(f"{hw_type} {device_type}")
        
        # Add color indicator if available
        if device.color:
            color_dot = Gtk.Label()
            hex_color = f"#{device.color.red:02x}{device.color.green:02x}{device.color.blue:02x}"
            color_dot.set_markup(f"<span foreground='{hex_color}'>●</span>")
            row.add_suffix(color_dot)
        
        row.device_data = device
        row.set_activatable(True)
        row.connect("activated", self._on_device_row_activated)
        
        return row

    def _on_device_row_activated(self, row: Adw.ActionRow):
        """Handle device row activation"""
        device = row.device_data
        if device:
            self._device_id = device.id
            self._device_name = device.name
            
            settings = self.get_settings()
            settings["device_id"] = device.id
            self.set_settings(settings)
            
            if hasattr(self, 'device_expander'):
                self.device_expander.set_subtitle(device.name)
            
            self._update_config()

    def _on_device_expander_expanded(self, expander: Adw.ExpanderRow, _):
        """Reload devices when expander is opened"""
        if expander.get_expanded():
            self._populate_device_list()

    def _on_refresh_clicked(self, button: Gtk.Button):
        """Refresh device list"""
        self._populate_device_list()

    def _on_icon_picker_clicked(self, button: Gtk.Button):
        """Open icon picker"""
        try:
            if gl.app is None:
                return
            gl.app.let_user_select_asset(
                default_path="",
                callback_func=self._on_icon_selected,
                callback_args=(),
                callback_kwargs={}
            )
        except Exception as e:
            log.error(f"Error opening icon picker: {e}")

    def _on_icon_selected(self, icon_path: str, *args, **kwargs):
        """Handle icon selection"""
        if not icon_path:
            return
        
        self._icon_path = icon_path
        settings = self.get_settings()
        settings["icon_path_from_picker"] = icon_path
        self.set_settings(settings)
        
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
        
        self._update_config()

    def _on_remove_icon_clicked(self, button: Gtk.Button):
        """Remove custom icon"""
        self._icon_path = None
        settings = self.get_settings()
        settings.pop("icon_path_from_picker", None)
        self.set_settings(settings)
        
        if hasattr(self, 'icon_preview'):
            self.icon_preview.set_visible(False)
        if hasattr(self, 'icon_row'):
            self.icon_row.set_subtitle("Select an icon from StreamController's icon packs")
        
        self._update_config()

    def _on_volume_step_changed(self, spin_row: Adw.SpinRow, _):
        value = int(spin_row.get_value())
        # For ButtonAction and SliderAction, use signed value directly (preserve negative)
        # For KnobAction, always use positive (absolute value)
        class_name = self.__class__.__name__
        if class_name == "ButtonAction" or class_name == "SliderAction":
            self._volume_step = value
        else:
            # KnobAction: always positive
            self._volume_step = abs(value)
        
        settings = self.get_settings()
        settings["volume_step"] = self._volume_step
        self.set_settings(settings)
        self._update_config()

    def _update_meter_color_sensitivity(self):
        """Update sensitivity of meter color controls"""
        color_enabled = self._meters_enabled and not self._meter_invert_color
        if hasattr(self, 'meter_color_button'):
            self.meter_color_button.set_sensitive(color_enabled)
        if hasattr(self, 'clear_meter_color_button'):
            self.clear_meter_color_button.set_sensitive(color_enabled)
        if hasattr(self, 'meter_invert_switch'):
            self.meter_invert_switch.set_sensitive(self._meters_enabled)

    def _on_meters_enabled_changed(self, switch: Gtk.Switch, _):
        self._meters_enabled = switch.get_active()
        settings = self.get_settings()
        settings["meters_enabled"] = self._meters_enabled
        self.set_settings(settings)
        self._update_meter_color_sensitivity()
        self._update_config()

    def _on_meter_invert_changed(self, switch: Gtk.Switch, _):
        self._meter_invert_color = switch.get_active()
        settings = self.get_settings()
        settings["meter_invert_color"] = self._meter_invert_color
        self.set_settings(settings)
        self._update_meter_color_sensitivity()
        self._update_config()

    def _on_meter_color_changed(self, button: Gtk.ColorButton):
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
        self._update_config()

    def _on_clear_meter_color_clicked(self, button: Gtk.Button):
        self._meter_color = self.COLOR_METER
        settings = self.get_settings()
        settings["meter_color"] = list(self._meter_color)
        self.set_settings(settings)
        if hasattr(self, 'meter_color_button'):
            self.meter_color_button.set_rgba(self._create_rgba_from_color(self.COLOR_METER))
        self._update_config()

    def _on_volume_bar_color_changed(self, button: Gtk.ColorButton):
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
        self._update_config()

    def _on_clear_volume_bar_color_clicked(self, button: Gtk.Button):
        self._volume_bar_color = None
        settings = self.get_settings()
        settings.pop("volume_bar_color", None)
        self.set_settings(settings)
        if hasattr(self, 'volume_bar_color_button'):
            self.volume_bar_color_button.set_rgba(self._create_rgba_from_color(None))
        self._update_config()

    def on_enable(self):
        self._register_with_core()

    def on_ready(self):
        self._register_with_core()

    def on_disable(self):
        self._unregister_from_core()


class KnobAction(BaseAction):
    """Knob/dial action for volume control"""

    ACTION_TYPE = ActionType.knob()

    def event_callback(self, event: Any, data: Any):
        if not self._device_id:
            return
        if event == Input.Dial.Events.TURN_CW:
            self._core.set_volume_relative(self._device_id, self._volume_step)
        elif event == Input.Dial.Events.TURN_CCW:
            self._core.set_volume_relative(self._device_id, -self._volume_step)
        elif event == Input.Dial.Events.SHORT_TOUCH_PRESS or "Short Up" in str(event):
            self._core.toggle_mute(self._device_id)


class ButtonAction(BaseAction):
    """Volume button (positive step = up, negative step = down, zero = mute)"""

    ACTION_TYPE = ActionType.button()

    def get_config_rows(self):
        # Base class already excludes meter settings for ButtonAction
        return super().get_config_rows()

    def _build_config(self) -> ActionConfig:
        config = super()._build_config()
        
        # If no custom icon is set, use the default audio-lines.svg icon
        if not config.icon_png:
            # Get the plugin directory (where main.py is located)
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            default_icon_path = os.path.join(plugin_dir, "assets", "icons", "audio-lines.svg")
            
            if os.path.exists(default_icon_path):
                try:
                    icon_data = self._load_icon_as_png(default_icon_path)
                    if icon_data:
                        config.icon_png = icon_data
                except Exception as e:
                    log.error(f"Error loading default icon: {e}")
        
        return config

    def event_callback(self, event: Any, data: Any):
        if "Short Up" in str(event) and self._device_id:
            if self._volume_step == 0:
                # Mute button
                self._core.toggle_mute(self._device_id)
            else:
                self._core.set_volume_relative(self._device_id, self._volume_step)


class SliderAction(BaseAction):
    """Slider button (top/bottom half of virtual slider)"""

    ACTION_TYPE = ActionType.slider()

    def _build_config(self) -> ActionConfig:
        config = super()._build_config()
        settings = self.get_settings()
        config.orientation = settings.get("orientation", "vertical")
        config.is_top = self._volume_step > 0
        return config

    def get_config_rows(self):
        # Base class already creates the correct row for SliderAction
        rows = super().get_config_rows()

        # Orientation selector
        lm = self.plugin_base.lm
        orientation_row = Adw.ActionRow()
        orientation_row.set_title("Orientation")
        orientation_row.set_subtitle("Slider direction")

        self.orientation_combo = Gtk.ComboBoxText()
        self.orientation_combo.append("vertical", "Vertical")
        self.orientation_combo.append("horizontal", "Horizontal")
        self.orientation_combo.set_active_id(
            self.get_settings().get("orientation", "vertical")
        )
        self.orientation_combo.connect("changed", self._on_orientation_changed)
        orientation_row.add_suffix(self.orientation_combo)
        rows.append(orientation_row)

        return rows

    def _on_orientation_changed(self, combo: Gtk.ComboBoxText):
        settings = self.get_settings()
        settings["orientation"] = combo.get_active_id()
        self.set_settings(settings)
        self._update_config()

    def event_callback(self, event: Any, data: Any):
        if "Short Up" in str(event) and self._device_id:
            self._core.set_volume_relative(self._device_id, self._volume_step)
