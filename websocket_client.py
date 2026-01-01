"""WebSocket client for communicating with PipeWeaver daemon"""
import json
import threading
import time
from queue import Empty, Queue
from typing import Any, Callable, Optional

import websocket  # type: ignore
from loguru import logger as log  # type: ignore

from .constants import (
    COMMAND_TIMEOUT,
    INITIAL_STATUS_TIMEOUT,
    JSON_PATCH_ADD,
    JSON_PATCH_REMOVE,
    JSON_PATCH_REPLACE,
    MESSAGE_ID_PATCH,
    PIPEWEAVER_METER_ENDPOINT,
    PIPEWEAVER_PORT,
    PIPEWEAVER_WS_ENDPOINT,
    RECONNECT_DELAY,
    WS_SOCK_TIMEOUT,
    WS_TIMEOUT,
    DEVICE_TYPE_SOURCE,
    DEVICE_TYPE_TARGET,
)
from .pipeweaver_helpers import (
    DevicesTree,
    get_device_by_id,
    get_device_list,
    get_devices_tree,
)

_shared_pipeweaver_client: Optional['PipeWeaverWebSocketClient'] = None
_shared_pipeweaver_refcount: int = 0
_shared_pipeweaver_lock = threading.Lock()

_shared_meter_client: Optional['MeterWebSocketClient'] = None
_shared_meter_refcount: int = 0
_shared_meter_lock = threading.Lock()

PatchCallback = Callable[[dict[str, Any]], None]
MeterCallback = Callable[[str, int], None]


def _decode_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_json_pointer_parent(
    doc: dict[str, Any] | list[Any], path: str
) -> tuple[dict[str, Any] | list[Any], str]:
    if not path.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer path: {path}")

    parts = [_decode_json_pointer_token(p) for p in path.lstrip("/").split("/") if p != ""]
    if not parts:
        raise ValueError("Empty JSON Pointer path")

    target = doc
    for part in parts[:-1]:
        if isinstance(target, list):
            index = int(part)
            if index < 0 or index >= len(target):
                raise IndexError(f"List index out of range: {index}")
            target = target[index]
        else:
            if part not in target or not isinstance(target[part], (dict, list)):
                target[part] = {}
            target = target[part]

    return target, parts[-1]


def _apply_single_patch_op(
    doc: dict[str, Any] | list[Any], op: dict[str, Any]
) -> None:
    operation = op.get("op")
    path = op.get("path")
    if path is None:
        raise ValueError(f"Patch operation missing path: {op}")

    parent, key = _resolve_json_pointer_parent(doc, path)

    if operation in (JSON_PATCH_ADD, JSON_PATCH_REPLACE):
        value = op.get("value")
        if isinstance(parent, list):
            if key == "-":
                parent.append(value)
            else:
                index = int(key)
                if operation == JSON_PATCH_ADD and index == len(parent):
                    parent.append(value)
                else:
                    parent[index] = value
        else:
            parent[key] = value
    elif operation == JSON_PATCH_REMOVE:
        if isinstance(parent, list):
            del parent[int(key)]
        else:
            del parent[key]
    else:
        log.warning(f"Unsupported JSON Patch operation: {operation}")


def apply_status_patch(status: dict[str, Any], patch: list[dict[str, Any]]) -> None:
    if not isinstance(patch, list):
        log.warning(f"Invalid patch format: {type(patch)}")
        return

    for op in patch:
        try:
            if isinstance(op, dict):
                _apply_single_patch_op(status, op)
        except Exception as e:
            log.error(f"Error applying patch operation {op}: {e}")


