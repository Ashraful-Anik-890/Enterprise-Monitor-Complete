# GitHub Actions Workflows

This directory contains GitHub Actions workflows for repository automation.

## Available Workflows

### Merge Master to Main (`merge-to-main.yml`)

**Purpose:** Automates the process of merging the master branch into main and optionally deleting the master branch.

**Trigger:** Manual workflow dispatch (you trigger it manually from the Actions tab)

**Inputs:**
- `delete_master` (boolean): Whether to delete the master branch after merging

**How to Use:**
1. Go to the "Actions" tab in GitHub
2. Select "Merge Master to Main" from the workflow list
3. Click "Run workflow"
4. Choose whether to delete master after merge
5. Click "Run workflow" to start

**What It Does:**
1. Fetches all branches from the repository
2. Checks out the main branch
3. Merges master into main (allowing unrelated histories)
4. Pushes the merged main branch to GitHub
5. Optionally deletes the master branch (if selected)

**Permissions Required:**
- `contents: write` (to push and delete branches)

**When to Use:**
Use this workflow to consolidate your repository branches and transition from master to main as the primary branch.

## Future Workflows

Additional workflows can be added to this directory for:
- CI/CD pipelines
- Automated testing
- Code quality checks
- Deployment automation

## Learn More

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)
