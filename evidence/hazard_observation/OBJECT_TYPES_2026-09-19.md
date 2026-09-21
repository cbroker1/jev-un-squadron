# Object table, power-ups and tanks - 2026-09-19 (evening)

Handoff entry: [CLAUDE_HANDOFF.md](../../docs/notes/CLAUDE_HANDOFF.md). Previous step: [pause-and-step](PAUSE_AND_STEP_2026-09-19.md). Carl asked for two things: collect the power-up that drops after the last orange unit dies, when that is safe; and, at low priority, fly low to kill ground tanks when that is safe.

## Verdict

- **The game keeps its objects in a table.** WRAM `0x1000..0x1FC0` holds 0x40-byte records. Byte 0 is a flags byte; bytes 1..3 hold a 24-bit routine address that identifies the object type; X/Y are signed 16.8 at `+0x10/+0x13`.
  - The player is `0x1000` (`$04:DF96`), and its shots are `0x1080/0x10C0` (`$04:E6AF`).
  - The controller now classifies **every** record by routine instead of watching fixed slots.
- **Types checked against screenshots in two recordings:**

  | Kind | Routine and gate | Evidence |
  |---|---|---|
  | Helicopters | `$02:B04A`, flags `C8`, `+8 = 03` | Seen in 12 slots across three captures, orange and green |
  | Enemy bullets | `$04:F97F`, flags `CC`, `+8 = 01` | **Blue or orange**; also in slots `0x1C40/0x1C80`, outside the old list |
  | Power-up | `$04:FABA`, flags `C8`, slot `0x1400` | Collected on contact at about 18 px; the HUD changes from POW 2/0 to 1/1 |
  | Ground tanks | `$02:9274` and `$02:90F0/9119/9131/9166/91DB/91FF/9203` | Killed by the main gun from Y 178-191; they **collide** with the aircraft |

- **Candidate hit marker:** `$04:F8A1` appears in slot `0x1040` on the frame the player is hit, followed by `$04:F8BC`. It matched every hit seen in screenshots: fire-from-start capture at about 20963, replay 21383, live 21236 and 21389. It is used only to count outcomes after a run, not as a health mapping.
- **Controller result:** the latest live run (`combat-20260919-170320-486fe9-live`) finished the 900-frame window (to frame 21563) with **zero hit markers** and collected the power-up. It killed no tanks.
  - The earlier run `165853-0b067a` killed 3 tanks but crashed into one.
  - Each configuration was run once, so this is progress, not proof.

## How the types were found (zero API)

1. **New capture mode.** `probe_hazards.py --modes replay --replay-run <run>` replays a run's logged per-frame button masks. It checks that every snapshot's player X/Y equals the run's log.
   - `probe_20260919-164616-e5ae0a_replay` reproduced Jev's 900-frame run `163645-fc9efa` exactly: 482 full-WRAM snapshots with screenshots.
2. **Survey.** `survey_objects.py <capture>` groups the table by routine address and writes `object_survey.json` and `object_points.csv`.
3. **Visual check.** `scripts\render_object_types.ps1` boxes the chosen routines on the exact frames. Inspected sheets: `survey_types_overview.png`, `powerup_track_replay.png`, `ground_types_replay.png` (replay) and `powerup_pickup_pulse6.png`, `ground_types_pulse6.png` (fire-from-start capture `probe_20260919-121654-34c1a8_pulse6`).
4. **Other findings:**
   - All 22 helicopter entries in three recordings came from just past the right edge (X about 270-272).
   - `$02:A78D` (flags `9A`) is invisible on both frame parities and is not tracked.
   - Drawn objects have flag bit `0x40` set.
   - The large ground turret is not classified.

**Tool lesson.** The first replay capture failed with a Lua error that only BizHawk's console showed: `io.lines(assert(path, msg))` passed the message as a read format. Carl caught it.
- `lua/hazard_snapshots.lua` now runs inside a top-level `xpcall` that writes `error.txt` and closes BizHawk.
- `probe_hazards.py` prints the Lua error, and stops after 30 s if the script never starts.