class MeterWebSocketClient:
    def __init__(self, callback: Optional[MeterCallback] = None, port: int = PIPEWEAVER_PORT):
        self._callbacks_lock = threading.Lock()
        self._callbacks: set[MeterCallback] = set()
        if callback:
            self._callbacks.add(callback)
        self.port = port
        self.ws: Optional[websocket.WebSocket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def add_callback(self, callback: MeterCallback) -> None:
        if callback:
            with self._callbacks_lock:
                self._callbacks.add(callback)

    def remove_callback(self, callback: MeterCallback) -> None:
        if callback:
            with self._callbacks_lock:
                self._callbacks.discard(callback)

    def _get_callbacks_snapshot(self) -> list[MeterCallback]:
        with self._callbacks_lock:
            return list(self._callbacks)

    def _run(self) -> None:
        while self.running:
            try:
                url = PIPEWEAVER_METER_ENDPOINT.replace(f":{PIPEWEAVER_PORT}", f":{self.port}")
                self.ws = websocket.create_connection(url, timeout=WS_TIMEOUT)

                while self.running:
                    try:
                        if self.ws:
                            self.ws.sock.settimeout(WS_SOCK_TIMEOUT)
                        message = self.ws.recv()
                        if message:
                            data = json.loads(message)
                            if 'id' in data and 'percent' in data:
                                for cb in self._get_callbacks_snapshot():
                                    try:
                                        cb(str(data['id']), int(data['percent']))
                                    except Exception as e:
                                        log.error(f"Error in meter callback: {e}")
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        break
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        log.error(f"Error receiving meter message: {e}")
                        break

            except (ConnectionRefusedError, OSError):
                if self.running:
                    time.sleep(RECONNECT_DELAY)
            except Exception as e:
                if self.running:
                    log.warning(f"Meter WebSocket connection error: {e}")
                    time.sleep(RECONNECT_DELAY)
            finally:
                self.ws = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="MeterWebSocket")
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=2)


