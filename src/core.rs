use crate::action::{ActionConfig, ActionState, ActionType};
use crate::devices::{apply_patch_op, Device, DeviceType, Status};
use crate::render::{ButtonRenderer, KnobRenderer, RenderParams, SliderRenderer, pixmap_to_png};
use futures_util::{SinkExt, StreamExt};
use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use serde_json::Value;
use std::collections::HashMap;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tiny_skia::Pixmap;

const RENDER_INTERVAL: Duration = Duration::from_micros(33333);
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

#[derive(Debug, Clone)]
struct PendingUpdate {
    image: Option<Vec<u8>>,
    image_hash: Option<u64>,
    label: Option<String>,
    generation: u64,
}

#[pyclass]
pub struct DeckWeaverCore {
    running: Arc<AtomicBool>,
    service_available: Arc<AtomicBool>,
    status: Arc<RwLock<Option<Status>>>,
    actions: Arc<RwLock<HashMap<String, ActionState>>>,
    meter_data: Arc<RwLock<HashMap<String, u8>>>,
    command_tx: Arc<RwLock<Option<tokio::sync::mpsc::Sender<Command>>>>,
    pending_updates: Arc<RwLock<HashMap<String, PendingUpdate>>>,
    page_generation: Arc<AtomicU64>,
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
            command_tx: Arc::new(RwLock::new(None)),
            pending_updates: Arc::new(RwLock::new(HashMap::new())),
            page_generation: Arc::new(AtomicU64::new(0)),
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
        self.actions
            .write()
            .insert(config.action_id.clone(), ActionState::new(config));
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

    fn get_pending_updates<'a>(&self, py: Python<'a>) -> PyResult<Bound<'a, PyDict>> {
        let current_generation = self.page_generation.load(Ordering::SeqCst);
        let mut updates = self.pending_updates.write();
        
        let dict = PyDict::new(py);
        let to_remove: Vec<_> = updates
            .iter()
            .filter(|(_, update)| update.generation == current_generation)
            .map(|(id, _)| id.clone())
            .collect();
        
        for action_id in &to_remove {
            let Some(update) = updates.get(action_id) else { continue };
            let entry = PyDict::new(py);
            if let Some(bytes) = &update.image {
                entry.set_item("image", PyBytes::new(py, bytes))?;
            } else {
                entry.set_item("image", py.None())?;
            }
            if let Some(label) = &update.label {
                entry.set_item("label", label)?;
            } else {
                entry.set_item("label", py.None())?;
            }
            dict.set_item(action_id, entry)?;
        }
        
        for action_id in to_remove {
            updates.remove(&action_id);
        }
        
        Ok(dict)
    }

    fn is_available(&self) -> bool {
        self.service_available.load(Ordering::Relaxed) || self.status.read().is_some()
    }

    fn get_devices(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(Status::get_all_devices)
            .unwrap_or_default()
    }

    #[pyo3(name = "get_sources")]
    fn py_get_sources(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(Status::get_sources)
            .unwrap_or_default()
    }

    #[pyo3(name = "get_targets")]
    fn py_get_targets(&self) -> Vec<Device> {
        self.status
            .read()
            .as_ref()
            .map(Status::get_targets)
            .unwrap_or_default()
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
        self.actions
            .read()
            .get(action_id)
            .and_then(|s| s.device.as_ref())
            .map(|d| d.name.clone())
    }

    fn clear_all_actions(&self) {
        self.page_generation.fetch_add(1, Ordering::SeqCst);
        self.actions.write().clear();
        self.pending_updates.write().clear();
    }
}

