#!/bin/bash
#
# Agent Memory Installation Script
#
# Usage: ./install.sh [--dev] [--no-integrations]
#
# Options:
#   --dev              Install development dependencies
#   --no-integrations  Skip agent integration installation prompts
#

set -e

# Parse arguments
DEV_MODE=false
SKIP_INTEGRATIONS=false

for arg in "$@"; do
    case "$arg" in
        --dev)
            DEV_MODE=true
            ;;
        --no-integrations)
            SKIP_INTEGRATIONS=true
            ;;
    esac
done

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
if [ "$DEV_MODE" = true ]; then
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

# === Integration Installation Functions ===

install_opencode_integration() {
    local config_dir="$HOME/.config/opencode"
    local rules_dir="$config_dir/rules"
    local skills_dir="$config_dir/skills/agent-memory"
    local config_file="$config_dir/opencode.json"
    local rules_path="$rules_dir/agent-memory.md"
    
    echo "Installing OpenCode integration..."
    
    # Install rules file
    mkdir -p "$rules_dir"
    if [ -f "$rules_path" ]; then
        read -p "  Rules file exists. Overwrite? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp "$SCRIPT_DIR/integrations/opencode/rules/agent-memory.md" "$rules_path"
            echo "  Rules installed to $rules_path"
        else
            echo "  Skipping rules file."
        fi
    else
        cp "$SCRIPT_DIR/integrations/opencode/rules/agent-memory.md" "$rules_path"
        echo "  Rules installed to $rules_path"
    fi
    
    # Configure opencode.json to include the rules via instructions field
    # OpenCode doesn't auto-load from rules/ dir, so we need to add to instructions
    mkdir -p "$config_dir"
    if [ -f "$config_file" ]; then
        # Check if instructions already contains agent-memory
        if grep -q "agent-memory.md" "$config_file" 2>/dev/null; then
            echo "  opencode.json already references agent-memory.md"
        else
            echo "  Adding agent-memory to opencode.json instructions..."
            # Use Python to safely update JSON (preserves existing config)
            $PYTHON_CMD << PYEOF
import json
import os

config_file = "$config_file"
rules_path = "$rules_path"

try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    config = {}

# Add or update instructions array
if 'instructions' not in config:
    config['instructions'] = []

if rules_path not in config['instructions']:
    config['instructions'].append(rules_path)

# Ensure schema is present
if '\$schema' not in config:
    config['\$schema'] = 'https://opencode.ai/config.json'

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print(f"  Updated {config_file}")
PYEOF
        fi
    else
        # Create new opencode.json with instructions
        echo "  Creating opencode.json with instructions..."
        cat > "$config_file" << JSONEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "instructions": ["$rules_path"]
}
JSONEOF
        echo "  Created $config_file"
    fi
    
    # Install skill (on-demand full reference)
    mkdir -p "$skills_dir"
    if [ -f "$skills_dir/SKILL.md" ]; then
        read -p "  Skill file exists. Overwrite? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp "$SCRIPT_DIR/integrations/opencode/skills/agent-memory/SKILL.md" "$skills_dir/"
            echo "  Skill installed to $skills_dir/SKILL.md"
        else
            echo "  Skipping skill."
        fi
    else
        cp "$SCRIPT_DIR/integrations/opencode/skills/agent-memory/SKILL.md" "$skills_dir/"
        echo "  Skill installed to $skills_dir/SKILL.md"
    fi
    
    echo "  OpenCode integration complete."
    echo "    - Rules: configured in opencode.json instructions (auto-loaded)"
    echo "    - Skill: load with /skill agent-memory"
}