## What the 21383 hit actually was

In the earlier best run, a helicopter in slot `0x1A00` appeared at (272,64), just past the right edge. It collided with the player, who was parked at X=239. The helicopter entered its hit state and the hit marker appeared on the same frame. The controller missed it for two reasons:
- that slot was not in the checked list;
- its reference point was off-screen, even though the sprite was on screen.

The orange ball seen on the jet at that frame was the hit flash.

## Controller changes

- `brain/observations.py`: `OBJECT_TYPES`, `classify_record`, `TableSlotTracker`, `TableTracker`, and a shared ROM/schema check. Tracks carry `routine` and `in_play`, meaning within 32 px outside the screen.
- `lua/main.lua` exports `object_table`: 64 records of 22 bytes, in one bulk read per frame, about 5 KB of state per frame.
- `brain/digest.py`: objects just past an edge count toward gaps.
- `brain/combat.py`, per option:
  - It leads with the **closest tracked threat** (the minimum over bullet, aircraft and tank gaps).
  - It adds the power-up closest approach and the ground-tank firing-line error.
  - It names the edge the action ends on ("the right edge, where every observed helicopter entered").
  - An option with nothing of a kind tracked reads "none tracked", not "unknown".
  - Instruction priorities: keep clear of threats; collect the power-up when safe; align with aircraft; lowest priority, shoot tanks from a distance and never descend onto them.
- `play_segment.py --stepped`: **re-plan trigger.** If the current action's closest threat gap drops below 24 px and has shrunk by at least 8 px since the decision, Lua pauses on the next frame and Jev is asked again (at most once every 6 frames).
- `analyze_segment.py` reports `candidate_table_events`: hit-marker frames, power-ups gone near the player or elsewhere, and tanks destroyed.
- 52 offline tests pass. Zero-API checks: stepped dry run `combat-20260919-165655-d56917-dry` passes; D/L `bridge-check-20260919-165820-0103a3` passes.

## Live runs (stepped, firing prelude, 900 frames, cap 45)

| Run (`runs/`) | Change | Requests | Hit markers | Power-up | Tanks destroyed |
|---|---|---:|---|---|---:|
| `combat-20260919-163645-fc9efa-live` (earlier, 7 fixed slots) | - | 26 | 1 (21383: right-edge helicopter), from its replay capture | collected at about 21111 (incidental) | 1 |
| `combat-20260919-165853-0b067a-live` | object table, power-up, tanks | 32 | 1 (21236: descended onto a tank) | collected 21098 | **3** |
| `combat-20260919-170125-d4745b-live` | tanks as bodies, "none tracked" | 37 | 1 (21389: right edge again) | collected 21098 | 0 |
| `combat-20260919-170320-486fe9-live` | closest-threat lead, edge names | 33 | **0** | collected 21098 | 0 |

The stationary firing baseline `163609-585d4f` was hit at about 20983 and lost control at 21084; the guard stopped it at 21205.

Paid attempts this round: 32 + 37 + 33 = 102; total so far **170**.

## Caveats and next

- One run per configuration. The hit marker is a candidate (four visual matches), not a health decoder.
- Tank kills disappeared once tanks became collision bodies at lowest priority. Getting safe tank kills probably needs a code-computed "level with a tank that is at least N px ahead" option, rather than more instruction text.
- Jev still uses Left at X=16 as a way to hold.
- Beyond frame 21563 is unexplored; the big ground turret and the stage boss are unclassified.

## Keeping the request general, not tuned to this segment (evening, second pass)

Carl asked to avoid overfitting the offline work into code or prompt rules, and to let Jev's own weighing do the judging.

