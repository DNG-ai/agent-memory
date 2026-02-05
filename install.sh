#!/bin/bash
#
# Agent Memory Installation Script
#
# Usage: ./install.sh [--dev]
#
# Options:
#   --dev    Install development dependencies
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${AGENT_MEMORY_PATH:-$HOME/.agent-memory}"

echo "Agent Memory Installer"
echo "======================"
echo ""
echo "Repository: $SCRIPT_DIR"
echo "Install to: $INSTALL_DIR"
echo ""

# Check Python version
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python 3 is required but not found."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

# Check Python version is >= 3.10
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "Error: Python 3.10 or higher is required (found $PYTHON_VERSION)"
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/bin"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
$PYTHON_CMD -m venv "$INSTALL_DIR/venv"

# Activate and install
echo "Installing agent-memory..."
source "$INSTALL_DIR/venv/bin/activate"

# Upgrade pip
pip install --upgrade pip --quiet

# Install package
if [ "$1" == "--dev" ]; then
    pip install -e "$SCRIPT_DIR[dev]"
else
    pip install -e "$SCRIPT_DIR"
fi

# Create wrapper script
cat > "$INSTALL_DIR/bin/agent-memory" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
source "$INSTALL_DIR/venv/bin/activate"
exec python -m agent_memory.cli "$@"
EOF

chmod +x "$INSTALL_DIR/bin/agent-memory"

# Create activation script for shell integration
cat > "$INSTALL_DIR/bin/activate-memory" << EOF
#!/bin/bash
# Source this file to add agent-memory to your PATH
export AGENT_MEMORY_PATH="$INSTALL_DIR"
export PATH="\$AGENT_MEMORY_PATH/bin:\$PATH"
EOF

chmod +x "$INSTALL_DIR/bin/activate-memory"

# Initialize default config
echo ""
echo "Initializing configuration..."
"$INSTALL_DIR/bin/agent-memory" config show > /dev/null 2>&1 || true

echo ""
echo "Installation complete!"
echo ""
echo "To use agent-memory, either:"
echo ""
echo "  1. Add to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
echo "     export AGENT_MEMORY_PATH=\"$INSTALL_DIR\""
echo "     export PATH=\"\$AGENT_MEMORY_PATH/bin:\$PATH\""
echo ""
echo "  2. Or source the activation script:"
echo "     source $INSTALL_DIR/bin/activate-memory"
echo ""
echo "Then verify installation:"
echo "  agent-memory --version"
echo ""

# Integration instructions
echo "Integration with AI Agents:"
echo "============================"
echo ""
echo "OpenCode:"
echo "  Copy the skill to your OpenCode skills directory:"
echo "  cp -r $SCRIPT_DIR/integrations/opencode ~/.config/opencode/skills/agent-memory"
echo ""
echo "Claude Code:"
echo "  Add the CLAUDE.md content to your project's CLAUDE.md file:"
echo "  cat $SCRIPT_DIR/integrations/claude-code/CLAUDE.md"
echo ""