class PipeWeaverWebSocketClient:
    def __init__(
        self,
        port: int = PIPEWEAVER_PORT,
        patch_callback: Optional[PatchCallback] = None
    ):
        self.port = port
        self._patch_callbacks_lock = threading.Lock()
        self._patch_callbacks: set[PatchCallback] = set()
        if patch_callback:
            self._patch_callbacks.add(patch_callback)
        self.ws: Optional[websocket.WebSocket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.command_id = 0
        self.message_queue: dict[int, tuple[Queue[Any], threading.Event]] = {}
        self.status: Optional[dict[str, Any]] = None
        self.connected = False

    def add_patch_callback(self, callback: PatchCallback) -> None:
        if callback:
            with self._patch_callbacks_lock:
                self._patch_callbacks.add(callback)
    
    def remove_patch_callback(self, callback: PatchCallback) -> None:
        if callback:
            with self._patch_callbacks_lock:
                self._patch_callbacks.discard(callback)

    def _get_patch_callbacks_snapshot(self) -> list[PatchCallback]:
        with self._patch_callbacks_lock:
            return list(self._patch_callbacks)

    def _wait_for_connection(self, max_wait: float = COMMAND_TIMEOUT) -> None:
        wait_time = 0.0
        while not self.connected and wait_time < max_wait and self.running:
            time.sleep(0.1)
            wait_time += 0.1

    def _is_pipewire_ok(self, response: Any) -> bool:
        return bool(
            response
            and isinstance(response, tuple)
            and len(response) == 2
            and response[0] == "Pipewire"
            and response[1] in ["Ok", {"Ok": None}]
        )

    def _send_command(
        self, request_data: Any, timeout: float = COMMAND_TIMEOUT
    ) -> Optional[tuple[str, Any]]:
        self._wait_for_connection(COMMAND_TIMEOUT)
        
        with self.lock:
            if not self.connected or not self.ws:
                return None
            
            command_id = self.command_id
            self.command_id += 1
            response_queue = Queue()
            event = threading.Event()
            self.message_queue[command_id] = (response_queue, event)
        
        try:
            request_json = json.dumps({"id": command_id, "data": request_data})
            with self.lock:
                ws = self.ws
                if not ws or not self.connected:
                    self.message_queue.pop(command_id, None)
                    return None

            ws.send(request_json)
            
            if event.wait(timeout):
                try:
                    return response_queue.get_nowait()
                except Empty:
                    return None
            else:
                with self.lock:
                    self.message_queue.pop(command_id, None)
                return None
        except Exception as e:
            log.error(f"Error sending command: {e}")
            with self.lock:
                self.message_queue.pop(command_id, None)
            return None
    
    def _handle_message(self, message: str) -> None:
        try:
            msg = json.loads(message)
            msg_id = msg.get("id")
            msg_data = msg.get("data")
            
            if msg_id is None or msg_data is None:
                return
            
            if msg_id == MESSAGE_ID_PATCH or (isinstance(msg_data, dict) and "Patch" in msg_data):
                if isinstance(msg_data, dict) and "Patch" in msg_data:
                    self._handle_patch(msg_data["Patch"])
                return

            with self.lock:
                if msg_id in self.message_queue:
                    response_queue, event = self.message_queue[msg_id]
                    if isinstance(msg_data, dict):
                        if "Status" in msg_data:
                            self.status = msg_data["Status"]
                            response_queue.put(("Status", self.status))
                        elif "Err" in msg_data:
                            response_queue.put(("Err", msg_data["Err"]))
                        elif "Pipewire" in msg_data:
                            response_queue.put(("Pipewire", msg_data["Pipewire"]))
                        else:
                            response_queue.put(("Unknown", msg_data))
                    elif msg_data == "Ok":
                        response_queue.put(("Ok", None))
                    else:
                        response_queue.put(("Unknown", msg_data))

                    event.set()
                    del self.message_queue[msg_id]
        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.error(f"Error handling message: {e}")
    
    def _handle_patch(self, patch: list[dict[str, Any]]) -> None:
        with self.lock:
            if not self.status:
                self.status = {}
            apply_status_patch(self.status, patch)
            status_snapshot = self.status.copy()

        for cb in self._get_patch_callbacks_snapshot():
            try:
                cb(status_snapshot)
            except Exception as e:
                log.error(f"Error in patch callback: {e}")
    
    
    def _run(self) -> None:
        while self.running:
            try:
                url = PIPEWEAVER_WS_ENDPOINT.replace(f":{PIPEWEAVER_PORT}", f":{self.port}")
                self.ws = websocket.create_connection(url, timeout=WS_TIMEOUT)
                self.connected = True
                
                self._request_initial_status_once()
                
                while self.running:
                    try:
                        if self.ws:
                            self.ws.sock.settimeout(WS_SOCK_TIMEOUT)
                        message = self.ws.recv()
                        if message:
                            self._handle_message(message)
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        break
                    except Exception as e:
                        log.error(f"Error receiving message: {e}")
                        break
                        
            except (ConnectionRefusedError, OSError):
                if self.running:
                    time.sleep(RECONNECT_DELAY)
            except Exception as e:
                if self.running:
                    log.warning(f"WebSocket connection error: {e}")
                    time.sleep(RECONNECT_DELAY)
            finally:
                self.connected = False
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                self.ws = None
    
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="PipeWeaverWebSocket")
        self.thread.start()
    
    def stop(self) -> None:
        self.running = False
        self.connected = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=2)
    
    def _request_initial_status_once(self) -> None:
        def request_once() -> None:
            try:
                time.sleep(0.2)
                response = self._send_command("GetStatus", timeout=INITIAL_STATUS_TIMEOUT)
                if response and response[0] == "Status":
                    with self.lock:
                        self.status = response[1]
            except Exception:
                pass
        
        threading.Thread(target=request_once, daemon=True, name="InitialStatusRequest").start()
    
    def _get_status(self) -> Optional[dict[str, Any]]:
        with self.lock:
            return self.status
    
    def _get_devices_tree(self) -> DevicesTree:
        return get_devices_tree(self._get_status())
    
    def get_devices(self) -> list[dict[str, str]]:
        return get_device_list(self._get_devices_tree())
    
    def _get_device_type(self, device_id: str) -> Optional[str]:
        devices_tree = self._get_devices_tree()
        if not devices_tree:
            return None
        
        if get_device_by_id(devices_tree, device_id, DEVICE_TYPE_SOURCE):
            return DEVICE_TYPE_SOURCE
        if get_device_by_id(devices_tree, device_id, DEVICE_TYPE_TARGET):
            return DEVICE_TYPE_TARGET
        return None
    
    def mute_device(self, device_id: str) -> bool:
        device_type = self._get_device_type(device_id)
        if not device_type:
            return False
        
        if device_type == DEVICE_TYPE_SOURCE:
            return self._send_pipewire_command({"AddSourceMuteTarget": [device_id, "TargetA"]})
        elif device_type == DEVICE_TYPE_TARGET:
            return self._send_pipewire_command({"SetTargetMuteState": [device_id, "Muted"]})
        return False
    
    def _send_pipewire_command(self, command: dict[str, Any]) -> bool:
        response = self._send_command({"Pipewire": command})
        return self._is_pipewire_ok(response)
    
    def unmute_device(self, device_id: str) -> bool:
        device_type = self._get_device_type(device_id)
        if not device_type:
            return False
        
        if device_type == DEVICE_TYPE_SOURCE:
            return self._send_pipewire_command({"DelSourceMuteTarget": [device_id, "TargetA"]})
        elif device_type == DEVICE_TYPE_TARGET:
            return self._send_pipewire_command({"SetTargetMuteState": [device_id, "Unmuted"]})
        return False
    
    def set_volume(self, device_id: str, volume: int) -> bool:
        device_type = self._get_device_type(device_id)
        if not device_type:
            return False
        
        if device_type == DEVICE_TYPE_SOURCE:
            command = {"SetSourceVolume": [device_id, "A", volume]}
        elif device_type == DEVICE_TYPE_TARGET:
            command = {"SetTargetVolume": [device_id, volume]}
        else:
            return False
        
        return self._send_pipewire_command(command)
    
    def set_volume_relative(
        self,
        device_id: str,
        delta: int,
        current_volume: Optional[int] = None
    ) -> bool:
        if current_volume is None:
            return False
        new_volume = max(0, min(100, current_volume + delta))
        return self.set_volume(device_id, new_volume)
    

