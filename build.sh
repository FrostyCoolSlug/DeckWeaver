#!/bin/bash
# Build script for DeckWeaver Rust extension module
# Builds the Rust code and copies the .so file to deckweaver/
#
# Usage: ./build.sh [clean|dev|release]
#   clean   - Clean build artifacts
#   dev     - Build in dev mode (debug symbols, fast compile)
#   release - Build in release mode (optimized, stripped, default)

set -e

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse command line argument
PROFILE="${1:-release}"

# Handle clean command
if [ "$PROFILE" = "clean" ]; then
    echo "Cleaning build artifacts..."
    cargo clean
    echo "Clean complete!"
    exit 0
fi

# Validate profile
if [ "$PROFILE" != "dev" ] && [ "$PROFILE" != "release" ]; then
    echo "Error: Invalid profile '$PROFILE'"
    echo "Usage: $0 [clean|dev|release]"
    exit 1
fi

# Set build flags and target directory based on profile
if [ "$PROFILE" = "release" ]; then
    CARGO_FLAGS="--release"
    TARGET_SUBDIR="release"
else
    CARGO_FLAGS=""
    TARGET_SUBDIR="debug"
fi

# Detect Python extension suffix
PYTHON_EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO'))")
TARGET_NAME="_core${PYTHON_EXT_SUFFIX}"
TARGET_DIR="deckweaver"
SOURCE_LIB="target/${TARGET_SUBDIR}/libdeckweaver.so"

echo "Building DeckWeaver Rust extension module..."
echo "Profile: $PROFILE"
echo "Target: ${TARGET_DIR}/${TARGET_NAME}"

# Build the Rust code
echo "Building Rust code..."
cargo build $CARGO_FLAGS

# Check if the source .so file exists
if [ ! -f "$SOURCE_LIB" ]; then
    echo "Error: $SOURCE_LIB not found after build!"
    exit 1
fi

# Create target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Delete the old .so file if it exists
if [ -f "$TARGET_DIR/$TARGET_NAME" ]; then
    echo "Removing old $TARGET_DIR/$TARGET_NAME"
    rm "$TARGET_DIR/$TARGET_NAME"
fi

# Copy the .so file to the target location with the correct name
echo "Copying $SOURCE_LIB -> $TARGET_DIR/$TARGET_NAME"
cp "$SOURCE_LIB" "$TARGET_DIR/$TARGET_NAME"

echo "Build complete! Extension module is at $TARGET_DIR/$TARGET_NAME"
