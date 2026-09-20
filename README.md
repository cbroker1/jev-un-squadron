# Jev U.N. Squadron experiment

BizHawk/Lua handles the SNES game; Python reads observations and sends controller actions. **Level 1 completion is not demonstrated**: the boss is reached but has never been killed, and no boss part has ever been destroyed. The best full-level run destroyed 82 of the 108 units it met, taking 4 hits. The original D/L launcher is target-70 calibration.

Before changing how Jev is asked anything, read [docs/typesafe/README.md](docs/typesafe/README.md):
the vendor documentation is saved locally and this project currently breaks several of its
rules, including asking a model that cannot do arithmetic to weigh numbers.

For the next agent: read [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md) first.

## Experimental combat (separate from D/L calibration)

With BizHawk closed, `run_jev_segment.bat` opens slot 1 at 50% speed and uses the intentionally local key. It runs **pause-and-step**: the game pauses on each decision frame while Jev decides, and the choice applies from that frame. The gun fires from the start. It permits at most **300 paid attempts** over 1800 combat frames with a decision every 6 game frames (bounds allow up to 1600 attempts over 7200 frames for runs aimed at the level end), releases controls and closes only its own emulator. Jev now sees helicopters, bullets, the dropped power-up and ground tanks from the game's object table. It is asked to collect the power-up when safe and, at lowest priority, to shoot tanks from a distance. Stop with **Ctrl+C** or **stop_segment.bat**. Do not run both launchers at once. The bounded runner refuses an already-open emulator.

The first 480 game frames are a deterministic prelude (gun firing with `--prelude-fire`, otherwise neutral and gun off; the gun-off prelude lets the player take a hit before Jev starts), followed by the combat window (`--frames`, default 210). Combat movement comes from Jev; Y firing is independent. Firing-only waiting/no-checked-track intervals are explicitly deterministic, not attributed to Jev. Logs, frames, provenance and failures are under a unique `runs/combat-*` folder. Observation now covers 7 checked aircraft slots and 6 projectile slots, including the orange helicopters missing from the first live test. Ground objects, terrain and other hazards are still unknown, so this is a research test, not a level-clear agent. Compare a run only against a baseline with the same prelude, frame budget and export: `runs/combat-20260919-162523-593790-baseline` (firing prelude, 420 frames) or `runs/combat-20260919-140905-903ba4-baseline` (gun off, 210 frames). See [the pause-and-step report](hazard_observation/PAUSE_AND_STEP_2026-09-19.md).

```powershell
python run_segment.py --mode dry --stepped --prelude-fire --interval 6 --max-calls 300 --frames 1800
python run_segment.py --mode baseline --prelude-fire --frames 420
# Paid (what run_jev_segment.bat runs):
python run_segment.py --mode live --stepped --prelude-fire --interval 6 --max-calls 300 --frames 1800
```

Dry/baseline modes make zero API calls and never read the key. `--max-calls` changes this runner's limit (1..1600); it does not use the old launcher's config limit. Its pending-result logging was amended after the live test; see the handoff's verification caveat.

## Measuring a change

Gameplay regressions do not show up in unit tests, so every change is judged by running it:

```powershell
python runs_table.py --last 12 --full-level-only   # units destroyed, share, hits, change under test
python benchmark.py --recent 3 --baseline 12       # per level segment, against the previous band
python replay_run.py --best-boss                   # watch a run back on screen
```

`run_segment.py --change "what this run tests"` records the change in the run's manifest so
the table can attribute it.

## Jev Squadron dashboard

`dashboard.bat` (or `python dashboard.py`) serves **http://127.0.0.1:8770** and opens it. Leave it
open across runs: it follows `runs/active_segment.json` and switches to each new run by itself.

- Header: run label, frame, elapsed frames, decision id, chosen action, Jev's confidence, latency,
  plane position and the aircraft's recent station-keeping.
- **What Jev sees**: a radar of the classified object table only - the plane and its gun line,
  aircraft, bullets, both power-up types, tanks and turrets, each with a 30-frame velocity trail.
  Objects with no classified routine do not appear, which is the honest picture of what is tracked.
