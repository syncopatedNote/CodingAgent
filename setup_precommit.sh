#!/bin/bash
# Setup script for pre-commit hooks

set -e

echo "🔧 Setting up pre-commit hooks for credential detection..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "📦 Installing pre-commit..."
    pip install pre-commit
else
    echo "✅ pre-commit already installed"
fi

# Install the git hooks
echo "🪝 Installing git hooks..."
pre-commit install

# Generate baseline for existing secrets (if any)
echo "📊 Scanning existing codebase for secrets..."
if command -v detect-secrets &> /dev/null; then
    detect-secrets scan --baseline .secrets.baseline
    echo "✅ Baseline created/updated: .secrets.baseline"
else
    echo "⚠️  detect-secrets not found, installing..."
    pip install detect-secrets
    detect-secrets scan --baseline .secrets.baseline
fi

# Run pre-commit on all files to check current state
echo "🔍 Running pre-commit checks on all files..."
pre-commit run --all-files || {
    echo ""
    echo "⚠️  Some files failed pre-commit checks."
    echo "This is normal on first run. Fix the issues and commit again."
    exit 0
}

echo ""
echo "✅ Pre-commit hooks successfully installed!"
echo ""
echo "Usage:"
echo "  • Hooks run automatically on 'git commit'"
echo "  • Run manually: pre-commit run --all-files"
echo "  • Update hooks: pre-commit autoupdate"
echo "  • Skip hooks (NOT recommended): git commit --no-verify"
echo ""
echo "Configuration files:"
echo "  • .pre-commit-config.yaml - hook configuration"
echo "  • .secrets.baseline - baseline for existing secrets"
echo "  • pyproject.toml - Python tool configuration"
