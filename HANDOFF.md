# Handoff - 2026-09-19 late evening, America/Chicago

## Where this stands

A bounded experimental controller plays U.N. Squadron level 1 with Jev choosing movement.
**Level 1 is not finished and the boss has never been reached**; 1800-frame runs end on their
frame budget. Runs aimed at the level end are now allowed up to 7200 frames and 1600 requests.

Best runs, counting kills after Jev takes control at frame 20663:

| Run | Kills (air/tank/turret) | Hits | Pickups | Median X | End |
|---|---:|---:|---:|---:|---|
| R19 `combat-20260919-232140` | **43** (30/5/8) | 2 | **3** | 126 | full window |
| R14 `combat-20260919-230019` | **43** (30/5/8) | **1** | 2 | 81 | full window |
| R12 `combat-20260919-225212` | 43 (30/5/8) | 2 | 2 | 126 | full window |
| R20 `combat-20260919-232804` | 12 | 1 | 1 | 111 | **died at 21344** |

For scale: a passive configuration reached 10 kills; before this evening the best was 42 with 3 hits.

## What moved the numbers, and what did not

Every gain came from the same discovery: **Jev was being given distances for decisions that are
about time**, or warnings that the code silenced. Four measurement defects, all fixed with tests:

1. **Terrain floor read from ground-target altitude.** A tank standing at Y 176 was treated as
   solid ground, so with a tank lined up (3 px error) *all five options* were labelled "ends at or
   below terrain" - tank kills were forbidden by construction. Only recorded collisions measure
   the surface now; a ground target's altitude is the firing line, flown safely in 74 of 122
   mapped columns. Tank kills went 1 -> 5.
2. **Velocity aliased to exactly zero.** Objects stationary in the level drift with the scroll at
   0.5 px/frame - one pixel every *other* frame - and a one-frame difference sampled on a fixed
   6-frame cadence always lands on the same parity. Turrets and screen-clear power-ups read 0.00
   in 100% of samples, so a drifting power-up looked parked. Velocity is measured over a 30-frame
   baseline now; those objects read -0.500.
3. **Terrain warnings cleared when every option was too low.** A valve meant to avoid an impossible
   constraint deleted the warning exactly when the aircraft was below a recorded collision
   altitude (three hits at Y 174 in one run). Warnings are kept; every option reports clearance in
   pixels, and the instruction says to climb out on the option with the most.
4. **No memory across decisions.** Each decision was judged fresh, so nothing could show that the
   aircraft had camped on one side for seconds, or sat inside the collision range for four
   decisions in a row (which is how R20 died). `where_you_have_been_recently` and
   `time_in_the_collision_range` are measured from the run itself.

**Both attempts to write tactics instead of measurements made runs worse and were reverted.**
Telling Jev to "turn and work the targets ahead" pushed it to median X 171: 36 kills, 5 hits, died.
Telling it to stay level with crossing targets pushed it to X 77 and 41 kills. Position correlates
strongly with outcome: every 43-kill run sat between X 81 and 131, both worst runs sat at 171.
Give Jev measurements; let Jev choose the tactics.

## How it works now

- **Pause-and-step.** Lua pauses on each decision frame; the choice applies from the observed
  frame. Decisions every **6 game frames**.
- **Whole object table.** WRAM `0x1000..0x1FC0`, 0x40-byte records, bytes 1..3 a routine address:
  helicopters `$02:B04A`, bullets `$04:F97F`, weapon power-up `$04:FABA`, screen-clearing power-up
  `$04:FAD9`, tanks `$02:9274` and `$02:90F0..9203`, turrets `$02:93DD`.
- **Facts per option**, all computed, none of them tactics: shot geometry and aim error; closest
  threat and direction; targets ahead/behind; **frames** to fly back past the nearest target
  behind, and what holding that direction for the whole transit reaches and costs; targets about
  to slip behind and when; power-up reach and expiry **in frames**, plus what holding a direction
  closes to; warning room and retreat room in pixels **and frames**; terrain clearance; and a
  30-frame whole-field forecast.
- **A screen-clearing power-up leads every option** when one is in play, per Carl's instruction
  that it should reshape the approach rather than sit at the end of the list.
- **One question per decision** (movement, five options). Jev returns probabilities and a
  confidence. There is no separate GOAL/AIM/DODGE question as in the Doom agent - see below.

## Jev Squadron dashboard

`dashboard.bat` serves **http://127.0.0.1:8770**. Leave it open: it follows
`runs/active_segment.json` and switches runs by itself with no human involvement. Header live
feed, a radar of what Jev actually sees, Jev's movement probabilities, and an R### history table.
It reads only the run files - no hook into the controller, no credentials, no emulator access.
`test_dashboard.py` covers it offline, including torn writes from a run in progress.

## Open problems, in the order they cost the most

1. **The boss and the rest of the level.** Never reached. Longer runs are now permitted; new
   object routines past frame 22463 must be surveyed from a replay capture before Jev meets them.
2. **The grounded helicopter.** It sits on the ground, takes off later, and matches **no**
   classified routine, so Jev cannot see it at all. Carl flagged it four times. Needs a replay
   capture of the late window and `survey_objects.py`.
3. **Aircraft collisions.** The one repeating damage source. R20 died after four consecutive
   decisions at 20-21 px from a tank; `time_in_the_collision_range` was added for exactly this
   and has not yet been measured across runs.
4. **Shooting into terrain.** Jev lines up targets with a structure in between, because terrain
   blocks shots and nothing models that.
5. **The tank-behind delay.** It now takes the tank, but 30-60 decisions later than a human would.

## Running it

```powershell
dashboard.bat                      # leave open; follows runs by itself
run_jev_segment.bat                # live: stepped, firing prelude, interval 6, 300 requests, 1800 frames
python run_segment.py --mode live --stepped --prelude-fire --interval 6 --max-calls 700 --frames 4200
python run_segment.py --mode dry --stepped --prelude-fire --interval 6 --max-calls 300 --frames 1800
python analyze_segment.py runs\<run>
python build_terrain_map.py        # after runs, to extend the terrain map
python -m unittest test_bridge test_brain test_combat test_dashboard   # 75 offline tests
```

Discovery: `probe_hazards.py --modes replay --replay-run runs\<run> --frames <n>` (exact replay
with full-WRAM capture; its overlay says OFFLINE CAPTURE so it is never mistaken for a Jev run),
then `survey_objects.py <capture>`.

## Rules that still hold

- **Slot 1 must hash `c1ea750e...`** (game frame 20183). `run_segment.py` refuses otherwise.
- `typesafe_api_key.txt` stays local and ignored; only `play_segment.py --mode live` reads it.
  Never print or commit it.
- The runners refuse to start if an emulator is already open and close only their own process.
- Evidence discipline: adopt an object type only after checking it against screenshots in two
  recordings; keep health, damage and death unmapped. Do not claim level completion.
- Avoid overfitting: stage facts are counted at runtime, thresholds are relative, and tactics
  belong to Jev rather than to code. The two violations of this rule both lost kills.
- **The repository has no remote.** Commits are local. To publish:
  `winget install GitHub.cli` then `gh repo create jev-un-squadron --private --source . --remote origin --push`.
