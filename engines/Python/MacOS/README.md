# MacOS Agent Engine

A small Python-based Switchbay engine for local MacOS assistance.

## Tools

- `status` — verify the engine is available
- `query` — summarize or inspect local MacOS context
- `open-app` — open an app, file, folder, or URL
- `run-script` — run a local shell or AppleScript snippet
- `defaults-get` — read a macOS preference value
- `defaults-set` — write a macOS preference value
- `notify` — show a local notification
- `clipboard-get` / `clipboard-set` — read or write clipboard contents
- `screenshot` — capture a screenshot to a file
- `finder_show` — safely reveal a user-space file or folder in Finder
- `finder_open` — safely open a user-space file or folder
- `finder_info` — safely inspect file or folder metadata
- `finder_reveal_parent` — reveal the parent folder for a user-space path

## Safety

- `run-script`, `defaults-set`, and `screenshot` are approval-gated in the template.
- Finder tools only allow paths under `~/`, `/Users/Shared`, or the repo CWD.
- Finder tools are read-only and do not rename, delete, or move files.
- Tool output is JSON for easy agent parsing.
- The script expects standard macOS CLI tools such as `open`, `defaults`, `osascript`, `pbcopy`, `pbpaste`, and `screencapture`.
