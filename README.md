# omarchy-restore

A safe, theme-aware terminal UI for creating and restoring a `home.tar.xz`
backup of your Omarchy home directory — themes, configs, dotfiles, and all your
personal data — onto a fresh [Omarchy](https://omarchy.org/) install.

> **Important**: omarchy-restore runs entirely as the current user. It only
> reads and writes inside your home directory (default `$HOME`). It never uses
> `sudo` and never touches system paths (`/etc`, `/usr`, `/var`, etc.).

## Table of contents

- [Why this tool](#why-this-tool)
- [Features](#features)
- [Install](#install)
- [Usage](#usage)
  - [Restore mode](#restore-mode)
  - [Backup mode](#backup-mode)
  - [Non-interactive report](#non-interactive-report)
- [The TUI screens](#the-tui-screens)
  - [1. Welcome (restore)](#1-welcome-restore)
  - [2. Preview (restore)](#2-preview-restore)
  - [3. Diff](#3-diff)
  - [4. Confirm (restore)](#4-confirm-restore)
  - [5. Progress](#5-progress)
  - [6. Done (restore)](#6-done-restore)
  - [Backup screens](#backup-screens)
    - [Backup Welcome](#backup-welcome)
    - [Backup Preview](#backup-preview)
    - [Backup Confirm](#backup-confirm)
    - [Backup Progress](#backup-progress)
    - [Backup Done](#backup-done)
- [File categorization](#file-categorization)
- [Safety guarantees](#safety-guarantees)
- [Safe extraction details](#safe-extraction-details)
- [Theme integration](#theme-integration)
  - [Palette derivation](#palette-derivation)
  - [Using `--no-theme`](#using---no-theme)
  - [Checking the resolved palette](#checking-the-resolved-palette)
- [Post-restore component reload](#post-restore-component-reload)
- [Development](#development)
- [Project structure](#project-structure)
- [License](#license)

---

## Why this tool

Restoring a `tar.xz` backup by hand is risky. A home-directory archive contains
thousands of files spread across configs, caches, secrets, and personal data.
Unpacking it blindly can:

- Overwrite new config files you want to keep on the fresh install.
- Write files into the wrong place.
- Restore machine-specific settings (display config, Bluetooth, audio) that
  differ on the new machine.
- Leave files owned by a stale UID.
- Unpack a caching directory that should just rebuild itself.

omarchy-restore gives you complete control:

1. It **previews** every file in the archive.
2. It **diffs** each file against what's already on disk, flagging new files,
   unchanged files, and overwrites.
3. It **categorizes** files so you can review by type (Omarchy config, secrets,
   caches, personal data, etc.).
4. It **safely extracts** via temp-file + fsync + atomic rename, so a power
   failure mid-restore never leaves a half-written file.
5. It **offers to reload** Omarchy components that were touched.

## Features

- **Dry-run preview** — inspect the archive before touching anything.
- **Diff against existing home** — every file is marked `+ NEW`, `~ OVR`,
  `= SAME`, `* DIR`, or `! REJECT` with the reason.
- **Selective restore** — toggle any file or category on or off in the TUI.
- **Omarchy-aware categorization** — files are sorted into 9 categories
  (see [table below](#file-categorization)), each with sensible defaults.
- **Backup creation** — scan your home folder, review by Omarchy category, and
  create a timestamped compressed `tar.xz` archive with sensible defaults.
- **Safety guarantees** — refuses to write anything that escapes the target
  directory, refuses unsafe symlinks/hardlinks, writes via temp+fsync+rename.
- **Theme-aware aesthetic** — automatically picks up the active Omarchy
  theme's palette, falling back to a neutral warm-monochrome look.
- **Reload Omarchy components** after restore — offers to reload Hyprland,
  restart Waybar / terminal / Walker, and re-apply the restored theme.
- **Streaming sha256 content comparison** — files with matching sizes are
  compared by content hash; identical files are skipped (not rewritten).

## Install

```bash
# Using uv (recommended)
uv tool install .

# Using pipx
pipx install .
```

The tool is published as a single Python package. After install the
`omarchy-restore` command is available on your `PATH`.

## Usage

### Restore mode

```bash
omarchy-restore restore /path/to/home.tar.xz
```

Opens the interactive TUI. Walk through the restore screens (Welcome → Preview →
Diff → Confirm → Progress → Done) to inspect, select, and restore your backup.

For backward compatibility, `omarchy-restore /path/to/home.tar.xz` (without the
`restore` subcommand) also works and defaults to restore mode.

### Backup mode

```bash
omarchy-restore backup [source]
```

Scans a source directory (default `$HOME`) and opens the TUI to review and
create a compressed `tar.xz` archive. Output defaults to a timestamped file
like `~/omarchy-backup-20260718-143022.tar.xz`.

Both modes accept `--dry-run` to preview without writing, `--yes` to skip the
TUI, and `--theme` / `--no-theme` to control theming.

### CLI flags

```
# Restore
omarchy-restore restore [archive.tar.xz]
  [--target DIR]                          target directory (default: $HOME)
  [--dry-run]                             preview and exit (no writes)
  [--diff-only]                           print diff report as plain text, exit
  [--yes]                                 skip confirmation (use with care)
  [--theme NAME]                          load a specific Omarchy theme by name
  [--no-theme]                            force the monochrome fallback palette
  [--watch-theme]                         re-read the Omarchy theme every 2 s
  [--keep-capabilities]                   preserve setuid/setgid/sticky bits
  [--no-color]                            disable ANSI color in --diff-only output

# Backup
omarchy-restore backup [source]
  [--output, -o FILE]                     output archive path (default: timestamped)
  [--dry-run]                             scan and print summary, no archive
  [--yes]                                 skip confirmation, create immediately

# Global
omarchy-restore --print-theme             print the resolved theme palette, exit
```

### Non-interactive report

```bash
# Print the full diff as plain text (useful for scripts)
omarchy-restore /path/to/home.tar.xz --diff-only

# Scan a directory without creating an archive
omarchy-restore backup ~/Documents --dry-run

# Print just the resolved theme palette
omarchy-restore --print-theme
```

#### Backup `--dry-run` output:

```
Source:  /home/user
Output:  /home/user/omarchy-backup-20260718-143022.tar.xz

Included files:  1234
Included bytes:  2.3 GB
Excluded:        567
Total scanned:   1801

By category:
  ·: 1120
  S:   45
  O:    3
  H:    8
  K:   12
  M:    6
  A:  567   (excluded)
```

Example `--diff-only` output:

```
+ NEW    · Documents/notes.txt
+ NEW    · Documents/todo.md
+ NEW    H .bashrc
+ NEW    K .ssh/id_ed25519
+ NEW    O .config/omarchy/themes/my-custom/theme.json
+ NEW    S .config/hypr/hyprland.conf
  NEW    A .cache/thumbnails/big.jpg
+ NEW    M .config/pulse/default.pa

7 new  0 overwrite  0 unchanged  0 rejected  7 total  1024 bytes to write
```

The `+` prefix marks files that will be written (included by their category).
The ` ` prefix marks files excluded by default (app-state / caches). The
single-letter column is the category chip.

## The TUI screens

### 1. Welcome (restore)

Enter the path to your `home.tar.xz` archive and the target directory (defaults
to `$HOME`). The tool validates that the archive is readable and that the
target is not a system path before proceeding.

### 2. Preview (restore)

Shows a summary of the archive:

```
Members:    1423
Files:      1130
Dirs:        212
Symlinks:     81
Uncompressed: 2.3 GB

Top-level entries:
  .bashrc
  .cache
  .config
  Documents
  Pictures
  ...
```

### 3. Diff

The core screen. Every member of the archive is shown in a table with columns:

| Column | Meaning |
|--------|---------|
| `INCL` | `+` if included, ` ` if excluded by default |
| `STATUS` | 4-character token (`+ NEW`, `~ OVR`, `= SAME`, `* DIR`, `! REJECT`) |
| `PATH` | Archive member name |
| `SIZE` | Uncompressed size in human-readable units |
| `Δ`    | Size difference vs the file on disk |
| `CAT`  | Category chip (`S`, `T`, `H`, `E`, `O`, `K`, `M`, `A`, `·`) |

**Controls:**

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate rows |
| `space` | Toggle include/exclude the selected row |
| `a` | Select all rows |
| `/` | Focus the table for keyboard navigation |
| `c` | Proceed to confirmation |
| `q` | Go back |
| Category buttons | Click a button (`ALL`, `O`, `S`, `T`, etc.) to filter the table to that category. Click again to clear the filter. |

Files that are `! REJECT` are unsafe and cannot be included (they have a
`reason` explaining why, e.g. "absolute member name: /etc/shadow").

### 4. Confirm (restore)

A final summary before writing:

```
Files to write:  850
  new:           720
  overwrite:     130
Skipped:        1010   (app-state / caches)
Total bytes:     450 MB

Top-level dirs:
  › .config
  › .ssh
  › Documents
  › Pictures

⚠ 3 secret files will be restored   (.ssh, .gnupg)
⚠ 2 machine-specific files will be restored   (.config/pulse)
```

Press `Y` to begin the restore. Press `q` or `esc` to go back to the Diff
screen.

### 5. Progress

A progress bar and a scrollable event log showing every step:

```
  ✓ Documents/notes.txt
  ✓ .bashrc
  ✓ .config/hypr/hyprland.conf
  ! .config/pulse/default.pa  [OSError: cannot create symlink]
  ✓ .ssh/id_ed25519

Restore complete
```

Press `q` to cancel mid-restore.

### 6. Done (restore)

Final summary and a checklist of Omarchy components that were touched:

```
Files written:  850
Total bytes:    450 MB

Reload Omarchy components:
  [ ]  Reload Hyprland
  [ ]  Restart Waybar
  [ ]  Restart terminal
  [ ]  Set theme: my-custom
```

Press `q` to exit.

### Backup screens

When run in backup mode (`omarchy-restore backup`), the TUI shows a different
set of screens tailored to creating an archive.

#### Backup Welcome

Enter the source directory (defaults to `$HOME`) and an output path. The tool
validates the source is readable and not a system path.

#### Backup Preview

After scanning the source, shows a summary:

```
Source:  /home/user
Output:  /home/user/omarchy-backup-20260718-143022.tar.xz

Included files:  1234
Included bytes:  2.3 GB
Excluded:        567

By category:
  S: 45  ·: 1120  O: 3  H: 8  K: 12  M: 6
```

Press `c` or click **Create backup** to proceed.

#### Backup Confirm

A final summary before creating the archive:

```
Source:    /home/user
Output:    /home/user/omarchy-backup-20260718-143022.tar.xz

Files:     1234
Bytes:     2.3 GB
Excluded:  567

  S: 45
  O: 3
  H: 8
  ...
```

Press `Y` to begin creating the archive.

#### Backup Progress

A progress bar and scrollable event log showing every file as it's archived:

```
  ✓ .bashrc
  ✓ .config/hypr/hyprland.conf
  ✓ .ssh/id_ed25519
  ✓ Documents/notes.txt
  - .cache/thumbnails/big.jpg  (excluded)

Backup complete
```

Press `q` to cancel mid-backup. The temp file is cleaned up automatically.

#### Backup Done

Final summary with the output archive path:

```
Archive: /home/user/omarchy-backup-20260718-143022.tar.xz
Files:   1234
Bytes:   2.3 GB
```

Press `q` to exit.

## File categorization

Every file in the archive is classified into one of 9 categories. The category
determines the default behavior (included or excluded) and whether a warning
is shown.

| Symbol | Category | Included by default | Warns | Examples |
|--------|----------|--------------------|-------|----------|
| `O` | omarchy-theme | Yes | No | `~/.config/omarchy/themes/my-custom/theme.json` |
| `S` | system-config | Yes | No | `~/.config/hypr/hyprland.conf`, `~/.config/waybar/config.jsonc` |
| `T` | terminal | Yes | No | `~/.config/alacritty/alacritty.toml`, `~/.config/kitty/kitty.conf` |
| `H` | shell | Yes | No | `~/.bashrc`, `~/.config/starship.toml` |
| `E` | editor/ide | Yes | No | `~/.config/nvim/init.lua`, `~/.config/Code/settings.json` |
| `K` | secrets | Yes | **Yes** | `~/.ssh/id_ed25519`, `~/.gnupg/`, `~/.password-store/` |
| `M` | machine-specific | Yes | **Yes** | `~/.config/pulse/`, `~/.config/bluetooth/`, `~/.config/gtk-3.0/` |
| `·` | user-data | Yes | No | `~/Documents/`, `~/Projects/`, `~/.cargo/` |
| `A` | app-state | **No** | No | `~/.cache/`, `~/.local/state/`, browser caches |

If a file doesn't match any specific rule it falls into `user-data` (the
catch-all), which is included by default — nothing is silently dropped.

## Safety guarantees

These checks are applied to every archive member **before** it is written.
Violations are shown as `! REJECT` in the diff table.

| Check | What happens |
|-------|-------------|
| Absolute member name | Rejected. Tar members like `/etc/shadow` are never written. |
| `..` component in path | Rejected. `home/user/../../etc/passwd` is refused. |
| Resolves outside target | Rejected. Verified via `os.path.realpath` + `os.path.commonpath`. |
| Symlink points outside target | Rejected if absolute (e.g. `/etc/shadow`) or uses `..` traversal. |
| Hardlink to outside target | Rejected. |
| Destination is a symlink to elsewhere | Refuse to follow; the write is blocked. |
| setuid / setgid / sticky bits | Stripped by default (`--keep-capabilities` to preserve). |
| Ownership mismatch | Files are written as the current user (no `sudo`, no stale UIDs). |
| `/`, `/etc`, `/usr`, `/var` as target | Refused by `resolve_target` at startup. |

## Safe extraction details

- **Regular files**: Written to a temporary file in the same parent directory
  (using `tempfile.mkstemp`), `fsync`'d, then atomically moved into place with
  `os.replace`. A power failure mid-write never leaves a half-written file at
  the destination.
- **Symlinks**: Recreated with `os.symlink` if the member passed the safety
  checks.
- **Hardlinks**: Recreated with `os.link`, pointing to the restored copy of
  the link target.
- **Directories**: Created with `os.makedirs(exist_ok=True)`.
- **FIFOs, devices**: Skipped with a logged warning.
- **Streaming sha256**: Files with matching size are compared by sha256 of
  their content. Identical files are not rewritten (avoids unnecessary inode
  churn on SSDs).

## Theme integration

The TUI automatically matches your current Omarchy theme. It reads the palette
from the active theme and applies it to the entire interface.

### Palette derivation

| Theme variable | Our mapping |
|----------------|-------------|
| `background` | `$bg` — app background |
| `foreground` | `$fg` — primary text |
| `cursor` | `$border-active` — focused panel border |
| `border` | `$border` — inactive dividers |

The background half of the scale (bg, bg_panel, bg_elevated, border) is always
monotonic in perceived brightness, regardless of the Omarchy theme's values.
The foreground half is allowed to vary.

If no Omarchy theme is active or the theme file can't be read, a warm
monochrome palette is used as fallback:
```
bg:        #1A1818
fg:        #F1ECEC
border:    #4B4646
accent:    #E8E2DD
```

### Using `--no-theme`

```bash
omarchy-restore /path/to/home.tar.xz --no-theme
```

Skips theme detection entirely and uses the monochrome fallback.

### Checking the resolved palette

```bash
omarchy-restore --print-theme
```

Prints every palette value as CSS variables and exits. Useful for debugging
theme integration or when customising the fallback.

### `--watch-theme`

If provided, the TUI polls `~/.config/omarchy/current/theme.json` every 2
seconds and re-applies if the file changes. Useful when iterating on a theme
in another terminal while the TUI is open.

## Post-restore component reload

After a successful restore, the Done screen offers a checklist of Omarchy
components that were touched. Each item can be selected individually. Items
only appear if their config directory was actually written:

| Component | Condition |
|-----------|-----------|
| `hyprctl reload` + `hyprctl configerrors` | `~/.config/hypr/**` was written |
| `omarchy restart waybar` | `~/.config/waybar/**` was written |
| `omarchy restart terminal` | Any of `alacritty/`, `foot/`, `kitty/`, `ghostty/` was written |
| `omarchy restart walker` | `~/.config/walker/**` was written |
| `omarchy theme set "<name>"` | A custom theme dir under `~/.config/omarchy/themes/` was written |

## Development

```bash
# Clone and enter the repo
git clone <repo-url> && cd tar_backup_tui

# Create a venv and install in editable mode
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run tests
.venv/bin/pytest

# Lint and type-check
.venv/bin/ruff check src/ tests/
.venv/bin/pyright src/ tests/
```

Build test fixtures for manual testing:

```bash
# Test restore flow
.venv/bin/python examples/make_fixture.py /tmp/test-fixture.tar.xz
.venv/bin/python -m omarchy_restore restore --diff-only /tmp/test-fixture.tar.xz --target /tmp/test-target

# Test backup flow
.venv/bin/python -m omarchy_restore backup /tmp/test-target --dry-run
.venv/bin/python -m omarchy_restore backup /tmp/test-target -o /tmp/test-backup.tar.xz --yes
```

## Project structure

```
src/omarchy_restore/
├── __init__.py
├── __main__.py          # CLI entry point (argparse)
├── archive.py           # tar.xz streaming
├── backup.py            # backup creation engine
├── diff.py              # archive-vs-disk comparison
├── omarchy.py           # path categorization (9 categories)
├── paths.py             # file-system safety checks
├── restore.py           # safe extraction worker
└── tui/
    ├── __init__.py
    ├── screens.py       # App root + all screens (restore + backup)
    └── theme.py         # Omarchy theme palette loader
tests/
├── test_app.py          # CLI, diff report, smoke tests
├── test_backup.py       # backup engine
├── test_diff.py         # diff engine
├── test_omarchy.py      # categorization
├── test_paths.py        # safety (most important tests)
├── test_restore.py      # extraction worker
└── test_theme.py        # palette derivation
examples/
└── make_fixture.py      # build a representative test archive
```

## License

MIT
