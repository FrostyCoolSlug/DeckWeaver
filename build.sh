#!/bin/bash
# Build script for DeckWeaver Rust extension module
# Builds the Rust code and copies the .so file to deckweaver/

set -e

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detect Python extension suffix
PYTHON_EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO'))")
TARGET_NAME="_core${PYTHON_EXT_SUFFIX}"
TARGET_DIR="deckweaver"
SOURCE_LIB="target/release/libdeckweaver.so"

echo "Building DeckWeaver Rust extension module..."
echo "Target: ${TARGET_DIR}/${TARGET_NAME}"

# Build the Rust code in release mode
echo "Building Rust code..."
cargo build --release

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
