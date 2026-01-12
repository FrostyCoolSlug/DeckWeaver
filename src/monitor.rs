//! Service monitor for checking PipeWeaver daemon availability

use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::watch;

const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 14565;
const CHECK_INTERVAL: Duration = Duration::from_secs(5);
const CONNECTION_TIMEOUT: Duration = Duration::from_secs(2);

#[pyclass]
pub struct ServiceMonitor {
    host: String,
    port: u16,
    running: Arc<AtomicBool>,
    available: Arc<AtomicBool>,
    callbacks: Arc<RwLock<Vec<Py<PyAny>>>>,
    shutdown_tx: Option<watch::Sender<bool>>,
}

#[pymethods]
impl ServiceMonitor {
    #[new]
    #[pyo3(signature = (host=None, port=None))]
    pub fn new(host: Option<&str>, port: Option<u16>) -> Self {
        Self {
            host: host.unwrap_or(DEFAULT_HOST).to_string(),
            port: port.unwrap_or(DEFAULT_PORT),
            running: Arc::new(AtomicBool::new(false)),
            available: Arc::new(AtomicBool::new(false)),
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
        let available = self.available.clone();
        let callbacks = self.callbacks.clone();

        std::thread::Builder::new()
            .name("pipeweaver-monitor".into())
            .spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_time()
                    .build()
                    .expect("Failed to create tokio runtime");

                rt.block_on(async move {
                    while running.load(Ordering::SeqCst) {
                        let was_available = available.load(Ordering::SeqCst);
                        let is_available = check_service(&host, port);

                        if was_available != is_available {
                            available.store(is_available, Ordering::SeqCst);
                            notify_callbacks(&callbacks, is_available);
                        }

                        tokio::select! {
                            _ = tokio::time::sleep(CHECK_INTERVAL) => {}
                            _ = shutdown_rx.changed() => {
                                if *shutdown_rx.borrow() {
                                    break;
                                }
                            }
                        }
                    }
                });
            })
            .expect("Failed to spawn monitor thread");
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(true);
        }
    }

    pub fn is_available(&self) -> bool {
        self.available.load(Ordering::SeqCst)
    }

    fn add_callback(&self, callback: Py<PyAny>) {
        self.callbacks.write().push(callback);
    }

    fn remove_callback(&self, _py: Python<'_>, callback: Py<PyAny>) {
        self.callbacks.write().retain(|c| !c.is(&callback));
    }
}

impl Drop for ServiceMonitor {
    fn drop(&mut self) {
        self.stop();
    }
}

fn check_service(host: &str, port: u16) -> bool {
    let addr = format!("{}:{}", host, port);
    addr.parse()
        .ok()
        .and_then(|addr| TcpStream::connect_timeout(&addr, CONNECTION_TIMEOUT).ok())
        .is_some()
}

fn notify_callbacks(callbacks: &Arc<RwLock<Vec<Py<PyAny>>>>, available: bool) {
    Python::attach(|py| {
        let cbs: Vec<_> = callbacks.read().iter().map(|c| c.clone_ref(py)).collect();
        for cb in &cbs {
            if let Err(e) = cb.call1(py, (available,)) {
                tracing::error!("Error in service state callback: {}", e);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_check_service_unavailable() {
        // Port that's unlikely to be in use
        assert!(!check_service("127.0.0.1", 59999));
    }
}
