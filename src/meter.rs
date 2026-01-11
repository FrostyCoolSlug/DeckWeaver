//! WebSocket client for PipeWeaver audio meter data

use futures_util::StreamExt;
use parking_lot::RwLock;
use pyo3::prelude::*;
use serde::Deserialize;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::watch;
use tokio_tungstenite::{connect_async, tungstenite::Message};

const DEFAULT_HOST: &str = "localhost";
const DEFAULT_PORT: u16 = 14565;
const RECONNECT_DELAY: Duration = Duration::from_secs(5);
const METER_THROTTLE: Duration = Duration::from_millis(33);

#[derive(Debug, Deserialize)]
struct MeterData { id: String, percent: u8 }

#[pyclass]
pub struct MeterClient {
    host: String,
    port: u16,
    running: Arc<AtomicBool>,
    callbacks: Arc<RwLock<Vec<Py<PyAny>>>>,
    shutdown_tx: Option<watch::Sender<bool>>,
}

#[pymethods]
impl MeterClient {
    #[new]
    #[pyo3(signature = (host=None, port=None))]
    pub fn new(host: Option<&str>, port: Option<u16>) -> Self {
        Self {
            host: host.unwrap_or(DEFAULT_HOST).to_string(),
            port: port.unwrap_or(DEFAULT_PORT),
            running: Arc::new(AtomicBool::new(false)),
            callbacks: Arc::new(RwLock::new(Vec::new())),
            shutdown_tx: None,
        }
    }

    pub fn start(&mut self) {
        if self.running.swap(true, Ordering::SeqCst) {
            return;
        }

        let (shutdown_tx, mut shutdown_rx) = watch::channel(false);
        self.shutdown_tx = Some(shutdown_tx);

        let host = self.host.clone();
        let port = self.port;
        let running = self.running.clone();
        let callbacks = self.callbacks.clone();

        std::thread::Builder::new()
            .name("pipeweaver-meter".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("Failed to create tokio runtime");

                rt.block_on(async move {
                    let url = format!("ws://{}:{}/api/websocket/meter", host, port);
                    let mut last_updates: HashMap<String, Instant> = HashMap::new();

                    while running.load(Ordering::SeqCst) {
                        let ws = match connect_async(&url).await {
                            Ok((ws, _)) => ws,
                            Err(e) => {
                                tracing::warn!("Meter WebSocket connection failed: {}", e);
                                tokio::select! {
                                    _ = tokio::time::sleep(RECONNECT_DELAY) => continue,
                                    _ = shutdown_rx.changed() => break,
                                }
                            }
                        };

                        tracing::debug!("Meter client connected");
                        let (_, mut read) = ws.split();
                        last_updates.clear();

                        loop {
                            tokio::select! {
                                msg = read.next() => {
                                    match msg {
                                        Some(Ok(Message::Text(text))) => {
                                            if let Ok(meter) = serde_json::from_str::<MeterData>(&text) {
                                                let now = Instant::now();
                                                let should_notify = last_updates
                                                    .get(&meter.id)
                                                    .map(|t| now.duration_since(*t) >= METER_THROTTLE)
                                                    .unwrap_or(true);
                                                if should_notify {
                                                    last_updates.insert(meter.id.clone(), now);
                                                    notify_meter_callbacks(&callbacks, &meter.id, meter.percent);
                                                }
                                            }
                                        }
                                        Some(Err(e)) => { tracing::warn!("Meter WebSocket error: {}", e); break; }
                                        None => break,
                                        _ => {}
                                    }
                                }
                                _ = shutdown_rx.changed() => {
                                    if *shutdown_rx.borrow() {
                                        running.store(false, Ordering::SeqCst);
                                        break;
                                    }
                                }
                            }
                        }

                        if running.load(Ordering::SeqCst) {
                            tokio::select! {
                                _ = tokio::time::sleep(RECONNECT_DELAY) => {}
                                _ = shutdown_rx.changed() => {}
                            }
                        }
                    }
                });
            })
            .expect("Failed to spawn meter thread");
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(true);
        }
    }

    fn add_callback(&self, callback: Py<PyAny>) {
        self.callbacks.write().push(callback);
    }

    fn remove_callback(&self, _py: Python<'_>, callback: Py<PyAny>) {
        self.callbacks.write().retain(|c| !c.is(&callback));
    }
}

impl Drop for MeterClient {
    fn drop(&mut self) {
        self.stop();
    }
}

fn notify_meter_callbacks(callbacks: &Arc<RwLock<Vec<Py<PyAny>>>>, device_id: &str, percent: u8) {
    Python::attach(|py| {
        let cbs: Vec<_> = callbacks.read().iter().map(|c| c.clone_ref(py)).collect();
        for cb in &cbs {
            if let Err(e) = cb.call1(py, (device_id, percent)) {
                tracing::error!("Error in meter callback: {}", e);
            }
        }
    });
}
