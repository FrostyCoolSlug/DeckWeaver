"""Global PipeWeaver service monitor - decoupled health check for the plugin.

This module provides a simple, global service availability check that runs
independently from the rest of the plugin. Actions can query is_service_available()
to determine if they should show an error state.

Actions can register callbacks via add_state_change_callback() to be notified
when the service availability changes, allowing them to update their display.
"""
import threading
import time
import socket
from loguru import logger as log

_service_available = False
_monitor_thread = None
_monitor_running = False
_monitor_lock = threading.Lock()

# Callbacks to notify when state changes
_state_callbacks = set()
_callbacks_lock = threading.Lock()

# Configuration
PIPEWEAVER_HOST = "localhost"
PIPEWEAVER_PORT = 14565
CHECK_INTERVAL = 5.0  # seconds between checks


def _check_service() -> bool:
    """Quick TCP connect check to see if PipeWeaver is listening."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex((PIPEWEAVER_HOST, PIPEWEAVER_PORT))
        sock.close()
        return result == 0
    except Exception:
        return False


def _notify_callbacks(available: bool):
    """Notify all registered callbacks of state change."""
    with _callbacks_lock:
        callbacks = list(_state_callbacks)
    
    for callback in callbacks:
        try:
            callback(available)
        except Exception as e:
            log.error(f"Error in service state callback: {e}")


def _monitor_loop():
    """Background loop that periodically checks service availability."""
    global _service_available, _monitor_running
    
    while _monitor_running:
        available = _check_service()
        
        with _monitor_lock:
            old_state = _service_available
            _service_available = available
            
        if old_state != available:
            if available:
                log.info("PipeWeaver service is now available")
            else:
                log.warning("PipeWeaver service is unavailable")
            # Notify callbacks of state change
            _notify_callbacks(available)
        
        time.sleep(CHECK_INTERVAL)


def start_monitor():
    """Start the background service monitor if not already running."""
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
        log.debug("PipeWeaver service monitor started")


def stop_monitor():
    """Stop the background service monitor."""
    global _monitor_thread, _monitor_running
    
    with _monitor_lock:
        _monitor_running = False
    
    if _monitor_thread:
        _monitor_thread.join(timeout=2)
        _monitor_thread = None
        log.debug("PipeWeaver service monitor stopped")


def is_service_available() -> bool:
    """Check if PipeWeaver service is currently available.
    
    This is a non-blocking call that returns the last known state.
    The monitor updates this state in the background.
    """
    with _monitor_lock:
        return _service_available


def force_check() -> bool:
    """Force an immediate service check and update state.
    
    Returns the current availability status.
    """
    global _service_available
    
    available = _check_service()
    with _monitor_lock:
        old_state = _service_available
        _service_available = available
    
    if old_state != available:
        _notify_callbacks(available)
    
    return available


def add_state_change_callback(callback):
    """Register a callback to be notified when service availability changes.
    
    The callback will be called with a single boolean argument indicating
    whether the service is now available.
    """
    with _callbacks_lock:
        _state_callbacks.add(callback)


def remove_state_change_callback(callback):
    """Remove a previously registered callback."""
    with _callbacks_lock:
        _state_callbacks.discard(callback)
