#!/bin/bash
# Build script for DeckWeaver Rust extension module
# Builds the Rust code and copies the .so file to deckweaver/
#
# Usage: ./build.sh [clean|dev|release|all]
#   clean   - Clean build artifacts
#   dev     - Build in dev mode (debug symbols, fast compile) for current Python
#   release - Build in release mode (optimized, stripped, default) for current Python
#   all     - Build for all Python versions (3.11, 3.12, 3.13, 3.14) in release mode

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check for required tools
check_requirements() {
    local missing=()
    
    if ! command -v cargo &> /dev/null 2>&1; then
        missing+=("cargo (install via rustup)")
    fi
    
    if ! command -v pyenv &> /dev/null 2>&1; then
        missing+=("pyenv (install via: sudo pacman -S pyenv or https://github.com/pyenv/pyenv)")
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Error: Missing required tools:"
        for tool in "${missing[@]}"; do
            echo "  - $tool"
        done
        exit 1
    fi
}

# Run requirement check (only for 'all' mode to avoid breaking single builds)
if [ "${1:-}" = "all" ]; then
    check_requirements
fi

# Python versions to build for
PYTHON_VERSIONS=("3.11" "3.12" "3.13" "3.14")

# Function to initialize pyenv
init_pyenv() {
    if [ -n "$PYENV_ROOT" ] && [ -f "$PYENV_ROOT/bin/pyenv" ]; then
        export PATH="$PYENV_ROOT/bin:$PATH"
    fi
    eval "$(pyenv init - bash 2>/dev/null || pyenv init -)" 2>/dev/null || true
}

# Function to install Python version using pyenv
install_python_pyenv() {
    local version=$1
    echo "Installing Python ${version} using pyenv..."
    
    init_pyenv
    
    # Check if a matching version is already installed (e.g., 3.12.12 for 3.12)
    local installed_version=$(pyenv versions --bare 2>/dev/null | grep "^${version}" | head -1)
    if [ -n "$installed_version" ]; then
        echo "Python ${installed_version} already installed via pyenv (matches ${version})"
        return 0
    fi
    
    # Install the latest patch version for this major.minor
    # pyenv will install the latest available (e.g., 3.12.12 for 3.12)
    echo "Installing Python ${version} (this may take a while)..."
    if pyenv install -s "${version}"; then
        echo "✓ Python ${version} installed successfully"
        return 0
    else
        echo "✗ Failed to install Python ${version} via pyenv"
        return 1
    fi
}