- **Judgment**: Jev's own probabilities per movement option. There is exactly one question per
  decision (movement); the feed's tags are derived from the facts Jev was given, not extra judgments.
- **Live feed** and a **run history** table of kills, hits and what caused them, pickups and median X.

It reads only the files runs already write, holds no state, and has no hook into the controller or
the emulator, so it cannot affect a run.

## Your existing D/L launcher

1. Keep your existing BizHawk instance at the gameplay save, with the current `lua/main.lua` active. After code updates, reload that script once before using this manual workflow.
2. Double-click `launch.bat`. Choose **D** for deterministic dry-run or **L** for live Jev calibration.
3. Unpause during the five-second countdown. The checklist remains in the terminal.
4. Stop early with **Ctrl+C in the bridge terminal**. The terminal closes when the run finishes. This launcher does not open or close your emulator.

`config.json` controls `max_calls` (default **60**) and `decision_interval_frames` (default **30 actual game frames**, not seconds). The local `typesafe_api_key.txt` is intentionally reused by `launch_live.ps1`, without printing it. Leave it local; do not paste it into chat or commit it. Dry-run/preview modes need no key. A live API error stops instead of choosing a gameplay fallback.

Controls have bounded frame leases. On a stopped/lost bridge, injected controls expire; a paused emulator observes a STOP on its next frame. Loading a save invalidates the old run. Physical input is not an injected action.

## Automatic, no-key checks

With BizHawk closed, `run_brain_preview.bat` opens the ROM at slot 1, watches 900 game frames at **50% speed**, writes passive observations and Choice previews under `runs/bridge-check-*`, then closes its own emulator. **It does not move or fire, and makes zero Jev requests.** Ctrl+C stops the runner. It refuses to replace an already-open emulator.

`run_projectile_probe.bat` instead performs deterministic neutral/firing captures under `hazard_observation/probe_*`. Stop that capture using Esc in BizHawk, Ctrl+C, or `stop_projectile_probe.bat`. It also uses zero Jev requests.

For a programmer/agent continuing development:

```powershell
python -m unittest test_bridge test_brain test_combat -v
python check_bridge.py --mode calibrate
python check_bridge.py --mode reload
python check_bridge.py --mode expiry
python replay_brain.py hazard_observation\probe_20260919-121654-34c1a8_pulse6 --at-sample 862
python replay_brain.py hazard_observation\probe_20260919-132216-1dd64b_pulse8 --combat --horizon-frames 30 --at-sample 540
python analyze_aircraft_slot.py hazard_observation\probe_20260919-114543-d95c1f_neutral --base 0x1840
python probe_hazards.py --modes replay --replay-run runs\combat-20260919-170320-486fe9-live --frames 1380 --capture-from 480 --capture-to 1380
python survey_objects.py hazard_observation\<probe_folder> --from-sample 480
python build_terrain_map.py
python analyze_segment.py runs\<run> --baseline runs\combat-20260919-163609-585d4f-baseline
```

`replay_brain.py` reads saved evidence only: no emulator, API, credentials, or controller writes. `observe_brain.py` is the passive reader for an already-running current `main.lua`; it clears stale injection at startup but never requests movement/fire. Its preview interval counts game frames.

The older discovery launchers and `run_live_smoke.bat` are not the recommended path. In particular, the legacy smoke helper can close other emulator instances; the new check runners preserve them.

## What is genuinely established

Player reference X/Y, cardinal directions, tested movement limits, pulsed-Y gunfire, bounded action timing, and save-reload/expiry safety have recorded run evidence. Six slots in one enemy-projectile family and seven aircraft slots have per-slot visual and lifetime evidence; they are **not** complete hazard detection. Health, recovery, death, terrain and collision sizes remain unknown. Lua overlays are omitted by BizHawk's saved screenshots; independent annotations validate reference positions, not live overlay rendering.

See [PROJECT_STATE.md](PROJECT_STATE.md), [MEMORY_MAP.md](MEMORY_MAP.md), the [aircraft slot report](hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md) and the [2026-09-19 adoption report](hazard_observation/BRAIN_ADOPTION_2026-09-19.md) for precise evidence, caveats and the single next experiment.
