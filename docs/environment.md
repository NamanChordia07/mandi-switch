# Build environment (checked 6 Nov 2026, 12:50 IST)

| Item | Found | Notes |
|---|---|---|
| OS | Windows 11 Home 10.0.26200, x64, 15.6 GB RAM | Home edition → Docker Desktop needs the WSL2 backend |
| Shell | PowerShell 5.1 + Git Bash | scripts provided as `.ps1` and `.sh` |
| Git | 2.55.0 | `git init` done; nothing committed |
| Python | 3.12.10 (`py -0` shows only 3.12) | venv at `.venv/` |
| uv | not installed | not needed; we use `python -m venv` + pip |
| Node / npm / pnpm | 24.20.0 / 11.19.0 / 9.15.9 | UI uses npm |
| Docker | **not installed** | Help #1 |
| WSL | **not installed** | Help #1 (`wsl --install --no-distribution`) |
| oras | not installed | only needed for the Compose path (not used) |
| OpenSSL | 3.5.7 | |
| winget | 1.29 | |
| Claude Code | 2.1.318, signed in | provider for the gate agents |
| Switch Console | not installed → installer downloaded (0.40.1) | `C:\Users\naman_8\Downloads\switch-console\` |
| Free ports | 3000, 5173, 8000, 8065, 8081, 8700 all free | Console picks its own ports |
| Disk | ~730 GB free | |

Project path contains a space (`switch hackathon`) — every script quotes paths.
