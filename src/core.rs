//! Core manager that orchestrates all Rust functionality

use crate::action::{ActionConfig, ActionState, ActionType};
use crate::devices::{Device, DeviceType, Status};
use crate::render::{ButtonRenderer, KnobRenderer, RenderParams, SliderRenderer};

use futures_util::StreamExt;
use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use serde_json::Value;
use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use tokio_tungstenite::{connect_async, tungstenite::Message};

const RENDER_INTERVAL: Duration = Duration::from_millis(33);
const DEFAULT_HOST: &str = "localhost";
const DEFAULT_PORT: u16 = 14565;
const RECONNECT_DELAY: Duration = Duration::from_secs(5);
const SERVICE_CHECK_INTERVAL: Duration = Duration::from_secs(2);

#[derive(Debug)]
enum Command {
    SetVolume { device_id: String, volume: u8 },
    SetVolumeRelative { device_id: String, delta: i8 },
    ToggleMute { device_id: String },
}

#[pyclass]
pub struct DeckWeaverCore {
    running: Arc<AtomicBool>,
    service_available: Arc<AtomicBool>,
    status: Arc<RwLock<Option<Status>>>,
    actions: Arc<RwLock<HashMap<String, ActionState>>>,
    meter_data: Arc<RwLock<HashMap<String, u8>>>,
    image_callbacks: Arc<RwLock<HashMap<String, Py<PyAny>>>>,
    label_callbacks: Arc<RwLock<HashMap<String, Py<PyAny>>>>,
    command_tx: Arc<RwLock<Option<mpsc::Sender<Command>>>>,
}

#[pymethods]
impl DeckWeaverCore {
    #[new]
    fn new() -> Self {
        Self {
            running: Arc::new(AtomicBool::new(false)),
            service_available: Arc::new(AtomicBool::new(false)),
            status: Arc::new(RwLock::new(None)),
            actions: Arc::new(RwLock::new(HashMap::new())),
            meter_data: Arc::new(RwLock::new(HashMap::new())),
            image_callbacks: Arc::new(RwLock::new(HashMap::new())),
            label_callbacks: Arc::new(RwLock::new(HashMap::new())),
            command_tx: Arc::new(RwLock::new(None)),
        }
    }

    fn start(&mut self) {
        if self.running.swap(true, Ordering::SeqCst) {
            return;
        }
        self.start_websocket_thread();
        self.start_meter_thread();
        self.start_render_thread();
        self.start_monitor_thread();
        tracing::info!("DeckWeaverCore started");
    }

    fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        tracing::info!("DeckWeaverCore stopped");
    }

    fn register_action(&self, config: ActionConfig) {
        let action_id = config.action_id.clone();
        self.actions.write().insert(action_id, ActionState::new(config));
    }

    fn unregister_action(&self, action_id: &str) {
        self.actions.write().remove(action_id);
    }

    fn update_action(&self, action_id: &str, config: ActionConfig) {
        if let Some(state) = self.actions.write().get_mut(action_id) {
            state.config = config;
            state.device = None;
            state.last_render_hash.store(255, Ordering::Relaxed);
        }
    }

    fn add_image_callback(&self, action_id: String, callback: Py<PyAny>) {
        self.image_callbacks.write().insert(action_id, callback);
    }

    fn remove_image_callback(&self, action_id: &str) {
        self.image_callbacks.write().remove(action_id);
    }

    fn add_label_callback(&self, action_id: String, callback: Py<PyAny>) {
        self.label_callbacks.write().insert(action_id, callback);
    }

    fn remove_label_callback(&self, action_id: &str) {
        self.label_callbacks.write().remove(action_id);
    }

    fn is_available(&self) -> bool {
        self.service_available.load(Ordering::Relaxed) || self.status.read().is_some()
    }

    fn get_devices(&self) -> Vec<Device> {
        self.status.read().as_ref().map(|s| s.get_all_devices()).unwrap_or_default()
    }

    #[pyo3(name = "get_sources")]
    fn py_get_sources(&self) -> Vec<Device> {
        self.status.read().as_ref().map(|s| s.get_sources()).unwrap_or_default()
    }

    #[pyo3(name = "get_targets")]
    fn py_get_targets(&self) -> Vec<Device> {
        self.status.read().as_ref().map(|s| s.get_targets()).unwrap_or_default()
    }

    fn get_device(&self, device_id: &str) -> Option<Device> {
        self.status.read().as_ref().and_then(|s| s.get_device(device_id, None))
    }

    fn set_volume(&self, device_id: &str, volume: u8) -> bool {
        self.send_command(Command::SetVolume { device_id: device_id.to_string(), volume })
    }

    fn set_volume_relative(&self, device_id: &str, delta: i8) -> bool {
        self.send_command(Command::SetVolumeRelative { device_id: device_id.to_string(), delta })
    }

    fn toggle_mute(&self, device_id: &str) -> bool {
        self.send_command(Command::ToggleMute { device_id: device_id.to_string() })
    }

    fn force_render(&self, action_id: &str) {
        if let Some(state) = self.actions.read().get(action_id) {
            state.last_render_hash.store(255, Ordering::Relaxed);
        }
    }

    fn get_action_device_name(&self, action_id: &str) -> Option<String> {
        self.actions.read().get(action_id).and_then(|s| s.device.as_ref()).map(|d| d.name.clone())
    }
}