# Function to find Python executable for a version (pyenv only)
find_python() {
    local version=$1
    
    init_pyenv
    
    # Determine pyenv root
    local pyenv_root="${PYENV_ROOT:-$HOME/.pyenv}"
    if [ ! -d "$pyenv_root" ]; then
        pyenv_root=$(pyenv root 2>/dev/null || echo "$HOME/.pyenv")
    fi
    
    # Check if a version matching major.minor is installed via pyenv
    # pyenv might have 3.12.12 installed when we're looking for 3.12
    local pyenv_version=$(pyenv versions --bare 2>/dev/null | grep "^${version}" | head -1)
    if [ -n "$pyenv_version" ]; then
        # Construct the full path to the Python executable
        local pyenv_python="$pyenv_root/versions/${pyenv_version}/bin/python3"
        
        # Also try python (without the 3) in case that's what exists
        if [ ! -f "$pyenv_python" ]; then
            pyenv_python="$pyenv_root/versions/${pyenv_version}/bin/python"
        fi
        
        # Verify it exists and check version
        if [ -f "$pyenv_python" ] && [ -x "$pyenv_python" ]; then
            local detected_version=$("$pyenv_python" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
            if [ "$detected_version" = "$version" ]; then
                echo "$pyenv_python"
                return 0
            fi
        fi
    fi
    
    return 1
}

# Function to ensure Python version is available (install if needed)
ensure_python_version() {
    local version=$1
    
    # First check if it's already available
    if find_python "$version" > /dev/null 2>&1; then
        return 0
    fi
    
    echo "Python ${version} not found. Installing via pyenv..."
    
    if install_python_pyenv "$version"; then
        return 0
    fi
    
    echo "✗ Could not install Python ${version}"
    return 1
}

# Function to create venv for a Python version
setup_venv() {
    local version=$1
    local venv_dir=".venv-${version}"
    local python_cmd
    
    # Try to ensure Python version is available
    if ! python_cmd=$(find_python "$version"); then
        echo "Python ${version} not found. Attempting to install..."
        if ! ensure_python_version "$version"; then
            echo "Warning: Python ${version} not found and could not be installed, skipping..."
            return 1
        fi
        # Re-initialize pyenv after installation (in case a new version was installed)
        init_pyenv
        # Try again after installation
        if ! python_cmd=$(find_python "$version"); then
            echo "Warning: Python ${version} still not found after installation attempt, skipping..."
            return 1
        fi
    fi
    
    # Verify we have an absolute path (not just a command name)
    # If it's not an absolute path, try to resolve it
    if [ ! -f "$python_cmd" ]; then
        if command -v "$python_cmd" &> /dev/null 2>&1; then
            python_cmd=$(command -v "$python_cmd")
        else
            echo "Warning: Python command '$python_cmd' not found or not executable"
            return 1
        fi
    fi
    
    # Ensure it's executable
    if [ ! -x "$python_cmd" ]; then
        echo "Warning: Python executable '$python_cmd' is not executable"
        return 1
    fi
    
    echo "Setting up venv for Python ${version} using: $python_cmd"
    
    # Create venv if it doesn't exist
    if [ ! -d "$venv_dir" ]; then
        echo "Creating virtual environment: $venv_dir"
        "$python_cmd" -m venv "$venv_dir" || {
            echo "Error: Failed to create venv with $python_cmd"
            return 1
        }
    fi
    
    # Activate venv
    source "$venv_dir/bin/activate"
    
    # Ensure pip is up to date (needed for building)
    pip install -q --upgrade pip setuptools wheel
    
    echo "$venv_dir"
    return 0
}

# Function to build for a specific Python version
build_for_python() {
    local version=$1
    local profile=$2
    local venv_dir=".venv-${version}"
    local python_cmd
    
    echo ""
    echo "=========================================="
    echo "Building for Python ${version}"
    echo "=========================================="
    
    # Setup venv (this will install Python if needed)
    if ! setup_venv "$version"; then
        echo "✗ Failed to set up Python ${version}"
        return 1
    fi
    
    # Get the Python command after setup (it might have been installed)
    if ! python_cmd=$(find_python "$version"); then
        echo "✗ Python ${version} not available after setup"
        return 1
    fi
    
    # Activate venv
    source "$venv_dir/bin/activate"
    
    # Get Python extension suffix
    PYTHON_EXT_SUFFIX=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO'))")
    TARGET_NAME="_core${PYTHON_EXT_SUFFIX}"
    TARGET_DIR="deckweaver"
    
    # Set build flags
    if [ "$profile" = "release" ]; then
        CARGO_FLAGS="--release"
        TARGET_SUBDIR="release"
    else
        CARGO_FLAGS=""
        TARGET_SUBDIR="debug"
    fi
    
    SOURCE_LIB="target/${TARGET_SUBDIR}/libdeckweaver.so"
    
    echo "Python: $(python --version)"
    echo "Extension suffix: $PYTHON_EXT_SUFFIX"
    echo "Target: ${TARGET_DIR}/${TARGET_NAME}"
    
    # Build with cargo, using PYO3_PYTHON to specify the Python interpreter
    # This ensures pyo3 uses the correct Python version
    echo "Building Rust code with cargo (using Python ${version})..."
    PYO3_PYTHON="$python_cmd" cargo build $CARGO_FLAGS
    
    # Check if the source .so file exists
    if [ ! -f "$SOURCE_LIB" ]; then
        echo "Error: $SOURCE_LIB not found after build!"
        deactivate 2>/dev/null || true
        return 1
    fi
    
    # Create target directory if it doesn't exist
    mkdir -p "$TARGET_DIR"
    
    # Copy the .so file to the target location with the correct name
    echo "Copying $SOURCE_LIB -> $TARGET_DIR/$TARGET_NAME"
    cp "$SOURCE_LIB" "$TARGET_DIR/$TARGET_NAME"
    
    echo "✓ Built successfully for Python ${version}"
    
    # Deactivate venv (ignore errors - venv might not be active)
    deactivate 2>/dev/null || true
    
    # Clear any VIRTUAL_ENV that might be set
    unset VIRTUAL_ENV 2>/dev/null || true
    
    return 0
}

# Parse command line argument
PROFILE="${1:-release}"

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

# Handle "all" command - build for all Python versions
if [ "$PROFILE" = "all" ]; then
    echo "Building for all Python versions (3.11, 3.12, 3.13, 3.14)..."
    echo ""
    
    SUCCESS_COUNT=0
    FAIL_COUNT=0
    
    # Disable exit on error for the loop so we can continue building other versions
    set +e
    
    for version in "${PYTHON_VERSIONS[@]}"; do
        if build_for_python "$version" "release"; then
            ((SUCCESS_COUNT++)) || true
        else
            ((FAIL_COUNT++)) || true
        fi
    done
    
    # Re-enable exit on error for the rest of the script
    set -e
    
    echo ""
    echo "=========================================="
    echo "Build Summary"
    echo "=========================================="
    echo "Successful: $SUCCESS_COUNT"
    echo "Failed: $FAIL_COUNT"
    echo ""
    
    if [ $SUCCESS_COUNT -gt 0 ]; then
        echo "Built extension modules:"
        ls -lh deckweaver/_core*.so 2>/dev/null || echo "  (none found)"
    fi
    
    exit 0
fi

# Validate profile for single build
if [ "$PROFILE" != "dev" ] && [ "$PROFILE" != "release" ]; then
    echo "Error: Invalid profile '$PROFILE'"
    echo "Usage: $0 [clean|dev|release|all]"
    exit 1
fi

# Single build mode - use current Python or venv
set -e  # Enable exit on error for single build
echo "Building DeckWeaver Rust extension module (single build mode)..."
echo "Profile: $PROFILE"
echo ""

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Detect Python extension suffix
if [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
else
    PYTHON_CMD="python3"
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
echo "Using Python: $($PYTHON_CMD --version)"

PYTHON_EXT_SUFFIX=$($PYTHON_CMD -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO'))")
TARGET_NAME="_core${PYTHON_EXT_SUFFIX}"
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

# Build the Rust code
echo "Building Rust code..."
PYO3_PYTHON="$PYTHON_CMD" cargo build $CARGO_FLAGS

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

echo ""
echo "Build complete! Extension module is at $TARGET_DIR/$TARGET_NAME"
