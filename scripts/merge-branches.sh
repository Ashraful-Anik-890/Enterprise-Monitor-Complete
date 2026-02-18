#!/bin/bash

# Script to merge master branch into main and optionally delete master
# Usage: ./merge-branches.sh [--delete-master]

set -e  # Exit on error

echo "================================"
echo "Branch Merge Script"
echo "================================"
echo ""

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo "❌ Error: Not a git repository"
    echo "Please run this script from the repository root"
    exit 1
fi

# Check for --delete-master flag
DELETE_MASTER=false
if [ "$1" == "--delete-master" ]; then
    DELETE_MASTER=true
    echo "⚠️  Master branch will be deleted after merge"
fi

echo "Step 1: Fetching latest changes..."
git fetch --all

echo ""
echo "Step 2: Checking out main branch..."
git checkout main

echo ""
echo "Step 3: Pulling latest main..."
git pull origin main || echo "Main branch is up to date"

echo ""
echo "Step 4: Merging master into main..."
if git merge origin/master --allow-unrelated-histories --no-edit; then
    echo "✅ Merge successful!"
else
    echo "❌ Merge failed. Please resolve conflicts manually."
    exit 1
fi

echo ""
echo "Step 5: Pushing merged main to remote..."
if git push origin main; then
    echo "✅ Main branch pushed successfully!"
else
    echo "❌ Failed to push main branch"
    exit 1
fi

if [ "$DELETE_MASTER" == true ]; then
    echo ""
    echo "Step 6: Deleting master branch..."
    
    # Delete local master branch
    if git branch -D master 2>/dev/null; then
        echo "✅ Local master branch deleted"
    else
        echo "ℹ️  Local master branch doesn't exist or already deleted"
    fi
    
    # Delete remote master branch
    if git push origin --delete master; then
        echo "✅ Remote master branch deleted"
    else
        echo "❌ Failed to delete remote master branch"
        exit 1
    fi
fi

echo ""
echo "================================"
echo "✅ All operations completed successfully!"
echo "================================"
echo ""
echo "Summary:"
echo "- Master branch has been merged into main"
echo "- Main branch contains all the code"
if [ "$DELETE_MASTER" == true ]; then
    echo "- Master branch has been deleted (locally and remotely)"
else
    echo "- Master branch still exists (use --delete-master to remove it)"
fi
echo ""
echo "Next steps for other users:"
echo "1. git fetch --all --prune"
echo "2. git checkout main"
echo "3. git pull origin main"