impl DeckWeaverCore {
    fn send_command(&self, cmd: Command) -> bool {
        self.command_tx.read().as_ref().is_some_and(|tx| tx.blocking_send(cmd).is_ok())
    }

    fn start_websocket_thread(&self) {
        let running = self.running.clone();
        let status = self.status.clone();
        let command_tx_holder = self.command_tx.clone();

        std::thread::Builder::new()
            .name("deckweaver-ws".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("Failed to create tokio runtime");

                rt.block_on(async move {
                    let (cmd_tx, mut cmd_rx) = mpsc::channel::<Command>(32);
                    *command_tx_holder.write() = Some(cmd_tx);

                    let url = format!("ws://{}:{}/api/websocket", DEFAULT_HOST, DEFAULT_PORT);
                    let command_id = AtomicU64::new(0);

                    while running.load(Ordering::SeqCst) {
                        // Try to connect
                        let ws = match connect_async(&url).await {
                            Ok((ws, _)) => ws,
                            Err(e) => {
                                tracing::warn!("WebSocket connection failed: {}", e);
                                tokio::time::sleep(RECONNECT_DELAY).await;
                                continue;
                            }
                        };

                        tracing::info!("Connected to PipeWeaver");
                        let (mut write, mut read) = ws.split();

                        // Request initial status
                        let initial_id = command_id.fetch_add(1, Ordering::SeqCst);
                        let initial_request = serde_json::json!({
                            "id": initial_id,
                            "data": "GetStatus"
                        });
                        if let Ok(json) = serde_json::to_string(&initial_request) {
                            use futures_util::SinkExt;
                            let _ = write.send(Message::Text(json.into())).await;
                        }

                        loop {
                            tokio::select! {
                                msg = read.next() => {
                                    match msg {
                                        Some(Ok(Message::Text(text))) => {
                                            handle_ws_message(&text, &status);
                                        }
                                        Some(Err(e)) => {
                                            tracing::warn!("WebSocket error: {}", e);
                                            break;
                                        }
                                        None => break,
                                        _ => {}
                                    }
                                }
                                cmd = cmd_rx.recv() => {
                                    if let Some(cmd) = cmd {
                                        let id = command_id.fetch_add(1, Ordering::SeqCst);
                                        if let Some(json) = build_command(&status, id, cmd) {
                                            use futures_util::SinkExt;
                                            if write.send(Message::Text(json.into())).await.is_err() {
                                                break;
                                            }
                                        }
                                    }
                                }
                            }

                            if !running.load(Ordering::SeqCst) {
                                break;
                            }
                        }

                        if running.load(Ordering::SeqCst) {
                            tokio::time::sleep(RECONNECT_DELAY).await;
                        }
                    }

                    *command_tx_holder.write() = None;
                });
            })
            .expect("Failed to spawn websocket thread");
    }

    fn start_meter_thread(&self) {
        let running = self.running.clone();
        let meter_data = self.meter_data.clone();

        std::thread::Builder::new()
            .name("deckweaver-meter".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("Failed to create tokio runtime");

                rt.block_on(async move {
                    let url = format!("ws://{}:{}/api/websocket/meter", DEFAULT_HOST, DEFAULT_PORT);
                    let mut last_update: HashMap<String, Instant> = HashMap::new();
                    let throttle = Duration::from_millis(33); // 30fps

                    while running.load(Ordering::SeqCst) {
                        let ws = match connect_async(&url).await {
                            Ok((ws, _)) => ws,
                            Err(_) => {
                                tokio::time::sleep(RECONNECT_DELAY).await;
                                continue;
                            }
                        };

                        let (_, mut read) = ws.split();
                        last_update.clear();

                        loop {
                            tokio::select! {
                                msg = read.next() => {
                                    match msg {
                                        Some(Ok(Message::Text(text))) => {
                                            if let Ok(data) = serde_json::from_str::<Value>(&text) {
                                                if let (Some(id), Some(percent)) = (
                                                    data.get("id").and_then(|v| v.as_str()),
                                                    data.get("percent").and_then(|v| v.as_u64()),
                                                ) {
                                                    let now = Instant::now();
                                                    let should_update = last_update
                                                        .get(id)
                                                        .map(|t| now.duration_since(*t) >= throttle)
                                                        .unwrap_or(true);

                                                    if should_update {
                                                        last_update.insert(id.to_string(), now);
                                                        meter_data.write().insert(id.to_string(), percent as u8);
                                                    }
                                                }
                                            }
                                        }
                                        Some(Err(_)) | None => break,
                                        _ => {}
                                    }
                                }
                                _ = tokio::time::sleep(Duration::from_millis(100)) => {
                                    if !running.load(Ordering::SeqCst) {
                                        break;
                                    }
                                }
                            }
                        }

                        if running.load(Ordering::SeqCst) {
                            tokio::time::sleep(RECONNECT_DELAY).await;
                        }
                    }
                });
            })
            .expect("Failed to spawn meter thread");
    }

    fn start_render_thread(&self) {
        let running = self.running.clone();
        let service_available = self.service_available.clone();
        let status = self.status.clone();
        let actions = self.actions.clone();
        let meter_data = self.meter_data.clone();
        let image_callbacks = self.image_callbacks.clone();
        let label_callbacks = self.label_callbacks.clone();

        std::thread::Builder::new()
            .name("deckweaver-render".into())
            .spawn(move || {
                let mut renderers = Renderers::new();

                while running.load(Ordering::SeqCst) {
                    let frame_start = Instant::now();
                    let available = service_available.load(Ordering::Relaxed) || status.read().is_some();

                    let mut label_updates = Vec::new();

                    // Update device info for all actions
                    {
                        let status_guard = status.read();
                        let meter_guard = meter_data.read();
                        let mut actions_guard = actions.write();

                        for (action_id, state) in actions_guard.iter_mut() {
                            let Some(device_id) = state.config.device_id.as_ref() else { continue };
                            if let Some(ref st) = *status_guard {
                                state.device = st.get_device(device_id, None);
                            }
                            if let Some(&meter) = meter_guard.get(device_id) {
                                state.set_meter(meter);
                            }
                            let new_label = state.device.as_ref().map(|d| d.name.as_str());
                            if state.label_changed(new_label) {
                                if let Some(name) = new_label {
                                    label_updates.push((action_id.clone(), name.to_string()));
                                }
                            }
                        }
                    }

                    // Send label updates
                    if !label_updates.is_empty() {
                        Python::attach(|py| {
                            let callbacks = label_callbacks.read();
                            for (id, label) in &label_updates {
                                if let Some(cb) = callbacks.get(id) {
                                    let _ = cb.clone_ref(py).call1(py, (label.as_str(),));
                                }
                            }
                        });
                    }

                    // Collect and render
                    let tasks: Vec<_> = {
                        let guard = actions.read();
                        guard.iter()
                            .filter(|(_, s)| s.needs_render())
                            .map(|(id, s)| (id.clone(), s.config.clone(), s.device.clone(), s.get_meter()))
                            .collect()
                    };

                    for (action_id, config, device, meter) in tasks {
                        let png = if !available {
                            renderers.render_unavailable(&config)
                        } else if let Some(ref dev) = device {
                            renderers.render(&config, dev, meter)
                        } else {
                            renderers.render_loading(&config)
                        };

                        if let Some(bytes) = png {
                            Python::attach(|py| {
                                if let Some(cb) = image_callbacks.read().get(&action_id).map(|c| c.clone_ref(py)) {
                                    let _ = cb.call1(py, (pyo3::types::PyBytes::new(py, &bytes),));
                                }
                            });
                        }
                    }

                    let elapsed = frame_start.elapsed();
                    if elapsed < RENDER_INTERVAL {
                        std::thread::sleep(RENDER_INTERVAL - elapsed);
                    }
                }
            })
            .expect("Failed to spawn render thread");
    }

    fn start_monitor_thread(&self) {
        let running = self.running.clone();
        let service_available = self.service_available.clone();

        std::thread::Builder::new()
            .name("deckweaver-monitor".into())
            .spawn(move || {
                use std::net::ToSocketAddrs;

                while running.load(Ordering::SeqCst) {
                    let addr_str = format!("{}:{}", DEFAULT_HOST, DEFAULT_PORT);
                    let available = addr_str
                        .to_socket_addrs()
                        .ok()
                        .and_then(|mut addrs| addrs.next())
                        .map(|addr| {
                            TcpStream::connect_timeout(&addr, Duration::from_secs(2)).is_ok()
                        })
                        .unwrap_or(false);

                    service_available.store(available, Ordering::Relaxed);
                    std::thread::sleep(SERVICE_CHECK_INTERVAL);
                }
            })
            .expect("Failed to spawn monitor thread");
    }
}

