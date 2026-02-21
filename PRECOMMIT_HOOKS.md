# Pre-commit Security Hooks

This project uses [pre-commit](https://pre-commit.com/) hooks to detect secrets and enforce code quality standards before commits.

## 🔒 What's Protected

The pre-commit hooks check for:

- **Secrets & Credentials**: API keys, passwords, tokens, private keys
- **AWS Keys**: AWS access keys and secret keys
- **GitHub Tokens**: Personal access tokens, OAuth tokens
- **Private Keys**: SSH keys, SSL certificates
- **High Entropy Strings**: Base64/hex strings that might be secrets
- **Common Security Issues**: Using `bandit` for Python security

## 🚀 Quick Setup

Run the setup script:

```bash
./setup_precommit.sh
```

Or manually:

```bash
# Install pre-commit
pip install pre-commit

# Install the git hooks
pre-commit install

# Create baseline for existing files
detect-secrets scan --baseline .secrets.baseline
```

## 📝 Usage

### Automatic (Recommended)
Hooks run automatically when you commit:

```bash
git add .
git commit -m "Your message"
# Hooks run automatically here ✅
```

### Manual Run
Test all files before committing:

```bash
pre-commit run --all-files
```

Run on specific files:

```bash
pre-commit run --files path/to/file.py
```

### Bypass Hooks (Use Sparingly)
If you need to bypass hooks (NOT recommended):

```bash
git commit --no-verify -m "Message"
```

## 🔧 Configuration Files

- **`.pre-commit-config.yaml`** - Main configuration for all hooks
- **`.secrets.baseline`** - Baseline of known/approved "secrets" (false positives)
- **`pyproject.toml`** - Configuration for Python tools (black, bandit)

## 🛠️ Managing False Positives

If a legitimate value is flagged as a secret:

### Option 1: Update Baseline
```bash
detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline
```

### Option 2: Add Inline Comment
```python
api_key = "not-a-real-key"  # pragma: allowlist secret
```

### Option 3: Exclude in Config
Edit `.pre-commit-config.yaml` to exclude specific files or patterns.

## 📊 Hook Details

### detect-secrets
Scans for various types of secrets:
- AWS keys
- Azure tokens
- GitHub tokens
- Private keys
- JWT tokens
- High entropy strings
- Slack tokens
- ... and more

### bandit
Scans Python code for security issues:
- SQL injection risks
- Shell injection
- Hardcoded passwords
- Unsafe deserialization
- ... and more

### pre-commit-hooks
General file checks:
- Large file prevention (>10MB)
- No commits to main/master
- Trailing whitespace
- File encoding
- YAML/JSON syntax

### black
Python code formatter (optional):
- Enforces consistent style
- Line length: 88 characters

## 🔄 Updating Hooks

Keep hooks up to date:

```bash
pre-commit autoupdate
```

## 💡 Best Practices

1. **Never** commit real credentials
2. Use environment variables for secrets (`.env` files)
3. Use secret management tools (AWS Secrets Manager, HashiCorp Vault)
4. Keep `.secrets.baseline` updated and reviewed
5. Don't bypass hooks unless absolutely necessary
6. Review what hooks flag - they're there to help!

## 🆘 Troubleshooting

### Hook fails with false positive
```bash
# Update baseline
detect-secrets scan --baseline .secrets.baseline
```

### Need to skip a specific hook
```bash
SKIP=detect-secrets git commit -m "Message"
```

### Hooks not running
```bash
# Reinstall hooks
pre-commit install --install-hooks
```

## 📚 Resources

- [pre-commit documentation](https://pre-commit.com/)
- [detect-secrets documentation](https://github.com/Yelp/detect-secrets)
- [bandit documentation](https://bandit.readthedocs.io/)
