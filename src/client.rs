//! WebSocket client for communicating with PipeWeaver daemon

use crate::devices::{Device, DeviceType, Status};
use futures_util::{SinkExt, StreamExt};
use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot, watch};
use tokio_tungstenite::{connect_async, tungstenite::Message};

const DEFAULT_HOST: &str = "localhost";
const DEFAULT_PORT: u16 = 14565;
const RECONNECT_DELAY: Duration = Duration::from_secs(5);

type PendingRequests = Arc<RwLock<HashMap<u64, oneshot::Sender<Option<Value>>>>>;

#[derive(Debug, Serialize)]
struct Request { id: u64, data: Value }

#[derive(Debug, Deserialize)]
struct Response { id: u64, data: Value }

/// Command sent to the WebSocket task
enum Command {
    SendRequest {
        data: Value,
        response_tx: oneshot::Sender<Option<Value>>,
    },
    Shutdown,
}

/// WebSocket client for PipeWeaver main API
#[pyclass]
pub struct PipeWeaverClient {
    host: String,
    port: u16,
    running: Arc<AtomicBool>,
    connected: Arc<AtomicBool>,
    status: Arc<RwLock<Option<Status>>>,
    command_tx: Option<mpsc::Sender<Command>>,
    callbacks: Arc<RwLock<Vec<Py<PyAny>>>>,
    shutdown_tx: Option<watch::Sender<bool>>,
}

#[pymethods]
impl PipeWeaverClient {
    #[new]
    #[pyo3(signature = (host=None, port=None))]
    pub fn new(host: Option<&str>, port: Option<u16>) -> Self {
        Self {
            host: host.unwrap_or(DEFAULT_HOST).to_string(),
            port: port.unwrap_or(DEFAULT_PORT),
            running: Arc::new(AtomicBool::new(false)),
            connected: Arc::new(AtomicBool::new(false)),
            status: Arc::new(RwLock::new(None)),
            command_tx: None,
            callbacks: Arc::new(RwLock::new(Vec::new())),
            shutdown_tx: None,
        }
    }

