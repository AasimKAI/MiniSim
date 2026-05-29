# Collaborator Instructions

This repository contains the **Crypto Signal System v3** - a production trading system for Raspberry Pi. This document explains how to set up, collaborate, and maintain the system.

## Access & Permissions

### Repository Status
⚠️ **PRIVATE REPOSITORY** - Access restricted to authorized team members only.

### Who Has Access
- **Owner:** Aasim Karbhari (akarbhari@olceurope.com)
- **Collaborators:** Added on request
- **Non-collaborators:** No access

### Getting Access

If you need access:
1. Contact the owner (akarbhari@olceurope.com)
2. Provide:
   - Your GitHub username
   - Your role (developer, tester, operator, etc.)
   - Brief reason for access
3. Owner adds you as collaborator via GitHub Settings → Collaborators

---

## Cloning the Repository

### First Time Setup

```bash
# Clone (you must have access)
git clone https://github.com/AasimKAI/OLC.git
cd OLC

# Check out the main branch
git checkout main

# Or the latest development branch
git checkout claude/new-session-PGAxF
```

### Authentication

**SSH (Recommended):**
```bash
# Ensure SSH key is set up
ssh -T git@github.com
# Should print: Hi [username]! You've successfully authenticated...

# Clone with SSH
git clone git@github.com:AasimKAI/OLC.git
```

**HTTPS (Alternative):**
```bash
# Use personal access token (PAT) instead of password
# Create PAT: GitHub → Settings → Developer settings → Personal access tokens
# Scopes needed: repo, workflow

git clone https://[username]:[PAT]@github.com/AasimKAI/OLC.git
```

---

## Collaboration Workflow

### Branches

```
main                          ← Stable, production-ready
├── claude/new-session-*      ← Development branches (current work)
├── feature/*                 ← New features
└── bugfix/*                  ← Bug fixes
```

### Creating a Feature Branch

```bash
# Update main
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes, commit
git add .
git commit -m "Your commit message"

# Push
git push -u origin feature/your-feature-name
```

### Pull Requests

1. **Create PR on GitHub:**
   - Go to https://github.com/AasimKAI/OLC/pulls
   - Click "New Pull Request"
   - Base: `main`, Compare: `your-branch`
   - Fill in title and description
   - Click "Create Pull Request"

2. **Code Review:**
   - Owner reviews code
   - Request changes or approve
   - Address feedback with new commits

3. **Merge:**
   - Once approved, click "Merge pull request"
   - Delete branch after merge

### Commit Message Format

```
Brief summary (50 chars max)

Longer explanation if needed (wrap at 72 chars):
- Why this change
- What was fixed
- Any breaking changes

Related issues: #123
```

**Example:**
```
Fix concurrent position mutation race condition

Added threading.RLock() to protect self.positions dict
from simultaneous access by analysis and exit loops.

This prevents ghost exits and ensures correct position
state even under load.

Fixes: #5 (Critical bugs from code review)
```

---

## Development Setup

### Prerequisites

```bash
# Python 3.9+
python3 --version

# Virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows
```

### Install Dependencies

```bash
cd OLC
pip install -r requirements.txt
```

### Run Tests

```bash
python3 tests/run_tests.py

# Expected output:
# ======================================================================
# RESULTS: 23 passed, 0 failed
# ======================================================================
```

### Run Locally (Development)

```bash
# Test in fixture mode (no network)
python3 main.py

# Or set mode in config/config.py first
MODE = "fixture"
python3 main.py
```

---

## Important: Secrets & Credentials

### ⚠️ CRITICAL: Never Commit Secrets

**Files that MUST be gitignored:**
- `config/secrets.py` - API keys, passwords
- `.env` - Environment variables
- Any file containing credentials

**Verify before committing:**
```bash
# Check what's staged
git diff --cached | grep -i "api\|key\|secret\|token\|password"

# If any secrets found:
git reset HEAD <file>  # Unstage
# Edit file to remove secrets
git add <file>
git commit -m "Remove secrets (actual change here)"
```

### Using Template Files

```bash
# Copy template
cp config/secrets.example.py config/secrets.py

# Edit with YOUR keys
nano config/secrets.py

# Git will ignore this file (gitignore already set)
```

---

## Code Review Guidelines

### For Code Authors

1. **Before submitting PR:**
   - Run tests: `python3 tests/run_tests.py` (must pass)
   - Verify no secrets in code
   - Check README/docs are updated
   - Commit messages are clear

