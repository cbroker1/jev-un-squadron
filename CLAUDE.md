# Project entry point

Read [CLAUDE_HANDOFF.md](docs/notes/CLAUDE_HANDOFF.md), then the current sections of [PROJECT_STATE.md](docs/notes/PROJECT_STATE.md) and [MEMORY_MAP.md](docs/notes/MEMORY_MAP.md). Historical sections contain disproved mappings; do not reuse them as current facts.

Layout (see README): Python in `src/` (run it from the repo root: `python src/run_segment.py ...`), tests in `tests/` (`python -m unittest discover -s tests -t tests`), double-click launchers in `launchers/`, Lua in `lua/`, measured maps in `data/`, captures and evidence reports in `evidence/`, notes in `docs/notes/`. `runs/`, `bizhawk/`, the key and the `runtime_*.json` IPC files stay at the repo root. Lua scripts use absolute paths under `C:\Users\Carl-MainRig\Projects\jev-un-squadron`.

- Carl wants autonomous, visible BizHawk tests without repeated manual Lua clicks.
- Use the installed TypeSafe skill and current official documentation for Jev work.
- Never display, copy into logs, or commit the intentionally local credential file.
- Keep experiments bounded; own and close only the emulator process you start.
- Preserve `launchers\launch.bat` D/L calibration. Experimental combat is a separate launcher.
- Carl approved paid Jev requests (free tier) on 2026-09-19. Keep every live run bounded by the runner's request cap. Zero-API dry/baseline runs and offline analysis are always fine. Do not claim level completion or hazard coverage we have not demonstrated.
- Live combat uses pause-and-step (`--stepped`) with the gun on from the start (`--prelude-fire`). Compare only against a baseline with the same prelude and frame budget.
- Adopt a new RAM slot only with per-slot evidence from two recordings; keep `lua/main.lua` `enemy_bases` equal to `ENEMY_BASES`.