    /// Start the WebSocket connection
    pub fn start(&mut self) {
        if self.running.swap(true, Ordering::SeqCst) {
            return; // Already running
        }

        let (shutdown_tx, shutdown_rx) = watch::channel(false);
        let (command_tx, command_rx) = mpsc::channel(32);

        self.shutdown_tx = Some(shutdown_tx);
        self.command_tx = Some(command_tx);

        let host = self.host.clone();
        let port = self.port;
        let running = self.running.clone();
        let connected = self.connected.clone();
        let status = self.status.clone();
        let callbacks = self.callbacks.clone();

        std::thread::Builder::new()
            .name("pipeweaver-client".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("Failed to create tokio runtime");

                rt.block_on(run_client_loop(
                    host,
                    port,
                    ClientState { running, connected, status, callbacks },
                    command_rx,
                    shutdown_rx,
                ));
            })
            .expect("Failed to spawn client thread");
    }

    /// Stop the WebSocket connection
    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        if let Some(tx) = self.command_tx.take() {
            let _ = tx.blocking_send(Command::Shutdown);
        }
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(true);
        }
    }

    /// Check if connected to PipeWeaver
    pub fn is_connected(&self) -> bool {
        self.connected.load(Ordering::SeqCst)
    }

    /// Get all devices
    pub fn get_devices(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(|s| s.get_all_devices())
            .unwrap_or_default()
    }

    /// Get source devices only
    pub fn get_sources(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(|s| s.get_sources())
            .unwrap_or_default()
    }

    /// Get target devices only
    pub fn get_targets(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(|s| s.get_targets())
            .unwrap_or_default()
    }

    /// Get a specific device by ID
    #[pyo3(signature = (device_id, device_type=None))]
    pub fn get_device(&self, device_id: &str, device_type: Option<DeviceType>) -> Option<Device> {
        self.status
            .read()
            .as_ref()
            .and_then(|s| s.get_device(device_id, device_type))
    }

    /// Set volume for a device (0-100)
    pub fn set_volume(&self, device_id: &str, volume: u8) -> bool {
        let Some(device) = self.get_device(device_id, None) else {
            return false;
        };

        let command = match device.device_type {
            DeviceType::Source => {
                serde_json::json!({"Pipewire": {"SetSourceVolume": [device_id, "A", volume]}})
            }
            DeviceType::Target => {
                serde_json::json!({"Pipewire": {"SetTargetVolume": [device_id, volume]}})
            }
        };

        self.send_command(command)
            .is_some_and(|r| is_pipewire_ok(&r))
    }

    /// Set volume relative to current (delta can be negative)
    pub fn set_volume_relative(&self, device_id: &str, delta: i8) -> bool {
        let Some(device) = self.get_device(device_id, None) else {
            return false;
        };

        let new_volume = (device.volume as i16 + delta as i16).clamp(0, 100) as u8;
        self.set_volume(device_id, new_volume)
    }

    /// Mute a device
    fn mute(&self, device_id: &str) -> bool {
        let Some(device) = self.get_device(device_id, None) else {
            return false;
        };

        let command = match device.device_type {
            DeviceType::Source => {
                serde_json::json!({"Pipewire": {"AddSourceMuteTarget": [device_id, "TargetA"]}})
            }
            DeviceType::Target => {
                serde_json::json!({"Pipewire": {"SetTargetMuteState": [device_id, "Muted"]}})
            }
        };

        self.send_command(command)
            .is_some_and(|r| is_pipewire_ok(&r))
    }

    /// Unmute a device
    fn unmute(&self, device_id: &str) -> bool {
        let Some(device) = self.get_device(device_id, None) else {
            return false;
        };

        let command = match device.device_type {
            DeviceType::Source => {
                serde_json::json!({"Pipewire": {"DelSourceMuteTarget": [device_id, "TargetA"]}})
            }
            DeviceType::Target => {
                serde_json::json!({"Pipewire": {"SetTargetMuteState": [device_id, "Unmuted"]}})
            }
        };

        self.send_command(command)
            .is_some_and(|r| is_pipewire_ok(&r))
    }

    /// Toggle mute state for a device
    pub fn toggle_mute(&self, device_id: &str) -> bool {
        let Some(device) = self.get_device(device_id, None) else {
            return false;
        };

        if device.is_muted {
            self.unmute(device_id)
        } else {
            self.mute(device_id)
        }
    }

    /// Add callback for status updates
    fn add_callback(&self, callback: Py<PyAny>) {
        self.callbacks.write().push(callback);
    }

    /// Remove callback by checking identity
    fn remove_callback(&self, _py: Python<'_>, callback: Py<PyAny>) {
        self.callbacks.write().retain(|c| !c.is(&callback));
    }
}

impl PipeWeaverClient {
    /// Send a command and wait for response
    fn send_command(&self, data: Value) -> Option<Value> {
        let tx = self.command_tx.as_ref()?;
        let (response_tx, response_rx) = oneshot::channel();

        tx.blocking_send(Command::SendRequest { data, response_tx })
            .ok()?;

        response_rx.blocking_recv().ok().flatten()
    }
}

impl Drop for PipeWeaverClient {
    fn drop(&mut self) {
        self.stop();
    }
}

struct ClientState {
    running: Arc<AtomicBool>,
    connected: Arc<AtomicBool>,
    status: Arc<RwLock<Option<Status>>>,
    callbacks: Arc<RwLock<Vec<Py<PyAny>>>>,
}

