//! DeckWeaver - Stream Deck plugin for PipeWeaver audio control
//!
//! This crate provides the core functionality for controlling PipeWeaver
//! virtual audio devices from a Stream Deck, exposed to Python via PyO3.

mod action;
mod client;
mod core;
mod devices;
mod icon_loader;
mod meter;
mod monitor;
mod render;

use pyo3::prelude::*;
use pyo3::types::PyModule;

pub use action::{ActionConfig, ActionType};
pub use client::PipeWeaverClient;
pub use core::DeckWeaverCore;
pub use devices::{Device, DeviceColor, DeviceType};
pub use icon_loader::load_icon_to_png;
pub use meter::MeterClient;
pub use monitor::ServiceMonitor;
pub use render::{ButtonRenderer, KnobRenderer, SliderRenderer};

/// Initialize the deckweaver Python module
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();

    // Core manager (new unified API)
    m.add_class::<DeckWeaverCore>()?;
    m.add_class::<ActionConfig>()?;
    m.add_class::<ActionType>()?;

    // Low-level classes (still available if needed)
    m.add_class::<PipeWeaverClient>()?;
    m.add_class::<MeterClient>()?;
    m.add_class::<ServiceMonitor>()?;
    m.add_class::<Device>()?;
    m.add_class::<DeviceColor>()?;
    m.add_class::<DeviceType>()?;
    m.add_class::<KnobRenderer>()?;
    m.add_class::<SliderRenderer>()?;
    m.add_class::<ButtonRenderer>()?;

    // Utility functions
    m.add_function(pyo3::wrap_pyfunction!(load_icon_to_png, m)?)?;

    // Constants
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    m.add("DEFAULT_PORT", 14565u16)?;

    Ok(())
}
