# DeckWeaver

A Stream Deck plugin for controlling PipeWeaver virtual audio devices. Provides hardware control for volume and mute through your Stream Deck device.

## What is PipeWeaver?

PipeWeaver is a virtual audio routing system that allows you to create and manage virtual audio devices. This plugin gives you physical control over those virtual devices directly from your Stream Deck, enabling real-time audio management with visual feedback.

## Features

### Core Functionality
- **Volume Control**: Adjust audio levels with precise steps (5-20% per step, configurable)
- **Mute Toggle**: Quickly mute/unmute audio devices with visual feedback
- **Device Selection**: Control any available PipeWeaver virtual device (source or target)
- **Real-time Feedback**: Visual indicators show current audio levels, mute status, and device state
- **Service Monitoring**: Automatic detection of PipeWeaver daemon availability with visual status indicators

### Stream Deck Integration
- **Knob Support**: Full support for Stream Deck+ and Studio dials
  - Turn clockwise/counter-clockwise for volume up/down
  - Press to toggle mute
- **Visual Feedback**: Dynamic icons and volume bars show device status and audio levels
- **Real-time Metering**: Visual audio level meters for source and target devices

### Configuration
- **Multi-language Support**: English (en_US), Spanish (es_ES), Chinese (zh_CN), French (fr_FR), German (de_DE)
- **Custom Icons**: Use StreamController icon packs or custom SVG/PNG files
- **Adjustable Steps**: Configure volume step size (5-20%) per your preference
- **Meter Controls**: Enable/disable audio level meters, customize meter color, and invert meter color
- **Volume Bar Color**: Customize volume bar color or use device color
- **Persistent Settings**: Device selections and configurations are saved automatically

## Building (developers)

The Rust extension is built once and works on **any Python 3.11+** (abi3 / stable ABI). No need to match a specific minor version.

- **Option 1:** `./build.sh release` — builds and copies `deckweaver/_core.abi3.so` (requires Rust/cargo).
- **Option 2:** `pip install .` — builds the extension for the current Python (requires Rust and maturin).

**Version:** Set once in `Cargo.toml` (`[package] version`). The build script syncs it to `pyproject.toml` and `manifest.json`. The plugin uses it at runtime via the Rust extension.

## Requirements

- **StreamController**: 1.5.0-beta.12 or later
- **PipeWeaver**: Daemon running on localhost:14565
- **Stream Deck Device**: 
  - Stream Deck+ or Studio (recommended for full knob functionality)

## Installation

1. Install the plugin through StreamController's plugin manager
2. Ensure PipeWeaver daemon is running and accessible on `localhost:14565`
3. Configure your preferred devices and settings in the plugin configuration
4. Add the PipeWeaver action to your Stream Deck layout

## Usage

### Basic Controls
- **Turn dial clockwise**: Increase volume by configured step amount
- **Turn dial counter-clockwise**: Decrease volume by configured step amount
- **Press dial**: Toggle mute/unmute

### Configuration Options
- **Device Selection**: Choose audio device from available PipeWeaver devices (with refresh button)
- **Custom Icon**: Select custom icons from StreamController icon packs or custom SVG/PNG files
- **Volume Step**: Adjust volume step size (5-20% increments)
- **Meters Enabled**: Toggle audio level meter display on/off
- **Meter Color**: Customize meter color or invert volume bar color for meters
- **Volume Bar Color**: Override volume bar color or use device color automatically
- **Language**: Set interface language or use OS default (in plugin settings)

## Device Types

- **Source Devices**: Input virtual devices with volume and mute control
- **Target Devices**: Output virtual devices with direct volume and mute control

## Support

For issues related to:
- **Plugin functionality**: Create an issue on GitHub
- **PipeWeaver daemon**: Refer to PipeWeaver documentation
- **StreamController**: Check StreamController documentation and support channels