- **Removed a stage-specific claim.** The instruction "every helicopter entered from the right edge" was true of three recordings of this one stretch, not a game rule. The request now carries `object_entries_counted_this_run`, counted live from the tracker's own new tracks, and says only that new objects appear from off-screen. `edge_words` names edges neutrally.
- **Re-plan trigger is relative now.** It fires when a threat appears where none was tracked, or when the closest-threat gap halves against what Jev was shown. The tuned 24 px threshold is gone.
- **Dropped the planned "safe tank line" rule.** Encoding a tactic in code is the overfitting Carl warned about. Code keeps computing geometry; Jev weighs it.

**Bug found and fixed.** The entry-edge loop named its loop variable `key`, shadowing the API key inside `run()`, so the next live request built `"Bearer " + tuple` and the run stopped with a bare `TypeError`. It cost about 4 paid attempts.
- `play_segment.py` now logs the exception type **and source location** (never the message).
- `test_combat.py` asserts every stepped request receives the caller's key, and that the error detail keeps no message text.
- The offline stepped tests had missed it because they patch `decide`.

**Three consecutive live runs** (`172622-90d9eb`, `172720-729582`, `172818-b5eabd`), unchanged settings:

| | Result |
|---|---|
| Checks | pass, all three |
| End | frame 21563 (full window), all three |
| Requests | 35 / 36 / 33 |
| Hit markers | **0 / 0 / 0** |
| Power-up | collected in 1 of 3 |
| Tanks destroyed | 0 |

Zero hits now holds across four runs counting `170320-486fe9`. The power-up is attempted but not always taken: in `172622` Jev moved toward it first (Right had the best approach, 90 px), then made safety choices and the canister drifted off the left edge at frame 21192, 38 px below the aircraft. Tanks stay unvisited while they are collision bodies at lowest priority.

Paid attempts this pass: 3 failed runs + 1 diagnostic post + 1 short repro + 104 = 109; total so far **279**.

## Playing to attack, not just to survive (evening, third pass)

Carl's point: Jev was optimising "zero hits" instead of destroying units and taking power-ups, and a human would clear this stretch. Three causes, all mine:
- Killing appeared only as an "alignment error" ranked last, behind safety.
- A 30-frame decision commits to a 75 px move; a human makes small corrections.
- Nothing told Jev whether a move would actually put a target in the gun's path.

**Measured shot geometry.** Player shots (`$04:E6AF`) travel right at exactly **11 px per game frame** at the aircraft's own Y (420 measured steps, no variation), from X 22 to about 251. The vertical tolerance is about **10 px**, estimated from the two kills where a shot and target were captured in the same frame.

**Changes**
- `brain/combat.py`: `shot_intersections` reports, per option, which tracked targets a shot fired from that position would meet and when, using the target's own velocity. `aim_error` reports how far off the gun line the nearest reachable target is, so an option that lines up a future shot is visible.
- Goal and instructions rewritten: destroying targets and collecting power-ups is the objective, and avoiding damage is the constraint on how to attack. Weaving between bullets to reach a firing position is the intended play. An option that hits nothing and only keeps distance is called out as a wasted move when a safer-or-equal option attacks.
- `--interval` is now a runner option (1..30 game frames, default 30) and the request cap is 1..400. The prelude re-issue cadence no longer rewrites the action file every frame, which at a 6-frame interval made Lua read a half-written file and abort the run. An empty run id is now treated as a torn read, not another bridge.
- `analyze_segment.py` also counts `aircraft_destroyed`.

**Results** (900-frame window, kills counted after Jev takes over at 20663, so prelude kills are excluded):

| Run | Interval | Requests | Aircraft | Tanks | Hits | Power-ups |
|---|---:|---:|---:|---:|---:|---:|
| `170320-486fe9` / `172622-90d9e` | 30 | 33 / 35 | 10 / 10 | 0 | 0 | 1 / 0 |
| `173831-ba0a81` (attack geometry) | 6 | 150 | 7 | 4 | 2 | 1 |
| `174223-df41c` (+ aim error) | 6 | 146 | **17** | **5** | 1 | 2 |
| `174348-2f981` (+ aim error) | 6 | 149 | **16** | 4 | 1 | 1 |
| stationary firing baseline `174014-347a3a` | - | 0 | 5 | 0 | 1 | 1 (guard stopped it at 21205) |

