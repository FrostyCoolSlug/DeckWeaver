#!/bin/bash
# Build script for DeckWeaver Rust extension module
# Builds the Rust code (abi3: one .so for Python 3.11+) and copies to deckweaver/
#
# Usage: ./build.sh [clean|dev|release] [--install|-i]
#   clean   - Clean build artifacts
#   dev     - Build in dev mode (debug symbols, fast compile)
#   release - Build in release mode (optimized, stripped, default)
#   --install, -i - After build, copy plugin to StreamController plugins folder
#
# Version-agnostic: the extension uses PyO3's abi3 (stable ABI), so a single
# build works on any Python 3.11+. No need for pyenv or multiple Python versions.
# Alternatively: pip install . (or maturin build) builds the same abi3 wheel.

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for required tools
if ! command -v cargo &> /dev/null 2>&1; then
    echo "Error: cargo not found (install via rustup)"
    exit 1
fi

# Sync version from Cargo.toml (single source of truth) to pyproject.toml and manifest.json
sync_version() {
    VERSION=$(awk -F'"' '/^version = / {print $2; exit}' Cargo.toml)
    if [ -n "$VERSION" ]; then
        sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
        sed -i "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" manifest.json
    fi
}
sync_version

# Parse command line arguments
PROFILE=""
INSTALL_PLUGIN=false
for arg in "$@"; do
    case "$arg" in
        --install|-i) INSTALL_PLUGIN=true ;;
        clean|dev|release) [ -z "$PROFILE" ] && PROFILE="$arg" ;;
        *) echo "Error: Unknown option '$arg'"; echo "Usage: $0 [clean|dev|release] [--install|-i]"; exit 1 ;;
    esac
done
[ -z "$PROFILE" ] && PROFILE="release"

# Handle clean command
if [ "$PROFILE" = "clean" ]; then
    set -e  # Enable exit on error for clean
    echo "Cleaning build artifacts..."
    cargo clean
    echo "Removing venvs..."
    rm -rf .venv-3.*
    echo "Removing compiled extension modules..."
    rm -f deckweaver/_core*.so
    echo "Clean complete!"
    exit 0
fi

# Validate profile
if [ "$PROFILE" != "dev" ] && [ "$PROFILE" != "release" ]; then
    echo "Error: Invalid profile '$PROFILE'"
    echo "Usage: $0 [clean|dev|release] [--install|-i]"
    exit 1
fi

# Single build mode (abi3: one .so for Python 3.11+)
set -e  # Enable exit on error for single build
echo "Building DeckWeaver Rust extension module (abi3, Python 3.11+)..."
echo "Profile: $PROFILE"
echo ""

TARGET_NAME="_core.abi3.so"
TARGET_DIR="deckweaver"

# Set build flags
if [ "$PROFILE" = "release" ]; then
    CARGO_FLAGS="--release"
    TARGET_SUBDIR="release"
else
    CARGO_FLAGS=""
    TARGET_SUBDIR="debug"
fi

SOURCE_LIB="target/${TARGET_SUBDIR}/libdeckweaver.so"

echo "Target: ${TARGET_DIR}/${TARGET_NAME}"
echo ""

# Build the Rust code (abi3 build does not require a Python interpreter)
echo "Building Rust code..."
cargo build $CARGO_FLAGS

# Check if the source .so file exists
if [ ! -f "$SOURCE_LIB" ]; then
    echo "Error: $SOURCE_LIB not found after build!"
    exit 1
fi

# Create target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Copy the .so file to the target location (abi3 name works on all Python 3.11+)
echo "Copying $SOURCE_LIB -> $TARGET_DIR/$TARGET_NAME"
cp "$SOURCE_LIB" "$TARGET_DIR/$TARGET_NAME"

# Copy plugin to StreamController plugins folder (only when --install or -i is passed)
PLUGIN_DEST="${DECKWEAVER_PLUGIN_DEST:-$HOME/.var/app/com.core447.StreamController/data/plugins/com_designgears_DeckWeaver}"
if [ "$INSTALL_PLUGIN" = true ] && [ -d "$(dirname "$PLUGIN_DEST")" ]; then
    echo "Copying plugin to StreamController..."
    rm -rf "$PLUGIN_DEST"
    mkdir -p "$PLUGIN_DEST"
    if command -v rsync &> /dev/null; then
        rsync -a \
            --exclude='.git' \
            --exclude='target' \
            --exclude='src' \
            --exclude='.venv*' \
            --exclude='build.sh' \
            --exclude='Cargo.toml' \
            --exclude='*.md' \
            --exclude='.gitignore' \
            "$SCRIPT_DIR/" "$PLUGIN_DEST/"
    else
        for f in main.py manifest.json attribution.json pyproject.toml; do [ -e "$f" ] && cp "$f" "$PLUGIN_DEST/"; done
        for d in deckweaver locales assets store; do [ -d "$d" ] && cp -r "$d" "$PLUGIN_DEST/"; done
    fi
    echo "Plugin installed at $PLUGIN_DEST"
else
    echo "Note: StreamController plugins dir not found, skipping install (path: $(dirname "$PLUGIN_DEST"))"
fi

echo ""
echo "Build complete! Extension module is at $TARGET_DIR/$TARGET_NAME"