impl Drop for DeckWeaverCore {
    fn drop(&mut self) {
        self.stop();
    }
}

fn handle_ws_message(text: &str, status: &Arc<RwLock<Option<Status>>>) {
    let Ok(response) = serde_json::from_str::<Value>(text) else { return };

    if let Some(status_data) = response.get("data").and_then(|d| d.get("Status")) {
        if let Ok(new_status) = serde_json::from_value::<Status>(status_data.clone()) {
            *status.write() = Some(new_status);
        }
    }

    if let Some(patch) = response.get("data").and_then(|d| d.get("Patch")).and_then(|p| p.as_array()) {
        apply_patch(status, patch);
    }
}

fn apply_patch(status: &Arc<RwLock<Option<Status>>>, patch: &[Value]) {
    let mut guard = status.write();
    let Some(current) = guard.as_mut() else { return };
    let Ok(mut value) = serde_json::to_value(&*current) else { return };

    for op in patch {
        if let Err(e) = crate::client::apply_patch_op(&mut value, op) {
            tracing::warn!("Failed to apply patch: {}", e);
        }
    }
    if let Ok(new_status) = serde_json::from_value::<Status>(value) {
        *current = new_status;
    }
}

fn build_command(status: &Arc<RwLock<Option<Status>>>, id: u64, cmd: Command) -> Option<String> {
    let status_guard = status.read();
    let status = status_guard.as_ref()?;

    let data = match cmd {
        Command::SetVolume { device_id, volume } => {
            let device = status.get_device(&device_id, None)?;
            match device.device_type {
                DeviceType::Source => {
                    serde_json::json!({"Pipewire": {"SetSourceVolume": [device_id, "A", volume]}})
                }
                DeviceType::Target => {
                    serde_json::json!({"Pipewire": {"SetTargetVolume": [device_id, volume]}})
                }
            }
        }
        Command::SetVolumeRelative { device_id, delta } => {
            let device = status.get_device(&device_id, None)?;
            let new_volume = (device.volume as i16 + delta as i16).clamp(0, 100) as u8;
            match device.device_type {
                DeviceType::Source => {
                    serde_json::json!({"Pipewire": {"SetSourceVolume": [device_id, "A", new_volume]}})
                }
                DeviceType::Target => {
                    serde_json::json!({"Pipewire": {"SetTargetVolume": [device_id, new_volume]}})
                }
            }
        }
        Command::ToggleMute { device_id } => {
            let device = status.get_device(&device_id, None)?;
            match device.device_type {
                DeviceType::Source => {
                    if device.is_muted {
                        serde_json::json!({"Pipewire": {"DelSourceMuteTarget": [device_id, "TargetA"]}})
                    } else {
                        serde_json::json!({"Pipewire": {"AddSourceMuteTarget": [device_id, "TargetA"]}})
                    }
                }
                DeviceType::Target => {
                    let state = if device.is_muted { "Unmuted" } else { "Muted" };
                    serde_json::json!({"Pipewire": {"SetTargetMuteState": [device_id, state]}})
                }
            }
        }
    };

    let request = serde_json::json!({ "id": id, "data": data });
    serde_json::to_string(&request).ok()
}