Options offering an immediate hit roughly doubled after the aim-error change (50-58 of ~148 decisions, against 37 of 150). Jev chose a maximum-hit option in about 70% of the decisions where one existed.

`launchers\run_jev_segment.bat` now runs `--interval 6 --max-calls 200 --frames 900`. Paid attempts this pass: 445; total **724**.

**Next:** two runs per configuration is still thin. Worth trying an interval of 3-4 frames, and giving multi-step aim progress rather than one step, since a single 6-frame move is 15 px.

## Positioning and foresight (evening, fourth pass)

Carl watched the runs and reported two things: Jev got pinched between a tank behind it and new arrivals instead of running to the left and dropping onto the tank, and in a later run it crashed into a tank it had not left room to arrive.

Both are general problems, so neither is coded as a tactic:

- **Position value, computed live.** Each option now reports `targets_ahead` (shots only travel right, so targets ahead are what this position can cover) and `warning_room_px` measured to whichever edge objects have actually been entering from this run. Where that edge is the right, these two favour the left side by themselves; if a stage fed objects from another side, the same numbers would favour the opposite side.
- **Foresight past the action.** Each option reports `threat_gap_if_you_hold_px`: the closest a tracked threat comes over the next 30 frames if the aircraft stays at the option's end position. A 6-frame action can look clear and still end where a tank arrives moments later, which is exactly how the frame-21055 tank collision happened (player (16,177), tank (25,176), 9 px).

**Hit causes, from the exported table:** every hit this pass is explained.
- Frame 21055: tank collision at the left edge on the tank line.
- Frame 21520: a tracked enemy bullet; its slot flipped to `$04:F9C3`, the bullet's post-impact state.
- Frames 21104 and 21346: collisions with helicopters; the enemy's slot flips to `$04:FCC0` on the same frame as the player's hit marker. A hit-cause report should read the record from the previous frame to name the kind before it exploded.

**Runs** (900 frames, interval 6, kills after 20663):

| Run | Aircraft | Tanks | Hits | Power-ups | Median player X |
|---|---:|---:|---:|---:|---:|
| `174648-6d58ab` | 17 | 5 | 1 (tank collision) | 1 | 46 |
| `174806-9452a4` | 17 | 5 | 1 (bullet) | 1 | 56 |
| `175132-8ff6f?` (with foresight) | 17 | 5 | **0** | 1 | 61 |
| `175257-ff42c?` (with foresight) | 16 | 5 | 2 (helicopter collisions) | 1 | 191 |

Kills are stable at 21-22 per run against 10 for the passive 30-frame runs and 5 for the stationary baseline. Hits vary from 0 to 2, and the run that drifted to the right side (median X 191) took both of its hits there, which matches Carl's reading that the left side is the defensive position here.

**Next:** more repeats to get a distribution rather than single runs; make the hit-cause analysis read the previous frame; and consider whether the position numbers deserve to be stated earlier in each option, since Jev weighed them differently between runs.

## Attacking on purpose: turrets, targets behind, and all directions (evening, fifth pass)

Carl's feedback drove this pass: Jev collided with aircraft unnecessarily; it should keep a reaction buffer rather than hugging the left bound, but the buffer must not stop it taking a kill; the orange turret drops a power-up and is worth prioritising; it let a tank behind it box it in instead of slipping past and killing it; and enemies arrive from every direction.

**New object type.** `$02:93DD` is a **turret**, a domed gun emplacement on a platform (zoomed frames 1170-1360 of the replay capture). Adopted as a tracked kind, counted as a collision body and as a target. Destroying one drops a power-up, which the runs bear out: the runs that killed 2 turrets collected 2 power-ups instead of 1.