def acquire_shared_pipeweaver_client(
    patch_callback: Optional[PatchCallback] = None,
    port: int = PIPEWEAVER_PORT
) -> PipeWeaverWebSocketClient:
    global _shared_pipeweaver_client, _shared_pipeweaver_refcount

    with _shared_pipeweaver_lock:
        if _shared_pipeweaver_client is None:
            _shared_pipeweaver_client = PipeWeaverWebSocketClient(port=port)
            _shared_pipeweaver_client.start()

        _shared_pipeweaver_refcount += 1
        if patch_callback:
            _shared_pipeweaver_client.add_patch_callback(patch_callback)

        return _shared_pipeweaver_client


def release_shared_pipeweaver_client(
    patch_callback: Optional[PatchCallback] = None
) -> None:
    global _shared_pipeweaver_client, _shared_pipeweaver_refcount

    with _shared_pipeweaver_lock:
        if _shared_pipeweaver_client is None:
            return

        if patch_callback:
            _shared_pipeweaver_client.remove_patch_callback(patch_callback)

        _shared_pipeweaver_refcount -= 1
        if _shared_pipeweaver_refcount <= 0:
            try:
                _shared_pipeweaver_client.stop()
            except Exception:
                pass
            _shared_pipeweaver_client = None
            _shared_pipeweaver_refcount = 0


def acquire_shared_meter_client(
    callback: Optional[MeterCallback] = None,
    port: int = PIPEWEAVER_PORT
) -> MeterWebSocketClient:
    global _shared_meter_client, _shared_meter_refcount

    with _shared_meter_lock:
        if _shared_meter_client is None:
            _shared_meter_client = MeterWebSocketClient(port=port)
            _shared_meter_client.start()

        _shared_meter_refcount += 1
        if callback:
            _shared_meter_client.add_callback(callback)

        return _shared_meter_client


def release_shared_meter_client(callback: Optional[MeterCallback] = None) -> None:
    global _shared_meter_client, _shared_meter_refcount

    with _shared_meter_lock:
        if _shared_meter_client is None:
            return

        if callback:
            _shared_meter_client.remove_callback(callback)

        _shared_meter_refcount -= 1
        if _shared_meter_refcount <= 0:
            try:
                _shared_meter_client.stop()
            except Exception:
                pass
            _shared_meter_client = None
            _shared_meter_refcount = 0