struct Renderers {
    knob: KnobRenderer,
    sliders: HashMap<u32, SliderRenderer>,
    buttons: HashMap<u32, ButtonRenderer>,
}

impl Renderers {
    fn new() -> Self {
        Self {
            knob: KnobRenderer::new(200, 100),
            sliders: HashMap::new(),
            buttons: HashMap::new(),
        }
    }

    fn slider(&mut self, width: u32) -> &mut SliderRenderer {
        self.sliders.entry(width).or_insert_with(|| SliderRenderer::new(width))
    }

    fn button(&mut self, width: u32) -> &mut ButtonRenderer {
        self.buttons.entry(width).or_insert_with(|| ButtonRenderer::new(width))
    }

    fn render_unavailable(&mut self, config: &ActionConfig) -> Option<Vec<u8>> {
        match config.action_type {
            ActionType::Knob => self.knob.render_unavailable_internal(),
            ActionType::Slider => self.slider(config.width).render_unavailable_internal(),
            ActionType::Button => self.button(config.width).render_unavailable_internal(),
        }
    }

    fn render_loading(&mut self, config: &ActionConfig) -> Option<Vec<u8>> {
        match config.action_type {
            ActionType::Knob => self.knob.render_loading_internal(),
            ActionType::Slider => self.slider(config.width).render_loading_internal(),
            ActionType::Button => self.button(config.width).render_loading_internal(),
        }
    }

