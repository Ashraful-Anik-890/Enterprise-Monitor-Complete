# Scripts Directory

This directory contains utility scripts for repository management and project setup.

## Repository Management Scripts

### `merge-branches.sh`

**Purpose:** Merge master branch into main and optionally delete master

**Usage:**
```bash
# Basic merge (keeps master branch)
./scripts/merge-branches.sh

# Merge and delete master branch
./scripts/merge-branches.sh --delete-master
```

**What it does:**
1. Fetches latest changes from all branches
2. Checks out the main branch
3. Merges master into main (allowing unrelated histories)
4. Pushes the merged main branch to GitHub
5. Optionally deletes local and remote master branch

**Requirements:**
- Git installed
- Repository cloned locally
- Write access to the repository

## Project Setup Scripts

### `setup-macos.sh`

**Purpose:** Set up the development environment on macOS

**Usage:**
```bash
./scripts/setup-macos.sh
```

**What it does:**
- Installs required dependencies for macOS development
- Configures the backend-macos environment
- See the script file for detailed steps

### `setup-windows.bat`

**Purpose:** Set up the development environment on Windows

**Usage:**
```cmd
scripts\setup-windows.bat
```

**What it does:**
- Installs required dependencies for Windows development
- Configures the backend-windows environment
- See the script file for detailed steps

## Making Scripts Executable

On Unix-like systems (Linux/macOS), make scripts executable:

```bash
chmod +x scripts/*.sh
```

Windows batch files (`.bat`) are executable by default.

## Contributing

When adding new scripts:
1. Add them to this directory
2. Make them executable (Unix scripts)
3. Update this README with documentation
4. Include usage examples and requirements
