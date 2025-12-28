"""Knob-specific action for PipeWeaver"""
from typing import Any

from src.backend.DeckManagement.InputIdentifier import Input  # type: ignore

from .action_base import PipeWeaverAction


class PipeWeaverKnobAction(PipeWeaverAction):
    def event_callback(self, event: Any, data: Any) -> None:
        if event == Input.Dial.Events.TURN_CW:
            self._set_volume_relative(self.volume_step)
        elif event == Input.Dial.Events.TURN_CCW:
            self._set_volume_relative(-self.volume_step)
        elif str(event) == "Dial Short Up":
            self._toggle_mute()
        elif event == Input.Dial.Events.SHORT_TOUCH_PRESS:
            self._toggle_mute()
    
