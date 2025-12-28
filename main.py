"""Simplified main plugin class"""
import os
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
from loguru import logger as log  # type: ignore

from src.backend.DeckManagement.InputIdentifier import Input  # type: ignore
from src.backend.PluginManager.ActionHolder import ActionHolder  # type: ignore
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport  # type: ignore
from src.backend.PluginManager.PluginBase import PluginBase  # type: ignore

from .knob_action import PipeWeaverKnobAction
from .service_monitor import start_monitor, stop_monitor


class DeckWeaver(PluginBase):
    def __init__(self):
        super().__init__()
        self.init_vars()
        self.load_and_apply_settings()
        self.load_devices()
        self.register_plugin()
        start_monitor()
    
    def init_vars(self) -> None:
        self.lm = self.locale_manager
    
    def load_and_apply_settings(self) -> None:
        settings = self.get_settings()
        language = settings.get("language", "auto")
        
        if language != "auto":
            self._set_language(language)
        else:
            self.lm.set_to_os_default()
    
    def _set_language(self, language: str) -> None:
        try:
            self.lm.set_language(language)
        except AttributeError:
            try:
                self.lm.set_locale(language)
            except AttributeError:
                if hasattr(self.lm, 'language'):
                    self.lm.language = language
                else:
                    self.lm.set_to_os_default()
    
    def register_plugin(self) -> None:
        self.register(
            plugin_name=self.lm.get("plugin.name"),
            github_repo="https://github.com/designgears/DeckWeaver",
            plugin_version="1.0.0",
            app_version="1.5.0-beta"
        )
    
    def load_devices(self) -> None:
        try:
            self.load_icon_assets()
            self._register_knob_action()
        except Exception as e:
            log.error(f"Error registering actions: {e}")
    
    def _register_knob_action(self) -> None:
        knob_holder = ActionHolder(
            plugin_base=self,
            action_base=PipeWeaverKnobAction,
            action_id_suffix="Knob",
            action_name=self.lm.get("actions.knob.name"),
            action_support={
                Input.Key: ActionInputSupport.UNSUPPORTED,
                Input.Dial: ActionInputSupport.SUPPORTED,
                Input.Touchscreen: ActionInputSupport.SUPPORTED
            }
        )
        self.add_action_holder(knob_holder)
    
    def load_icon_assets(self) -> None:
        try:
            from src.backend.PluginManager.PluginSettings.Asset import Icon
            
            icon_assets = {
                "pipeweaver": "pipeweaver.png",
                "audio": "audio.png",
                "volume": "volume.png",
                "mute": "mute.png",
                "a-b-outline": "a-b-outline.png"
            }
            
            for asset_name, filename in icon_assets.items():
                icon_path = self.get_asset_path(filename, ["icons"])
                if os.path.exists(icon_path):
                    icon = Icon(icon_path)
                    self.asset_manager.icons.add_asset(asset_name, icon)
        except Exception as e:
            log.warning(f"Could not load icon assets: {e}")
    
    def get_settings_area(self) -> Adw.PreferencesGroup:
        languages = [
            ("auto", self.lm.get("settings.language.name.auto")),
            ("en_US", self.lm.get("settings.language.name.en_US")),
            ("es_ES", self.lm.get("settings.language.name.es_ES")),
            ("fr_FR", self.lm.get("settings.language.name.fr_FR")),
            ("de_DE", self.lm.get("settings.language.name.de_DE")),
        ]

        language_names = [name for _, name in languages]
        self.language_model = Gtk.StringList().new(language_names)
        self.language_dropdown = Adw.ComboRow(
            model=self.language_model,
            title=self.lm.get("settings.language.label")
        )
        
        settings = self.get_settings()
        current_language = settings.get("language", "auto")
        
        for i, (code, name) in enumerate(languages):
            if code == current_language:
                self.language_dropdown.set_selected(i)
                break
        
        self.language_dropdown.connect("notify::selected", self.on_language_changed)
        
        group = Adw.PreferencesGroup()
        group.add(self.language_dropdown)
        return group
    
    def on_language_changed(self, combo: Adw.ComboRow, data: Any) -> None:
        selected_index = combo.get_selected()
        
        languages = [
            ("auto", self.lm.get("settings.language.name.auto")),
            ("en_US", self.lm.get("settings.language.name.en_US")),
            ("es_ES", self.lm.get("settings.language.name.es_ES")),
            ("fr_FR", self.lm.get("settings.language.name.fr_FR")),
            ("de_DE", self.lm.get("settings.language.name.de_DE")),
        ]

        if selected_index < len(languages):
            selected_code, _ = languages[selected_index]
            settings = self.get_settings()
            settings["language"] = selected_code
            self.set_settings(settings)
            self.load_and_apply_settings()
    
    def on_enable(self) -> None:
        pass
    
    def on_disable(self) -> None:
        stop_monitor()