**Request changes, all computed rather than ruled**
- `retreat_room_px`: room left on the far side from where objects enter, so sitting against a bound shows 0. The instruction calls it a waiting preference, not a no-go area: entering that strip to take a shot, reach a power-up or kill something behind is the right move.
- `targets_behind` and `pixels_to_pass_nearest_behind`: the gun only fires right, so a target behind is attackable only after getting past it. Without this there was no gradient toward a tank that had slipped behind.
- `closest_threat_direction` per option, and `tracked_threats_by_direction_now` in the state, since threats close from ahead, behind, above and below.
- Collision calibration: every recorded collision happened at a reference gap of 9-22 px, so the request states that range and flags an option whose closest threat falls inside it.
- Terrain note: a recorded hit came from flying low beside a turret platform. Terrain and platforms are not tracked at all.

**Two incidents**
- **Slot 1 was overwritten** at 18:13:22 (stray save state; BizHawk's save hotkey is Shift+F1). Runs then resumed at frame 21102 instead of 20183 and did nothing useful. BizHawk's own `.bak` matched the documented hash `c1ea750e...`, so slot 1 was restored from it and verified; the stray save is kept in the session scratch directory. `run_segment.py` now refuses to start when slot 1 does not match `SLOT1_SHA256`, and `play_segment.py` stops with `emulator_started_late`, before any paid request, if Lua attaches after the save frame.
- A prelude command issued on the frame before a pause was superseded before Lua read it, failing two mechanical checks. The prelude no longer issues a command on that frame.

**Results** (900 frames, interval 6, kills after 20663)

| Run | Kills (air/tank/turret) | Hits | Power-ups | Median X |
|---|---|---:|---:|---:|
| `180551`, `180830` (turret priority) | 20, 22 | 2, 2 | 2, 2 | 171, 171 |
| `181109`, `181232` (buffer as preference) | 18, 23 | 1, 2 | 2, 1 | 186, 96 |
| `181830` (directions) | 17 | 2 | 1 | 171 |
| `181953`, `182117` (directions) | 17, 20 | **0, 0** | 1, 1 | 126, 134 |

For comparison: passive 30-frame runs reached 10 kills with 0 hits, and a stationary firing plane gets 5 kills and dies around frame 21205.

**Still open:** hits remain mostly aircraft collisions when Jev is on the right; terrain is untracked; single runs per configuration; and a tank behind is now visible to Jev but its firing pattern is not modelled.

## Screen-clearing power-up, and collisions as the main damage source (evening, sixth pass)

**Second power-up identified by its effect, not its pixels.** `$04:FAD9` (slot `0x1400`, flags `C8`/`D8`, drifting left at a constant Y) is the screen-clearing item Carl described. In the two runs that touched one (`174223` at 7 px, `175257` at 14 px), every live target dropped from 5-6 to **0** within a few frames. Adopted as kind `clear_screen_power_up`, with its own closest-approach number per option and the instruction that it outweighs any single kill when the way there is clear, and should be let go when reaching it means crossing close threats. It did not spawn in the latest three runs, so the behaviour is not yet exercised live.

`$04:FABA` remains the weapon power-up: it drops from destroyed units and turrets, and the HUD goes POW 2/0 -> 1/1 on contact.

**Collisions stated as the main damage source.** Per Carl: colliding with an aircraft is bad, not merely wasteful. The instructions now say collisions are how this aircraft takes damage and that an option whose closest threat sits inside the measured 9-22 px collision range is a last resort.

**Results** (900 frames, interval 6, kills after 20663):

| Run | Kills (air/tank/turret) | Hits | Median X |
|---|---|---:|---:|
| `183245-c60ae?` | 21 (14/5/2) | **0** | 126 |
| `183408-fcf2f?` | 17 (11/4/2) | 1 (aircraft) | 111 |
| `183532-a7134?` | **24** (17/5/2) | **0** | 96 |

Two of three runs took no damage at all while destroying 21-24 units including both turrets, and the median position settled left of centre without hugging the bound. Baselines for the same window: passive 30-frame runs 10 kills, stationary firing 5 kills and dead by 21205.

## Position as value, and the terrain problem (evening, seventh pass)

Carl's diagnosis was that Jev kept getting sandwiched and never fell back to re-engage from in front of targets, and that we were patching symptoms. That was right, and the cause was structural: **every number Jev received described the present** (targets ahead now, hits available now), so a greedy choice always crept toward targets and ended up pinched. Nothing rewarded letting enemies come to it.

**Changes**
- `future_shots`: for each option, how many targets will cross into the gun's line within the next 60 frames if the aircraft holds that position, and how soon. Enemies travel left, so this gives a real gradient toward the left side without naming a side.
- `gap_ahead_px` / `gap_behind_px` per option, so a squeeze is visible as two numbers rather than one.
- Options now state where they end (`Ends at X,Y`), which the aircraft needs to reason about altitude at all.
- Instructions: falling back to where targets will drift into the line is normal play, not retreat, and beats chasing from behind where the gun cannot fire.

**Results** (1800-frame window, interval 6, kills after 20663)

| Run | Kills (air/tank/turret) | Hits | Power-ups | Median X | End |
|---|---|---:|---:|---:|---|
| `184344` | 26 | 3 | 2 | 201 | died 22403 |
| `184607` | 27 | 3 | 1 | 182 | full |
| `184931` (position value) | 22 | 2 | 2 | 156 | died 21885 |
| `185117` (position value) | 38 | 6 | 2 | **66** | full |
| `185840` (altitude + terrain note) | 24 | 1 | 2 | 156 | died 21859 |
| `190025` (altitude + terrain note) | **42** (29/5/8) | 3 | **3** | 156 | full |

Kills roughly doubled once position had value. The remaining hits are aircraft collisions and terrain.

## Terrain: what is known now

Terrain is **not** in the object table, and it is now a leading damage source: six hits in `185117` and two in `190025` had no tracked object within 36 px, every one while flying at Y 174-191.

- **The level scroll position is WRAM `0x007B`** (16-bit, +0.5 px per frame). Verified: screen x + scroll is exactly constant for stationary ground objects (spread 0.0 over 131 samples). `lua/main.lua` now exports it as `scroll_x`, which makes a level-keyed terrain map possible.
- `build_terrain_profile.py` (new) measures a ground surface from capture screenshots keyed by scroll position, with a median across frames so moving sprites drop out. **It is not usable yet:** colour alone cannot separate collidable ground from background art, so it reports the mountains and refinery towers (surface Y 103-128) rather than the surface the aircraft hits.
- Until a real map exists, the request states the measured facts: ground and platforms are solid but untracked, tracked tanks and turrets mark where that terrain is, and every recorded terrain collision happened at Y 174-191.

**Next for terrain:** build the map from evidence instead of pixels. With `scroll_x` exported, every run gives safe (level_x, y) positions flown and terrain-hit positions; a map of "lowest altitude flown safely" and "hit recorded" per level column would be measured rather than guessed, and would extend automatically to the boss section.

## Whole-field forecast and a measured terrain map (evening, eighth pass)

Carl's refinement: skip cones, consider the entire player field, and forecast about 30 frames rather than 60.

- `field_forecast` gives a 4x8 grid over the flyable area (rows about one gun band apart, or the map would miss every firing line). Each cell reports the targets that would cross the gun's line within 30 frames if the aircraft sat there, and how close the nearest threat would come. `future_shots` moved from a 60-frame to a 30-frame window.
- With the field map, runs held the left side (median X 81-96) and destroyed 36-39 units per run.

**Terrain, measured rather than guessed.** `lua/main.lua` now exports `scroll_x` (WRAM `0x007B`), so a frame's level column is `player_x + scroll_x`. `build_terrain_map.py` turns past runs into `terrain_map.json`: per 4 px column, the lowest altitude flown without an untracked hit and the altitude of any untracked hit. Each option now reports the measured floor where it would end, and says plainly that a column with no measurement is unknown rather than safe. The first map covers 304 columns over level x 0-1344, with 8 columns carrying recorded hits (for example level 888-892 at Y 174, level 1188 at Y 161).

| Run | Kills (air/tank/turret) | Hits | Power-ups | Median X |
|---|---|---:|---:|---:|
| `191514` (field map) | 38 (28/5/5) | 6 | 1 | 91 |
| `191747` (field map) | 38 (29/5/4) | 4 | 2 | 81 |
| `192145` (terrain map) | 39 (28/5/6) | 3 | 3 | 165 |
| `192417` (terrain map) | 36 (30/0/6) | 3 | 2 | 96 |

Untracked terrain hits fell from 4-6 per run to 1-2 once the measured floor was reported, on two runs each, which is thin evidence.

## Terrain measured from ground objects (late evening, ninth pass)

The terrain map only covered columns the aircraft had already flown, which is why terrain kept causing hits in unvisited stretches. Tanks and turrets **stand on** that terrain, so their positions measure its surface wherever they appear, whether or not we have flown there.

`build_terrain_map.py` now records `ground_object_y` per level column from every gated tank and turret in every run's exported object table. Coverage went from 13 columns with hit data to **122 columns with a measured surface**, over level x 0-1416. Each option reports the surface altitude where it would end, plus any recorded collision or the lowest altitude flown safely there.

| Run | Kills (air/tank/turret) | Hits | Power-ups | End |
|---|---|---:|---:|---|
| `214509` (before) | 38 (28/5/5) | 4, all terrain | 2 | full |
| `214749` (before) | 30 (23/5/2) | 3, all terrain | 2 | died 22060 |
| `215106` (surface map) | 32 (27/2/3) | 2 (turret, aircraft) | 1 | full |
| `215340` (surface map) | 41 (30/5/6) | 2, both terrain | 3 | full |
| `215629` (combined text) | **42** (30/4/8) | **2** (bullet, terrain) | 2 | full |

Terrain hits per run fell from 3-4 to 0-2 on five runs, which is still thin evidence, and the best run now destroys 42 units with two hits over the full 1800-frame window.

## Terrain collisions to zero (late evening, tenth pass)

Carl asked for zero terrain collisions. Checking each terrain hit against the map showed the cause was not missing data: the hits clustered on a few level columns (854, 873, 889, 897, 907, 1142, 1160, 1190) and the map **already carried a recorded collision altitude for almost every one**. Jev was told "a terrain collision was recorded here at Y 174 and below" and flew there at Y 174 anyway. Two defects:

- Terrain was one sentence among fifteen, with no weight behind it.
- The lookup only covered the column where a move ends, not the columns it crosses.

Now `terrain_at` spans every column between the current and projected position, each option carries `terrain_floor_y` (the altitude at or below which terrain is known solid on that path) and `ends_at_or_below_terrain`, and such an option is flagged `TERRAIN:` and called disqualifying in the instructions, since contact is damage every time and a higher option always exists.

| Run | Kills (air/tank/turret) | Hits | Terrain hits | Power-ups |
|---|---|---:|---:|---:|
| `220250-9ea86?` | 39 (30/1/8) | 1 (bullet) | **0** | 3 |
| `220532-a4fff?` | 31 (30/0/1) | **0** | **0** | 1 |
| `220807-ae2de?` | 37 (30/1/6) | 2 (aircraft) | **0** | 3 |

Terrain hits went from 1-4 per run to none in three runs, and the rebuilt map recorded no new hit columns, which confirms it independently. **Trade-off:** tank kills fell from 4-5 per run to 0-1, because tanks sit on the terrain Jev now stays above; turret kills held at 6-8. Aircraft collisions are now the only repeating damage source.
