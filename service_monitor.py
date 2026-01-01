"""Global PipeWeaver service monitor"""
import socket
import threading
import time
from typing import Callable, Final, Set

from loguru import logger as log

# PipeWeaver configuration
PIPEWEAVER_HOST: Final[str] = "localhost"  # Hostname or IP address where PipeWeaver daemon is running
PIPEWEAVER_PORT: Final[int] = 14565  # Port number where PipeWeaver daemon is listening

# Service monitor configuration
CHECK_INTERVAL: Final[float] = 5.0  # Seconds between service availability checks (how often to ping the daemon)
CONNECTION_TIMEOUT: Final[float] = 2.0  # Seconds for socket connection timeout (how long to wait when checking if service is available)

_service_available: bool = False
_monitor_thread: threading.Thread | None = None
_monitor_running: bool = False
_monitor_lock = threading.Lock()
_state_callbacks: Set[Callable[[bool], None]] = set()
_callbacks_lock = threading.Lock()


def _check_service() -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECTION_TIMEOUT)
        result = sock.connect_ex((PIPEWEAVER_HOST, PIPEWEAVER_PORT))
        sock.close()
        return result == 0
    except Exception:
        return False


def _notify_callbacks(available: bool) -> None:
    with _callbacks_lock:
        callbacks = list(_state_callbacks)
    
    for callback in callbacks:
        try:
            callback(available)
        except Exception as e:
            log.error(f"Error in service state callback: {e}")


def _monitor_loop() -> None:
    global _service_available, _monitor_running
    
    while _monitor_running:
        available = _check_service()
        
        with _monitor_lock:
            old_state = _service_available
            _service_available = available
            
        if old_state != available:
            _notify_callbacks(available)
        
        time.sleep(CHECK_INTERVAL)


def start_monitor() -> None:
    global _monitor_thread, _monitor_running
    
    with _monitor_lock:
        if _monitor_running:
            return
        
        _monitor_running = True
        _monitor_thread = threading.Thread(
            target=_monitor_loop,
            daemon=True,
            name="PipeWeaverServiceMonitor"
        )
        _monitor_thread.start()


def stop_monitor() -> None:
    global _monitor_thread, _monitor_running
    
    with _monitor_lock:
        _monitor_running = False
    
    if _monitor_thread:
        _monitor_thread.join(timeout=2)
        _monitor_thread = None


def is_service_available() -> bool:
    with _monitor_lock:
        return _service_available


def add_state_change_callback(callback: Callable[[bool], None]) -> None:
    if callback:
        with _callbacks_lock:
            _state_callbacks.add(callback)


def remove_state_change_callback(callback: Callable[[bool], None]) -> None:
    if callback:
        with _callbacks_lock:
            _state_callbacks.discard(callback)