#[allow(clippy::too_many_arguments)]
async fn run_client_loop(
    host: String,
    port: u16,
    state: ClientState,
    mut command_rx: mpsc::Receiver<Command>,
    mut shutdown_rx: watch::Receiver<bool>,
) {
    let ClientState { running, connected, status, callbacks } = state;
    let url = format!("ws://{}:{}/api/websocket", host, port);
    let command_id = AtomicU64::new(0);
    let pending_requests: PendingRequests = Arc::new(RwLock::new(HashMap::new()));

    while running.load(Ordering::SeqCst) {
        // Try to connect
        let ws = match connect_async(&url).await {
            Ok((ws, _)) => ws,
            Err(e) => {
                tracing::warn!("WebSocket connection failed: {}", e);
                tokio::select! {
                    _ = tokio::time::sleep(RECONNECT_DELAY) => continue,
                    _ = shutdown_rx.changed() => break,
                }
            }
        };

        connected.store(true, Ordering::SeqCst);
        tracing::info!("Connected to PipeWeaver");

        let (mut write, mut read) = ws.split();

        // Request initial status
        let initial_id = command_id.fetch_add(1, Ordering::SeqCst);
        let initial_request = Request {
            id: initial_id,
            data: serde_json::json!("GetStatus"),
        };
        if let Ok(json) = serde_json::to_string(&initial_request) {
            let _ = write.send(Message::Text(json.into())).await;
        }

        // Process messages until disconnection
        loop {
            tokio::select! {
                // Handle incoming messages
                msg = read.next() => {
                    match msg {
                        Some(Ok(Message::Text(text))) => {
                            handle_message(
                                &text,
                                &status,
                                &callbacks,
                                &pending_requests,
                            );
                        }
                        Some(Err(e)) => {
                            tracing::warn!("WebSocket error: {}", e);
                            break;
                        }
                        None => {
                            tracing::info!("WebSocket closed");
                            break;
                        }
                        _ => {}
                    }
                }

                // Handle outgoing commands
                cmd = command_rx.recv() => {
                    match cmd {
                        Some(Command::SendRequest { data, response_tx }) => {
                            let id = command_id.fetch_add(1, Ordering::SeqCst);
                            let request = Request { id, data };

                            pending_requests.write().insert(id, response_tx);

                            if let Ok(json) = serde_json::to_string(&request) {
                                if write.send(Message::Text(json.into())).await.is_err() {
                                    break;
                                }
                            }
                        }
                        Some(Command::Shutdown) | None => {
                            running.store(false, Ordering::SeqCst);
                            break;
                        }
                    }
                }

                // Handle shutdown
                _ = shutdown_rx.changed() => {
                    if *shutdown_rx.borrow() {
                        running.store(false, Ordering::SeqCst);
                        break;
                    }
                }
            }
        }

        connected.store(false, Ordering::SeqCst);

        // Clear pending requests
        pending_requests.write().clear();

        // Wait before reconnecting
        if running.load(Ordering::SeqCst) {
            tokio::select! {
                _ = tokio::time::sleep(RECONNECT_DELAY) => {}
                _ = shutdown_rx.changed() => {}
            }
        }
    }
}

fn handle_message(
    text: &str,
    status: &Arc<RwLock<Option<Status>>>,
    callbacks: &Arc<RwLock<Vec<Py<PyAny>>>>,
    pending_requests: &PendingRequests,
) {
    let Ok(response) = serde_json::from_str::<Response>(text) else { return };

    // Patch updates
    if let Some(patch) = response.data.get("Patch").and_then(|p| p.as_array()) {
        apply_patch(status, patch);
        notify_callbacks(callbacks, status);
        return;
    }

    // Status response
    if let Some(status_data) = response.data.get("Status") {
        if let Ok(new_status) = serde_json::from_value::<Status>(status_data.clone()) {
            *status.write() = Some(new_status);
            notify_callbacks(callbacks, status);
        }
    }

    // Command response
    if let Some(tx) = pending_requests.write().remove(&response.id) {
        let _ = tx.send(Some(response.data));
    }
}

/// Apply JSON Patch operations to status
fn apply_patch(status: &Arc<RwLock<Option<Status>>>, patch: &[Value]) {
    let mut status_guard = status.write();
    let Some(status) = status_guard.as_mut() else {
        return;
    };

    // Convert status to Value, apply patches, convert back
    let Ok(mut value) = serde_json::to_value(&*status) else {
        return;
    };

    for op in patch {
        if let Err(e) = apply_patch_op(&mut value, op) {
            tracing::warn!("Failed to apply patch: {}", e);
        }
    }

    if let Ok(new_status) = serde_json::from_value::<Status>(value) {
        *status = new_status;
    }
}