    fn render(&mut self, config: &ActionConfig, device: &Device, meter_value: u8) -> Option<Vec<u8>> {
        let is_source = device.device_type == DeviceType::Source;
        let color = device.color.as_ref().map(|c| (c.red, c.green, c.blue));

        match config.action_type {
            ActionType::Knob => {
                let params = RenderParams {
                    volume: device.volume,
                    is_muted: device.is_muted,
                    is_source,
                    meter_value,
                    device_color: color,
                    volume_bar_color: config.volume_bar_color,
                    meter_color: config.meter_color,
                    meter_invert: config.meter_invert,
                    meters_enabled: config.meters_enabled,
                };
                self.knob.render_internal_png(&params, config.icon_png.clone())
            }
            ActionType::Slider => {
                let params = RenderParams {
                    volume: device.volume,
                    is_muted: false,
                    is_source,
                    meter_value,
                    device_color: color,
                    volume_bar_color: config.volume_bar_color,
                    meter_color: config.meter_color,
                    meter_invert: config.meter_invert,
                    meters_enabled: config.meters_enabled,
                };
                self.slider(config.width).render_internal_png(&params, config.is_top, config.orientation == "horizontal")
            }
            ActionType::Button => {
                let is_plus = config.volume_step > 0;
                self.button(config.width).render_internal_png(is_plus, config.icon_png.clone())
            }
        }
    }
}