2. **When creating PR:**
   - Title is descriptive
   - Description explains "why" not "what"
   - Reference any related issues (#123)
   - Keep PR focused (one feature per PR)

### For Reviewers

1. **Check:**
   - Code is clear and testable
   - No secrets/credentials
   - Tests pass
   - Documentation updated
   - No unnecessary complexity

2. **Comment:**
   - Be specific (line numbers, quotes)
   - Suggest improvements
   - Ask questions if unclear

3. **Approve or Request Changes:**
   - Approve: ready to merge
   - Request changes: needs fixes

---

## Deployments

### To Binance Testnet (Pi)

See `DEPLOYMENT_PI.md` for full instructions.

**Quick version:**
```bash
scp -r ~/OLC pi@crypto-pi.local:~/
ssh pi@crypto-pi.local
cd ~/OLC
pip install -r requirements.txt
cp config/secrets.example.py config/secrets.py
# Edit secrets.py with Binance Testnet keys
python3 main.py
```

### Production Checklist Before Deployment

See `BEFORE_PI_DEPLOYMENT.md` for complete checklist.

---

## Monitoring & Support

### Daily Operations

```bash
# Check system running
ps aux | grep main.py

# View recent decisions
tail -20 data/decision_log.jsonl

# Check for errors
grep ERROR logs/crypto_signal.log | tail -10
```

### Reporting Issues

1. **Check existing issues:** https://github.com/AasimKAI/OLC/issues
2. **Create new issue:**
   - Title: Brief description
   - Description: Steps to reproduce, expected vs actual
   - Logs: Paste relevant error logs
   - Environment: Python version, OS, Pi model

3. **Format:**
```markdown
## Description
What's the problem?

## Steps to Reproduce
1. ...
2. ...

## Expected Behavior
What should happen?

## Actual Behavior
What actually happened?

## Logs
```
[paste error logs here]
```

## Environment
- Python: 3.11
- OS: Raspberry Pi OS Bookworm
- Crypto Signal System: v3.0
```

---

## Version Control Best Practices

### Do

✅ Pull before pushing
```bash
git pull origin main
git push origin feature-branch
```

✅ Create descriptive commits
```bash
git commit -m "Fix thesis-break exit order (before stop-loss)"
```

✅ Review changes before committing
```bash
git diff  # See unstaged changes
git diff --cached  # See staged changes
```

✅ Use feature branches
```bash
git checkout -b feature/new-analyst
```

### Don't

❌ Force push to main
```bash
git push -f origin main  # NEVER
```

❌ Commit secrets
```bash
# Check before committing
git diff --cached | grep -i "key\|secret\|token"
```

❌ Large binary files
```bash
# Don't commit large model files, datasets, backups
# Use .gitignore instead
```

❌ Merge without tests passing
```bash
# Always run tests first
python3 tests/run_tests.py  # Must pass
```

---

## Security Considerations

### API Keys

- **Binance Testnet keys:** Use TRADE-ONLY keys (no withdrawal permission)
- **Reddit/Twitter keys:** Restrict to read-only scopes
- **Telegram bot token:** Keep private, never share
- **Ollama:** Runs locally, no credentials needed

### Repository

- **Branch protection:** Main branch has review requirements
- **Secrets scanning:** GitHub scans for leaked credentials
- **Access control:** Only authorized collaborators can access

### Deployment

- **Testnet only:** Never use live Binance keys during development
- **Isolated environment:** Run on dedicated Pi with no other services
- **Backups:** Keep local backups of decision_log.jsonl and tax_ledger.jsonl

---

## Common Tasks

### Updating from Main

```bash
git fetch origin
git rebase origin/main
# or
git merge origin/main
```

### Viewing History

```bash
# See recent commits
git log --oneline -10

# See commits on your branch vs main
git log main..HEAD

# See what changed in a file
git log -p config/config.py
```

### Undoing Changes

```bash
# Unstage file
git reset HEAD <file>

# Discard local changes
git checkout -- <file>

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Undo last commit (discard changes)
git reset --hard HEAD~1
```

### Checking Status

```bash
# Overall status
git status

# What would be committed
git diff --cached

# What's not staged
git diff
```

---

## Questions or Issues?

1. **Technical questions:** Create an issue on GitHub
2. **Access problems:** Email owner
3. **Security concerns:** Email owner directly (don't post publicly)
4. **Feature requests:** Create issue with label `enhancement`

---

## Additional Resources

- **README.md** - Features, architecture, usage
- **DEPLOYMENT_PI.md** - Full Pi deployment guide
- **QUICK_START_PI.md** - 5-minute deployment summary
- **BEFORE_PI_DEPLOYMENT.md** - Pre-deployment checklist
- **Full Build Handoff** - Complete specification
