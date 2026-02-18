# How to Complete the Branch Merge

Thank you for your request to merge the master branches into main and clean up the repository structure.

## What This PR Provides

This PR includes tools and documentation to help you complete the branch consolidation:

1. **📄 BRANCH_MERGE_INSTRUCTIONS.md** - Detailed step-by-step manual instructions
2. **📄 MERGE_SUMMARY.md** - Overview of what was done and what's next
3. **⚙️ .github/workflows/merge-to-main.yml** - Automated GitHub Actions workflow
4. **🔧 scripts/merge-branches.sh** - Shell script for local execution

## Quick Start: Choose Your Method

### Method 1: GitHub Actions (Easiest) ⭐

1. **Merge this PR** into your current default branch
2. Go to the **Actions** tab in your GitHub repository
3. Click on **"Merge Master to Main"** workflow in the left sidebar
4. Click the **"Run workflow"** dropdown button
5. Select the branch and check **"Delete master branch after merge"** if you want to remove master
6. Click **"Run workflow"**
7. Wait for the workflow to complete (usually takes < 1 minute)

### Method 2: Local Script

```bash
# Clone or pull the latest changes
git pull origin copilot/merge-masters-into-main

# Run the script (with delete option)
./scripts/merge-branches.sh --delete-master

# Or without deleting master yet
./scripts/merge-branches.sh
```

### Method 3: Manual Steps

See `BRANCH_MERGE_INSTRUCTIONS.md` for detailed manual instructions.

## What Will Happen

**Before the merge:**
- `main` branch: Only initial commit (nearly empty)
- `master` branch: All your project code and files

**After the merge:**
- `main` branch: Contains all code from master (complete project)
- `master` branch: Can be safely deleted

## Important: Update Default Branch

After merging, make sure to set `main` as the default branch:

1. Go to **Settings** → **Branches**
2. Under **"Default branch"**, click the switch icon
3. Select **"main"**
4. Click **"Update"** and confirm

## Notify Your Team

After the merge, notify team members to update their local repositories:

```bash
git fetch --all --prune
git checkout main
git pull origin main
```

## Questions?

- See `BRANCH_MERGE_INSTRUCTIONS.md` for detailed instructions
- See `MERGE_SUMMARY.md` for a complete overview
- Open an issue if you encounter problems

---

**Note:** The actual merge was tested locally and works correctly. Due to GitHub permissions, you need to execute the final merge step using one of the methods above.