install_claude_code_integration() {
    local claude_dir="$HOME/.claude"
    local rules_dir="$claude_dir/rules"
    local skills_dir="$claude_dir/skills/agent-memory"
    local rules_path="$rules_dir/agent-memory.md"
    
    echo "Installing Claude Code integration..."
    
    # Install rules (auto-loaded from ~/.claude/rules/*.md)
    mkdir -p "$rules_dir"
    if [ -f "$rules_path" ]; then
        read -p "  Rules file exists. Overwrite? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp "$SCRIPT_DIR/integrations/claude-code/rules/agent-memory.md" "$rules_path"
            echo "  Rules installed to $rules_path"
        else
            echo "  Skipping rules."
        fi
    else
        cp "$SCRIPT_DIR/integrations/claude-code/rules/agent-memory.md" "$rules_path"
        echo "  Rules installed to $rules_path"
    fi
    
    # Install skill (on-demand full reference)
    mkdir -p "$skills_dir"
    if [ -f "$skills_dir/SKILL.md" ]; then
        read -p "  Skill file exists. Overwrite? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp "$SCRIPT_DIR/integrations/claude-code/skills/agent-memory/SKILL.md" "$skills_dir/"
            echo "  Skill installed to $skills_dir/SKILL.md"
        else
            echo "  Skipping skill."
        fi
    else
        cp "$SCRIPT_DIR/integrations/claude-code/skills/agent-memory/SKILL.md" "$skills_dir/"
        echo "  Skill installed to $skills_dir/SKILL.md"
    fi
    
    echo "  Claude Code integration complete."
    echo "    - Rules: ~/.claude/rules/ (auto-loaded every session)"
    echo "    - Skill: load with /agent-memory"
}

# === Agent Integrations ===

if [ "$SKIP_INTEGRATIONS" = false ]; then
    echo ""
    echo "Agent Integrations"
    echo "=================="
    echo ""
    read -p "Would you like to install agent integrations? [y/N] " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Select integrations to install:"
        echo "  [1] OpenCode    (rules + skill -> ~/.config/opencode/)"
        echo "  [2] Claude Code (rules + skill -> ~/.claude/)"
        echo "  [a] All"
        echo "  [n] None"
        echo ""
        read -p "Enter choice (1, 2, a, or n): " -r choice
        echo ""
        
        case "$choice" in
            1)
                install_opencode_integration
                ;;
            2)
                install_claude_code_integration
                ;;
            a|A)
                install_opencode_integration
                install_claude_code_integration
                ;;
            n|N|*)
                echo "  Skipping integrations."
                ;;
        esac
    fi
else
    echo ""
    echo "Skipping agent integrations (--no-integrations flag)."
fi

# Manual integration instructions
echo ""
echo "Manual Integration"
echo "=================="
echo ""
echo "If you skipped the automatic integration, you can install manually:"
echo ""
echo "OpenCode:"
echo "  # 1. Copy rules file"
echo "  mkdir -p ~/.config/opencode/rules"
echo "  cp $SCRIPT_DIR/integrations/opencode/rules/agent-memory.md ~/.config/opencode/rules/"
echo ""
echo "  # 2. Add to opencode.json instructions (REQUIRED - rules/ dir is not auto-loaded)"
echo "  # Edit ~/.config/opencode/opencode.json and add:"
echo '  #   "instructions": ["~/.config/opencode/rules/agent-memory.md"]'
echo ""
echo "  # 3. Copy skill (on-demand, load with /skill agent-memory)"
echo "  mkdir -p ~/.config/opencode/skills/agent-memory"
echo "  cp $SCRIPT_DIR/integrations/opencode/skills/agent-memory/SKILL.md ~/.config/opencode/skills/agent-memory/"
echo ""
echo "Claude Code:"
echo "  # 1. Copy rules (auto-loaded from ~/.claude/rules/)"
echo "  mkdir -p ~/.claude/rules"
echo "  cp $SCRIPT_DIR/integrations/claude-code/rules/agent-memory.md ~/.claude/rules/"
echo ""
echo "  # 2. Copy skill (on-demand, load with /agent-memory)"
echo "  mkdir -p ~/.claude/skills/agent-memory"
echo "  cp $SCRIPT_DIR/integrations/claude-code/skills/agent-memory/SKILL.md ~/.claude/skills/agent-memory/"
echo ""
