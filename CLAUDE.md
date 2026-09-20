# Project entry point

Read [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md), then the current sections of PROJECT_STATE.md and MEMORY_MAP.md. Historical sections contain disproved mappings; do not reuse them as current facts.

- Carl wants autonomous, visible BizHawk tests without repeated manual Lua clicks.
- Use the installed TypeSafe skill and current official documentation for Jev work.
- Never display, copy into logs, or commit the intentionally local credential file.
- Keep experiments bounded; own and close only the emulator process you start.
- Preserve `launch.bat` D/L calibration. Experimental combat is a separate launcher.
- Carl approved paid Jev requests (free tier) on 2026-09-19. Keep every live run bounded by the runner's request cap. Zero-API dry/baseline runs and offline analysis are always fine. Do not claim level completion or hazard coverage we have not demonstrated.
- Live combat uses pause-and-step (`--stepped`) with the gun on from the start (`--prelude-fire`). Compare only against a baseline with the same prelude and frame budget.
- Adopt a new RAM slot only with per-slot evidence from two recordings; keep `lua/main.lua` `enemy_bases` equal to `ENEMY_BASES`.