/// Apply a single JSON Patch operation (crate-internal)
pub(crate) fn apply_patch_op(doc: &mut Value, op: &Value) -> Result<(), String> {
    let operation = op.get("op").and_then(|v| v.as_str()).ok_or("Missing op")?;
    let path = op
        .get("path")
        .and_then(|v| v.as_str())
        .ok_or("Missing path")?;

    let (parent, key) = resolve_pointer_parent(doc, path)?;

    match operation {
        "add" | "replace" => {
            let value = op.get("value").cloned().ok_or("Missing value")?;
            match parent {
                Value::Array(arr) => {
                    if key == "-" {
                        arr.push(value);
                    } else {
                        let idx: usize = key.parse().map_err(|_| "Invalid array index")?;
                        if idx >= arr.len() {
                            arr.push(value);
                        } else {
                            arr[idx] = value;
                        }
                    }
                }
                Value::Object(obj) => {
                    obj.insert(key, value);
                }
                _ => return Err("Parent is not a container".into()),
            }
        }
        "remove" => match parent {
            Value::Array(arr) => {
                let idx: usize = key.parse().map_err(|_| "Invalid array index")?;
                if idx < arr.len() {
                    arr.remove(idx);
                }
            }
            Value::Object(obj) => {
                obj.remove(&key);
            }
            _ => return Err("Parent is not a container".into()),
        },
        _ => {
            tracing::warn!("Unsupported patch operation: {}", operation);
        }
    }

    Ok(())
}

/// Resolve a JSON Pointer path to parent and key
fn resolve_pointer_parent<'a>(
    doc: &'a mut Value,
    path: &str,
) -> Result<(&'a mut Value, String), String> {
    if !path.starts_with('/') {
        return Err("Path must start with /".into());
    }

    let parts: Vec<String> = path[1..]
        .split('/')
        .map(|p| p.replace("~1", "/").replace("~0", "~"))
        .collect();

    if parts.is_empty() {
        return Err("Empty path".into());
    }

    let key = parts.last().ok_or("Empty path")?.clone();
    let parent_path = &parts[..parts.len() - 1];

    let mut current = doc;
    for part in parent_path {
        current = match current {
            Value::Array(arr) => {
                let idx: usize = part.parse().map_err(|_| "Invalid array index")?;
                arr.get_mut(idx).ok_or("Array index out of bounds")?
            }
            Value::Object(obj) => obj.entry(part.as_str()).or_insert(Value::Object(Default::default())),
            _ => return Err("Cannot traverse non-container".into()),
        };
    }

    Ok((current, key))
}

/// Check if response indicates Pipewire command succeeded
fn is_pipewire_ok(response: &Value) -> bool {
    if let Some(pw) = response.get("Pipewire") {
        return pw == "Ok" || pw.get("Ok").is_some();
    }
    false
}

/// Notify callbacks of status update
fn notify_callbacks(callbacks: &Arc<RwLock<Vec<Py<PyAny>>>>, status: &Arc<RwLock<Option<Status>>>) {
    // Serialize status first (no GIL needed)
    let status_json: Option<String> = {
        let status_guard = status.read();
        status_guard
            .as_ref()
            .and_then(|s| serde_json::to_value(s).ok())
            .map(|v| v.to_string())
    };

    let Some(json_str) = status_json else {
        return;
    };

    Python::attach(|py| {
        // Clone callbacks with GIL held (Py<T> requires GIL for Clone)
        let callbacks_clone: Vec<Py<PyAny>> = {
            let guard = callbacks.read();
            guard.iter().map(|c| c.clone_ref(py)).collect()
        };

        for callback in callbacks_clone.iter() {
            if let Err(e) = callback.call1(py, (&json_str,)) {
                tracing::error!("Error in status callback: {}", e);
            }
        }
    });
}