impl DeckWeaverCore {
    fn send_command(&self, cmd: Command) -> bool {
        self.command_tx
            .read()
            .as_ref()
            .is_some_and(|tx| tx.blocking_send(cmd).is_ok())
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
                    let (cmd_tx, mut cmd_rx) = tokio::sync::mpsc::channel(32);
                    *command_tx_holder.write() = Some(cmd_tx);

                    let url = format!("ws://{}:{}/api/websocket", DEFAULT_HOST, DEFAULT_PORT);
                    let command_id = AtomicU64::new(0);

                    while running.load(Ordering::SeqCst) {
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

                        let initial_id = command_id.fetch_add(1, Ordering::SeqCst);
                        let initial_request = serde_json::json!({
                            "id": initial_id,
                            "data": "GetStatus"
                        });
                        if let Ok(json) = serde_json::to_string(&initial_request) {
                            if write.send(Message::Text(json.into())).await.is_err() {
                                break;
                            }
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
                                    let Some(cmd) = cmd else { continue };
                                    let id = command_id.fetch_add(1, Ordering::SeqCst);
                                    let Some(json) = build_command(&status, id, cmd) else { continue };
                                    if write.send(Message::Text(json.into())).await.is_err() {
                                        break;
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
        let actions = self.actions.clone();

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
                        let has_meters_enabled = {
                            let guard = actions.read();
                            guard.values().any(|s| s.config.meters_enabled)
                        };
                        
                        if !has_meters_enabled {
                            tokio::time::sleep(Duration::from_secs(1)).await;
                            continue;
                        }
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
                            let has_meters_enabled = {
                                let guard = actions.read();
                                guard.values().any(|s| s.config.meters_enabled)
                            };
                            
                            if !has_meters_enabled {
                                break;
                            }

                            tokio::select! {
                                msg = read.next() => {
                                    match msg {
                                        Some(Ok(Message::Text(text))) => {
                                            match serde_json::from_str::<Value>(&text) {
                                                Ok(data) => {
                                                    if let (Some(id), Some(percent)) = (
                                                        data.get("id").and_then(|v| v.as_str()),
                                                        data.get("percent").and_then(|v| v.as_u64()),
                                                    ) {
                                                        let device_needs_meters = {
                                                            let guard = actions.read();
                                                            guard.values().any(|s| {
                                                                s.config.meters_enabled &&
                                                                s.config.device_id.as_ref().map_or(false, |did| did == id)
                                                            })
                                                        };
                                                        
                                                        if device_needs_meters {
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
                                                Err(e) => {
                                                    tracing::warn!("Failed to parse meter message as JSON: {} (message: {})", e, text.chars().take(200).collect::<String>());
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
        let pending_updates = self.pending_updates.clone();
        let page_generation = self.page_generation.clone();

        std::thread::Builder::new()
            .name("deckweaver-render".into())
            .spawn(move || {
                let mut renderers = Renderers::new();
                let mut last_generation = 0u64;

                while running.load(Ordering::SeqCst) {
                    let frame_start = Instant::now();
                    let current_generation = page_generation.load(Ordering::SeqCst);
                    if current_generation != last_generation {
                        last_generation = current_generation;
                        std::thread::sleep(RENDER_INTERVAL);
                        continue;
                    }
                    last_generation = current_generation;

                    let available = service_available.load(Ordering::Relaxed) || status.read().is_some();
                    let mut label_updates = Vec::new();

                    let action_ids: Vec<String> = {
                        let guard = actions.read();
                        guard.keys().cloned().collect()
                    };

                    {
                        let status_guard = status.read();
                        let mut actions_guard = actions.write();

                        for action_id in action_ids {
                            let Some(state) = actions_guard.get_mut(&action_id) else { continue };
                            let Some(device_id) = state.config.device_id.as_ref() else { continue };
                            
                            if let Some(ref st) = *status_guard {
                                state.device = st.get_device(device_id, None);
                            }
                            
                            if state.config.meters_enabled {
                                let meter_guard = meter_data.read();
                                if let Some(&meter) = meter_guard.get(device_id) {
                                    state.set_meter(meter);
                                }
                            } else {
                                state.set_meter(0);
                            }
                            
                            if let Some(name) = state.device.as_ref().map(|d| d.name.as_str()) {
                                if state.label_changed(Some(name)) {
                                    label_updates.push((action_id, name.to_string()));
                                }
                            }
                        }
                    }

                    if !label_updates.is_empty() {
                        let mut updates = pending_updates.write();
                        for (action_id, label) in label_updates {
                            let should_update = updates
                                .get(&action_id)
                                .and_then(|u| u.label.as_ref())
                                .map_or(true, |existing| existing != &label);
                            
                            if should_update {
                                let update = updates.entry(action_id).or_insert_with(|| PendingUpdate {
                                    image: None,
                                    image_hash: None,
                                    label: None,
                                    generation: current_generation,
                                });
                                update.label = Some(label);
                                update.generation = current_generation;
                            }
                        }
                    }

                    let tasks: Vec<_> = {
                        let guard = actions.read();
                        guard.iter()
                            .filter(|(_, s)| s.needs_render())
                            .map(|(id, s)| {
                                let max_icon_size = match s.config.action_type {
                                    ActionType::Knob => 52.0,
                                    _ => (s.config.width as f32) * 0.5,
                                };
                                let cached_icon = s.get_cached_icon(
                                    s.config.icon_png.as_deref(),
                                    max_icon_size,
                                );
                                
                                let needs_base_rebuild = if (s.config.action_type == ActionType::Knob || s.config.action_type == ActionType::Slider) && s.config.meters_enabled {
                                    s.needs_base_rebuild()
                                } else {
                                    false
                                };
                                
                                let cached_base = if (s.config.action_type == ActionType::Knob || s.config.action_type == ActionType::Slider) && s.config.meters_enabled && !needs_base_rebuild {
                                    s.cached_base.read().clone()
                                } else {
                                    None
                                };
                                
                                (id.clone(), s.config.clone(), s.device.clone(), s.get_meter(), cached_icon, cached_base, needs_base_rebuild)
                            })
                            .collect()
                    };

                    for (action_id, config, device, meter, cached_icon, cached_base, needs_base_rebuild) in tasks {
                        if page_generation.load(Ordering::SeqCst) != current_generation {
                            break;
                        }

                        let cached_base = if needs_base_rebuild && (config.action_type == ActionType::Knob || config.action_type == ActionType::Slider) && config.meters_enabled {
                            if let Some(ref dev) = device {
                                let is_source = dev.device_type == DeviceType::Source;
                                let color = dev.color.as_ref().map(|c| (c.red, c.green, c.blue));
                                let params = RenderParams {
                                    volume: dev.volume,
                                    is_muted: dev.is_muted,
                                    is_source,
                                    meter_value: 0,
                                    device_color: color,
                                    volume_bar_color: config.volume_bar_color,
                                    meter_color: config.meter_color,
                                    meter_invert: config.meter_invert,
                                    meters_enabled: config.meters_enabled,
                                };
                                
                                let base_pixmap = match config.action_type {
                                    ActionType::Knob => {
                                        renderers.knob.render_base(&params, config.icon_png.clone(), cached_icon.as_ref())
                                    }
                                    ActionType::Slider => {
                                        renderers.slider(config.width).render_base(&params)
                                    }
                                    _ => None,
                                };
                                
                                if let Some(base_pixmap) = base_pixmap {
                                    let guard = actions.write();
                                    if let Some(state) = guard.get(&action_id) {
                                        let base_hash = state.base_hash();
                                        let cached = crate::action::CachedBaseRender {
                                            pixmap: base_pixmap.clone(),
                                            base_hash,
                                        };
                                        *state.cached_base.write() = Some(cached.clone());
                                        drop(guard);
                                        Some(cached)
                                    } else {
                                        drop(guard);
                                        None
                                    }
                                } else {
                                    None
                                }
                            } else {
                                None
                            }
                        } else {
                            cached_base
                        };

                        let png = if !available {
                            renderers.render_unavailable(&config)
                        } else if let Some(ref dev) = device {
                            renderers.render_with_cached(&config, dev, meter, cached_icon.as_ref(), cached_base.as_ref())
                        } else {
                            renderers.render_loading(&config)
                        };

                        if let Some(bytes) = png {
                            let mut hasher = DefaultHasher::new();
                            bytes.hash(&mut hasher);
                            let image_hash = hasher.finish();
                            
                            let mut updates = pending_updates.write();
                            let should_update = updates
                                .get(&action_id)
                                .and_then(|u| u.image_hash)
                                .map_or(true, |existing_hash| existing_hash != image_hash);
                            
                            if should_update {
                                let update = updates.entry(action_id).or_insert_with(|| PendingUpdate {
                                    image: None,
                                    image_hash: None,
                                    label: None,
                                    generation: current_generation,
                                });
                                update.image = Some(bytes);
                                update.image_hash = Some(image_hash);
                                update.generation = current_generation;
                            }
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
    let Ok(response) = serde_json::from_str::<Value>(text) else {
        let preview: String = text.chars().take(200).collect();
        tracing::warn!("Failed to parse WebSocket message as JSON (message: {})", preview);
        return;
    };

    if let Some(status_data) = response.get("data").and_then(|d| d.get("Status")) {
        if let Ok(new_status) = serde_json::from_value::<Status>(status_data.clone()) {
            let mut status_guard = status.write();
            if let Some(ref mut s) = *status_guard {
                s.rebuild_index();
            } else {
                let s = new_status;
                s.rebuild_index();
                *status_guard = Some(s);
            }
        } else {
            tracing::warn!("Failed to deserialize Status");
        }
    }

    if let Some(patch) = response
        .get("data")
        .and_then(|d| d.get("Patch"))
        .and_then(|p| p.as_array())
    {
        apply_patch(status, patch);
    }
}

fn apply_patch(status: &Arc<RwLock<Option<Status>>>, patch: &[Value]) {
    let mut guard = status.write();
    let Some(current) = guard.as_mut() else {
        tracing::warn!("Cannot apply patch: status is None");
        return;
    };
    
    let Ok(mut value) = serde_json::to_value(&*current) else {
        tracing::error!("Failed to serialize status for patch");
        return;
    };

    for op in patch {
        if let Err(e) = apply_patch_op(&mut value, op) {
            tracing::warn!("Failed to apply patch operation: {}", e);
        }
    }
    
    if let Ok(new_status) = serde_json::from_value::<Status>(value) {
        let s = new_status;
        s.rebuild_index();
        *current = s;
    } else {
        tracing::error!("Failed to deserialize status after patch");
    }
}

fn build_command(status: &Arc<RwLock<Option<Status>>>, id: u64, cmd: Command) -> Option<String> {
    let device = status
        .read()
        .as_ref()?
        .get_device(match &cmd {
            Command::SetVolume { device_id, .. } => device_id,
            Command::SetVolumeRelative { device_id, .. } => device_id,
            Command::ToggleMute { device_id } => device_id,
        }, None)?;

    let data = match cmd {
        Command::SetVolume { device_id, volume } => match device.device_type {
            DeviceType::Source => {
                serde_json::json!({"Pipewire": {"SetSourceVolume": [device_id, "A", volume]}})
            }
            DeviceType::Target => {
                serde_json::json!({"Pipewire": {"SetTargetVolume": [device_id, volume]}})
            }
        },
        Command::SetVolumeRelative { device_id, delta } => {
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
        Command::ToggleMute { device_id } => match device.device_type {
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
        },
    };

    serde_json::to_string(&serde_json::json!({ "id": id, "data": data })).ok()
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


    fn render_with_cached(&mut self, config: &ActionConfig, device: &Device, meter_value: u8, cached_icon: Option<&crate::action::CachedIcon>, cached_base: Option<&crate::action::CachedBaseRender>) -> Option<Vec<u8>> {
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
                if let Some(cached_base) = cached_base {
                    let mut pixmap = cached_base.pixmap.clone();
                    self.knob.render_meter_overlay(&mut pixmap, &params);
                    pixmap_to_png(&pixmap)
                } else if let Some(cached) = cached_icon {
                    self.knob.render_internal_png_with_cached(&params, Some(cached))
                } else {
                    self.knob.render_internal_png(&params, config.icon_png.clone())
                }
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
                if let Some(cached_base) = cached_base {
                    let mut full = cached_base.pixmap.clone();
                    self.slider(config.width).render_meter_overlay(&mut full, &params);
                    
                    let mut result = Pixmap::new(config.width, config.width)?;
                    let y_off = if config.is_top { 0 } else { config.width as usize };
                    let row_bytes = config.width as usize * 4;
                    
                    for y in 0..config.width as usize {
                        let src = (y + y_off) * row_bytes;
                        let dst = y * row_bytes;
                        result.data_mut()[dst..dst + row_bytes].copy_from_slice(&full.data()[src..src + row_bytes]);
                    }
                    
                    let is_horizontal = config.orientation == "horizontal";
                    if is_horizontal {
                        self.slider(config.width).rotate_cw(&result).and_then(|r| pixmap_to_png(&r))
                    } else {
                        pixmap_to_png(&result)
                    }
                } else {
                    self.slider(config.width).render_internal_png(&params, config.is_top, config.orientation == "horizontal")
                }
            }
            ActionType::Button => {
                let is_plus = if config.volume_step == 0 {
                    None
                } else if config.volume_step > 0 {
                    Some(true)
                } else {
                    Some(false)
                };
                if let Some(cached) = cached_icon {
                    self.button(config.width).render_internal_png_with_cached(is_plus, Some(cached), device.is_muted)
                } else {
                    self.button(config.width).render_internal_png(is_plus, config.icon_png.clone(), device.is_muted)
                }
            }
        }
    }
}
