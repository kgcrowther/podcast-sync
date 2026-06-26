# Git Cheat Sheet — SwimSync Project
*A reference for good Git practice, written for solo developers learning team habits.*

---

## The Mental Model

Git manages three zones on your local machine, plus a fourth on GitHub:

```
[Files on disk]  →  [Staging area]  →  [Local commits]  →  [GitHub]
 "Working tree"      "Index"            "Local repo"        "Remote (origin)"
```

- **Working tree** — your actual files, as you edit them
- **Staging area** — files you've selected for your next commit (`git add`)
- **Local commits** — your saved history, stored on your Mac
- **GitHub (origin)** — the cloud copy; updated only when you push/pull

**Branches** are parallel timelines. `main` is always the stable version.
All new work happens on a branch, then gets merged back when it's ready.

**Commits** are save points. Each one captures the state of all tracked
files at that moment. You can always return to any commit.

---

## Why Each Command Exists

| Command | What it does |
|---|---|
| `git status` | Show what has changed since your last commit |
| `git checkout main` | Switch to the main timeline |
| `git pull origin main` | Download commits from GitHub that you don't have locally |
| `git checkout -b feature/name` | Create a new branch off your current position |
| `git checkout branch-name` | Switch to an existing branch |
| `git add filename` | Stage a specific file for the next commit |
| `git add .` | Stage ALL changed files (check `git status` first) |
| `git commit -m "message"` | Create a save point with a description |
| `git push origin branch-name` | Upload a branch and its commits to GitHub |
| `git merge branch-name` | Fold another branch's commits into your current branch |
| `git branch -d branch-name` | Delete a branch locally (safe — commits still exist) |
| `git push origin --delete branch-name` | Delete a branch from GitHub |
| `git log --oneline` | See a compact list of recent commits |
| `git diff` | See exactly what changed in your files since last commit |

---

## Branch Naming Conventions

| Prefix | Use for |
|---|---|
| `feature/` | New functionality (e.g. `feature/device-detection`) |
| `fix/` | Bug fixes (e.g. `fix/sync-file-size-comparison`) |
| `docs/` | Documentation changes (e.g. `docs/requirements-document`) |
| `refactor/` | Code restructuring without behavior change |

---

## Commit Message Format

**Pattern:** `verb + what changed`

Good examples:
- `Add device detection for SWIM PRO drive`
- `Fix file size comparison bug in sync logic`
- `Update requirements document with flow configuration`
- `Refactor RSS parser into separate module`

Bad examples:
- `stuff`
- `changes`
- `fix`
- `wip`

**Rule of thumb:** if you can't describe the commit in one sentence,
it probably contains too many changes — split it into smaller commits.

---

## Typical Workflows

---

### Workflow 1: Start and finish a new feature
*Use this whenever building something new — a new screen, a new function, a new module.*

```bash
# 1. Start from an up-to-date main
git checkout main
git pull origin main

# 2. Create your feature branch
git checkout -b feature/your-feature-name

# --- do your work, edit files ---

# 3. Check what changed
git status

# 4. Stage your changes
git add filename.py        # stage a specific file
# or
git add .                  # stage everything (check status first)

# 5. Commit with a clear message
git commit -m "Add your feature description here"

# 6. Repeat steps 3-5 as you make more progress
#    (commit often — small save points are better than one giant one)

# 7. When the feature is complete, push your branch to GitHub
git push origin feature/your-feature-name

# 8. Merge into main
git checkout main
git pull origin main       # in case anything changed while you were working
git merge feature/your-feature-name

# 9. Push updated main to GitHub
git push origin main

# 10. Clean up the branch
git branch -d feature/your-feature-name
git push origin --delete feature/your-feature-name
```

---

### Workflow 2: Fix a bug
*Same as Workflow 1 but with a fix/ prefix. Identical mechanics.*

```bash
git checkout main
git pull origin main
git checkout -b fix/description-of-bug

# --- fix the bug ---

git add .
git commit -m "Fix description of what was wrong and how you fixed it"
git push origin fix/description-of-bug

git checkout main
git pull origin main
git merge fix/description-of-bug
git push origin main

git branch -d fix/description-of-bug
git push origin --delete fix/description-of-bug
```

---

### Workflow 3: Update documentation
*For changes to .md files, requirements, comments, or README.*

```bash
git checkout main
git pull origin main
git checkout -b docs/what-you-are-documenting

# --- edit your docs ---

git add .
git commit -m "Update requirements document with sync workflow detail"
git push origin docs/what-you-are-documenting

git checkout main
git merge docs/what-you-are-documenting
git push origin main

git branch -d docs/what-you-are-documenting
git push origin --delete docs/what-you-are-documenting
```

---

### Workflow 4: Check what's going on (diagnostic)
*Use this when you're confused about the state of things.*

```bash
# What branch am I on? What has changed?
git status

# What does the recent history look like?
git log --oneline

# What exactly changed in my files?
git diff

# What branches exist locally?
git branch

# What branches exist on GitHub?
git branch -r
```

---

### Workflow 5: Undo something
*Various levels of "I made a mistake".*

```bash
# Undo changes to a file you haven't staged yet (restore to last commit)
git checkout -- filename.py

# Unstage a file you added but haven't committed yet
git restore --staged filename.py

# Undo your last commit but KEEP the changes in your files
git reset --soft HEAD~1

# See all commits and find one to go back to
git log --oneline
```

⚠️ Never use `git reset --hard` unless you are certain you want to
permanently discard changes. It cannot be undone.

---

## VS Code Shortcuts

| Action | Where in VS Code |
|---|---|
| See changed files | `Cmd+Shift+G` (Source Control panel) |
| Stage a file | Click `+` next to the file in Source Control |
| Commit | Type message in box → click `✓` |
| Push / Pull | `...` menu in Source Control panel |
| Switch branch | Click branch name in bottom-left corner |
| Open terminal | `` Ctrl+` `` |

---

## Quick Reference Card

```
START WORK:
  git checkout main
  git pull origin main
  git checkout -b feature/name

DURING WORK:
  git status
  git add filename (or git add .)
  git commit -m "clear description"

FINISH WORK:
  git push origin feature/name
  git checkout main
  git pull origin main
  git merge feature/name
  git push origin main
  git branch -d feature/name
  git push origin --delete feature/name

DIAGNOSTICS:
  git status
  git log --oneline
  git diff
  git branch
```

---

*Keep this file in your project root or print it out for your first few weeks.*
*The workflows become muscle memory faster than you expect.*
