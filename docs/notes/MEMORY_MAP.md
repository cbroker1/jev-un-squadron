# Memory map (USA SNES ROM)

ROM: `U.N. Squadron (USA).sfc` (1 MiB; SHA-256 `0B155A54B6134601FC0791252A63CA73EFD522667C3D6FD7A44F5B3C500039D7`)
Emulator: BizHawk 2.11.1 (`2.11.1+bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`); configured SNES core: `Snes9x`; domain used: `WRAM`.

## Current evidence (2026-09-19; supersedes older interpretations below)

Slot-1 SHA-256: `c1ea750e24cdb17e2050eb4f490c82b3e7544c11441f736f60df7c014fde0f3d`.
ROM SHA-1, also reported by the live Lua API: `a2dd48574b9f7a49977c91d12d5c52c17c2c82aa`.
Full measurements, run IDs and screenshots: [aircraft slot validation](../../evidence/hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md), [combat segment report](../../evidence/hazard_observation/COMBAT_SEGMENT_2026-09-19.md), [brain adoption report](../../evidence/hazard_observation/BRAIN_ADOPTION_2026-09-19.md) and [initial projectile validation](../../evidence/hazard_observation/PROJECTILE_VALIDATION_2026-09-19.md). Resume instructions: [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md).

| Address | Domain/type | Current interpretation and validation boundary |
|---|---|---|
| `0x007B` | WRAM/u16 LE | **Level scroll position in pixels** (+0.5 px per frame). Verified: screen x + scroll is exactly constant for stationary ground objects (spread 0.0 over 131 samples). Exported by `lua/main.lua` as `scroll_x`; `level column = player_x + scroll_x` keys the measured terrain map. |
| Routine `$02:93DD` | object type | **Turret**: domed gun emplacement on a platform. Destroying one drops a power-up. Collides with the aircraft. |
| Routine `$04:FAD9`, slot `0x1400` | object type | **Screen-clearing power-up**: in both observed pickups (7 px and 14 px), every live target went from 5-6 to 0 within a few frames. |
| Routine `$04:F9C3` | observed | Follows an enemy bullet that has struck (the bullet equivalent of `$04:FCC0`). |
| Player shots `$04:E6AF` | measured | Travel right at exactly **11 px per game frame** at the aircraft's own Y (420 measured steps), from X 22 to about 251. Vertical tolerance about 10 px, from two captured kills. |
| `0x1000..0x1FC0` step `0x40` | WRAM object table (22 bytes exported per record) | Byte 0 = flags (drawn objects have bit `0x40`); bytes 1..3 = 24-bit routine address that identifies the type; X/Y signed 16.8 at `+0x10/+0x13`. Player `0x1000` (`$04:DF96`); player shots `0x1080/0x10C0` (`$04:E6AF`). [Object-table report](../../evidence/hazard_observation/OBJECT_TYPES_2026-09-19.md). |
| Routine `$02:B04A` (flags `C8`, `+8 = 03`) | object type | Helicopters (orange and green), seen in 12 slots; all 22 observed entries came from X about 270-272. Supersedes the fixed `ENEMY_BASES` list for the controller. |
| Routine `$04:F97F` (flags `CC`, `+8 = 01`) | object type | Enemy bullets, **blue or orange**, including slots `0x1C40/0x1C80`. |
| Routine `$04:FABA` (flags `C8`), slot `0x1400` | object type | Dropped power-up; drifts left while bobbing; collected on contact at a reference distance of about 18 px (HUD POW 2/0 -> 1/1). Absent when nothing is killed. |
| Routines `$02:9274`, `$02:90F0/9119/9131/9166/91DB/91FF/9203` | object types | Ground tanks (states of the same units); destroyed by the main gun from Y 178-191; collide with the aircraft (live run `165853-0b067a`, frame 21236). |
| Slot `0x1040`, routine `$04:F8A1` then `$04:F8BC` | candidate | Appears on the frame the player is hit (four screenshot-matched hits). Used only to count outcomes after a run; not a validated health/death field. |
| Routine `$02:A78D` (flags `9A`), routine `$04:FCC0` | observed | `$02:A78D` is invisible (not tracked). `$04:FCC0` (flags `D0`) is the state after an object is destroyed. |
| `0x1011` | WRAM/u8 | Player screen X in tested positions; increases right. Separate 120-frame Left/Right probes stop at 16 and 239. Two-frame intervals travel 5 pixels before a bound, on this pilot/save. |
| `0x1014` | WRAM/u8 | Player Y: increases down. Separate 120-frame Up/Down probes stop at 48 and 191. Cardinal bridge check `20260919-122719-3657b3` repeats 112 -> 62 -> 112 in exact 20-frame Up/Down actions. General liveness remains unknown. |
| `0x002C` | WRAM/u8 | Rejected as persistent player Y: transient 236/224/192/160/128 values in neutral combat. Keep as legacy scratch candidate only. |
| `0x1AD1`, `0x1AD4` | WRAM/u8,u8 | Integer low-byte aliases for the first tracked projectile. Do NOT track these as unsigned screen positions: negative X wraps to the right. Use the signed values below. |
| `0x1AD0`, `0x1AD3` | WRAM/signed24LE divided by 256 (16.8) | Projectile-reference X/Y in slot `0x1AC0`. Three observed lifetimes, 45 neutral-run visual matches and 29 firing-run matches. Continuous X crosses zero between samples 698/700 without wrapping. Slot reuse invalidates velocity. |
| `0x1B10`, `0x1B13` | WRAM/signed24LE /256 | Same observed projectile family in slot `0x1B00`: 22 neutral and 13 firing visual matches. Per-occurrence coordinate evidence, not a general object-type ID. |
| `0x1B50`, `0x1B53` | WRAM/signed24LE /256 | Slot `0x1B40`: 14 neutral and 6 firing visual matches. Y reaches zero at neutral sample 888 and continues -3,-6,...,-18 through sample 900. |
| `0x1B90`, `0x1B93` | WRAM/signed24LE /256 | Slot `0x1B80`: 13 neutral and 5 firing visual matches. |
| `0x1BD0`, `0x1BD3` | WRAM/signed24LE /256 | Slot `0x1BC0`: 7 neutral visual matches. Not observed with the matching header in the latest firing run; do not infer why. |
| `0x1C10`, `0x1C13` | WRAM/signed24LE /256 | Slot `0x1C00`: 7 neutral visual matches. Not observed with the matching header in the latest firing run. |
| Each of the six bases, offsets `+0x00..+0x03`, `+0x08` | WRAM/byte sequence and u8 | Provisional research gate: exact bytes `CC 7F F9 04` and `01` at +0x08 in the visually matched moving occurrences. `00`/`C0` transitions are excluded, not interpreted as a universal inactive/hit/death flag. |
| Each base, offsets `+0x01..+0x06`, `+0x0D` | WRAM/opaque bytes | Continuity fingerprint only. Changes reset velocity/history. Byte meanings and guaranteed uniqueness are unknown; gap/jump guards additionally reset history. |
| `0x1091`, `0x1094` | WRAM/u8,u8 | One player-shot X/Y occurrence, confirmed after a single Y press at three heights. X is a rendering anchor 8.5 pixels ahead of measured colored center; slot lifetime not validated. |
| `0x0958`, `0x0959` | WRAM/u8,u8 | Rejected as persistent projectile identity: ceases to follow the same visible projectile by sample 600. Possible render-buffer data remains only a hypothesis. |
| `0x16D0`, `0x16D3` (integer bytes `0x16D1/0x16D4`) | WRAM/signed24LE /256 in the current decoder; signed behavior for this aircraft family remains untested | Aircraft-reference X/Y in slot `0x16C0`. Independent green-fragment Y ranking uniquely selected `0x16D4` across 82 points (visual Y 69..121); fractional-coordinate plots follow turns. 89 family matches in the neutral recording; independent Left recording samples 628/630/640 follows the same aircraft rather than the displaced player. Coordinate occurrence accepted; not universal identity. |
| `0x1790`, `0x1793` | WRAM/signed24LE /256 in current decoder; signed behavior untested for this family | Aircraft-reference X/Y in slot `0x1780`: 80 visual matches in the neutral capture and inspected family contact sheet. Limited occurrence evidence. |
| `0x1950`, `0x1953` | WRAM/signed24LE /256 in current decoder; signed behavior untested for this family | Aircraft-reference X/Y in slot `0x1940`: 78 visual matches in the same capture and inspected contact sheet. Limited occurrence evidence. |
| `0x17D0`/`0x17D3`, `0x1810`/`0x1813`, `0x1850`/`0x1853`, `0x1890`/`0x1893` (integer bytes are the old candidates `0x17D1/0x17D4`, `0x1811/0x1814`, `0x1851/0x1854`, `0x1891/0x1894`) | WRAM/signed24LE /256; enabled as aircraft slots `0x17C0`, `0x1800`, `0x1840`, `0x1880` | Aircraft-reference X/Y, accepted per slot on 2026-09-19 ([report](../../evidence/hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md)). Each gated reference follows an orange helicopter through wide X/Y ranges in the neutral and Left/firing recordings (orange pixels within 3.1 px at 109/110, 131/131, 98/107, 120/120 neutral and 46/46, 5/5, 34/34, 46/46 replay samples; the misses are green second occupants). It disappears when the reference passes X=256 or the gate turns off, and a new occupant starts a new track generation. X carries into the high byte past 255 (the old u8 "phantoms" at X=15 were X=271). Fractions are supported by exact integration of the neighbouring field at `+0x16`. Negative values are not observed, so signed behavior is untested. Slots were later reused by green helicopters and, for `0x17C0`, a ground-level object. The slot number is not a colour or type. |
| Seven accepted aircraft bases (`0x16C0`, `0x1780`, `0x17C0`, `0x1800`, `0x1840`, `0x1880`, `0x1940`), `+0x00..+0x03`, `+0x08` | WRAM/bytes | Research gate `C8 4A B0 02`, `03` at +8; changes invalidate tracking. It is NOT a green/orange classifier or a universal hostile-type ID. Observed non-gated states: `D0 C0 FC 04 .. FF/F9` right after a hit (coordinates drift, then byte 0 becomes `00`), `00 4A B0 02 ..` after exiting right, and other objects reusing a slot with byte 0 still `C8` (`C8 F0 90 02 .. 05`, `E0 74 92 02 ..`). Byte 0 alone is not an aircraft test. These are byte observations, not decoded kill/despawn semantics. |
| `0x1700`, `0x1740` | WRAM/aircraft-gate candidates; NOT enabled | Pass the aircraft gate only in the Left/firing replay (25 and 36 samples; three zoomed samples each show green helicopters exiting right); `0x1740` passes once, off-screen, in the neutral recording. No two-recording visual acceptance. Do not infer the rest of the 0x40 stride (`0x1680`, `0x18C0`, `0x1900`, ... were never gated in these captures). |
| `0x0020`, `0x0022` | WRAM/u8,u8 | Alternate low-memory projectile-correlated values in one interval; lifetime unknown, not accepted for tracking. |

Family evidence: neutral `probe_20260919-114543-d95c1f_neutral`, firing `probe_20260919-121654-34c1a8_pulse6`; see their `signature_candidates.json`, raw screenshots and inspected `family_reference_overlay.png` / `firing_family_reference.png`. The discovery JSON retains its original candidate label; only the documented visual occurrences have been accepted. Rectangles indicate reference points, not collision boxes. General class/coverage and unseen layouts remain unknown.

No complete enemy/projectile enumeration, universal active/type flag, collision box, health, recovery or death mapping is accepted. Per-occurrence coordinate validation does not establish those fields. `DANGER`, `EXTINCT`, flashing and explosion-like images must not be equated with a specific RAM health/liveness state without separate evidence.

Aircraft evidence: `probe_20260919-114543-d95c1f_neutral/{enemy_track_evidence.json,enemy_family_candidates.json,enemy_family_reference.png}` and `probe_20260919-120911-629b88_neutral/enemy_repeat_left.png`. Orange discovery/evidence: neutral and `probe_20260919-132216-1dd64b_pulse8` each contain `orange_components.csv`, `orange_candidates.json`, the older ungated `orange_1851_*.png`, and the gated per-slot evidence `aircraft_slot_<base>_evidence.json`, `orange_1840_gated_*.png` and `aircraft_<base>_gated_*.png`. Runtime export overlays: `runs/combat-20260919-135757-4bbef0-dry/dry_slot_1840_reference.png` and `runs/combat-20260919-140241-240bde-dry/dry_slot_{1800,17C0}_reference.png`. Discovery counts are color-fragment correlations, not counts of unique tracked enemies. All these files are under `evidence/hazard_observation/`.

**Damage evidence is visual only (2026-09-19).** The HUD damage gauge, red screen flash and DANGER label are read from screenshots; no RAM field is mapped.
- In both continuous-mode live runs, helicopter `0x1800` entered its hit header `D0` at frame 20731/20732, 17-20 px from the player reference. The player then stopped following confirmed input and the jet exploded on screen.
- In the stepped run `combat-20260919-162830-7da253-live`, the player moved away in time and `0x1800` never entered `D0`.
- This is consistent with a collision, but it is not a collision, health or death mapping. See [the pause-and-step report](../../evidence/hazard_observation/PAUSE_AND_STEP_2026-09-19.md).

**Bounds caveat from live combat:** X=16..239/Y=48..191 remain the measured controllable-motion limits for this save, not guaranteed valid values during forced animation. In live run `combat-20260919-131922-c4e603-live`, X reached 15 at frame 20732. The exact-input offline replay reproduces X=15 at sample 550, X=14 at 552/554, then motion without directional injection and an explosion sequence. Keep the conservative controller stop; health/death semantics remain unknown.

## Historical candidates (some interpretations were disproved above)

The following entries are historical evidence, not the current accepted map. Claims below using `0x002C` as player Y or treating `EXTINCT` as death are superseded above.

| Candidate | Domain | Type | Interpretation | Evidence |
|---|---|---|---|---|
| `0x1011` | WRAM | u8 | verified player screen X; live Lua-overlay capture unavailable | six-step zero-Jev probe: Left 96→49, Right 49→94 over 20-frame actions; independent annotated captures 540/560/600/620 place the value at the aircraft center |
| `0x002C` | WRAM | u8 | verified player screen Y; live Lua-overlay capture unavailable | six-step zero-Jev probe: Up 112→67, Down 67→107 over 20-frame actions; independent annotated captures 540/560/600/620 place the value at the aircraft center |
| `0x1024` | WRAM | u8 | movement-correlated candidate | repeated automated up/down search; not accepted after marker tests |
| `0x002C`, `0x0901`, `0x0905`, `0x1014` | WRAM | u8 | movement-correlated candidates | repeated search/watch only; unverified |
| `0x0098`, `0x009B`, `0x009D`, `0x00FA`, `0x00FB`, `0x0629`, `0x062B`, `0x100D` | WRAM | u8 | search candidates | repeated search only; unverified |
| `0x090B/0x090C` | WRAM | u8/u8 | provisional moving-object screen X/Y; identity unknown | annotated combat snapshots: `(38,80)`, `(45,211)`, `(45,191)`, `(45,172)`, `(45,152)` at samples 540–620; overlaps visible aircraft in some frames, but slot reuse/identity not established |
| `0x0908/0x0909` | WRAM | u8/u8 | provisional moving-object screen X/Y; identity unknown | annotated combat snapshots: X `96→227→207→188→168`, Y near `104→169`; no enemy/projectile identity or collision size established |
| `0x16F5/0x16F6` | WRAM | u8/u8 | provisional moving-object screen X/Y; identity unknown | annotated combat snapshots: X `24,4,39,22,182`, Y `110`; no enemy/projectile identity or collision size established |
| `0x0958/0x0959` | WRAM | u8/u8 | provisional firing-independent projectile/background screen X/Y | firing and neutral extended captures both read `(184,98)` at sample 580 and annotated boxes land on the same visible blue projectile; identity as hostile bullet vs background effect remains unknown; no collision size |

No health, enemy, projectile, pickup, or collision address is accepted.

Health observation batch: three independent zero-Jev runs (`run_1789778051`, `run_1789778083`, `run_1789778116`) reproduced the visible `DANGER` HUD state at the end of the bounded observation. Their broad WRAM change logs did not isolate a health field, so no address was promoted.

Repeat batch: `run_1789778438`, `run_1789778470`, and `run_1789778502` independently reproduced active gameplay at the frame-600 screenshot and `EXTINCT` at frame-660. This validates a repeatable death-window observation only; it does not identify health or invulnerability memory.

Dense run `dense_1789778766` captured the HUD transition at 10-frame screenshot spacing: capture 620 was pre-danger-window, 630 displayed `DANGER`, and 640 displayed `EXTINCT`. The valid WRAM log still showed many simultaneous changes, so no health candidate was accepted.

Dense repeat `dense_1789778884` has an identical WRAM log and identical frame-630 screenshot hash. This confirms the transition is reproducible from the loaded state; it is not independent evidence for any particular address.

Perturbed run `perturb_1789778967` held Up for 120 frames and then released controls. It displayed `DANGER` by capture 600 and `EXTINCT` by 630, earlier than the neutral dense runs. This validates timing sensitivity to input only; no health address was accepted.

Down perturbation `perturb_down_1789779128` held Down for 120 frames. The aircraft was absent by the 600-frame capture and the HUD was degraded by 630. This is timing/path evidence only; no health address was accepted.

Recovery probe `recovery_1789779221` used neutral input for 450 frames, then alternating Left/Right. The aircraft entered an explosion/death sequence around captures 600-630; no recovery was observed and no health address was accepted.

Focused run `first_damage_1789779381` captured screenshots every 2 frames from capture 500 onward. The first visible `DANGER` transition occurred between captures 626 and 628. This is a visual timing boundary only; no health address was accepted.

Firing comparison `first_damage_fire_1789779536` used Y pulses every 6 frames. Visible shots and score increases were observed; score reached 1200 by capture 700 and the aircraft remained active through the neutral run's damage window. This verifies the firing pattern's gameplay effect, not a health address.

Hazard snapshot discovery (`snap_1789780676`) ranked variable adjacent-byte pairs. Top unverified candidates included `0x1757/0x1758`, `0x1717/0x1718`, `0x1797/0x1798`, `0x16D7/0x16D8`, and `0x171A/0x171B`. They are only statistical candidates from WRAM variation; no enemy/projectile interpretation or overlay validation has been assigned.

Neutral comparison `snap_1789781633` produced the same top-ranked pairs as the firing capture. Firing changed 7,895 sampled bytes, but not the ranking; this rejects those top pairs as firing-specific evidence and leaves them unverified shared-motion candidates.

Extended firing capture `snap_1789781699` covers frames 20187–21083 through combat/death. After filtering values dominated by 0/255/off-screen sentinels, the top statistical pair is `0x1756/0x1757`, followed by candidates near `0x1B02`, `0x1042`, `0x181D`, `0x16DD`, and `0x179D`. These remain unverified coordinate candidates only.

Dynamic ranking from the same capture (valid-screen occupancy plus frame-to-frame changes) produced unverified pairs including `0x00CF/0x00D0`, `0x0068/0x0069`, `0x090B/0x090C`, `0x1710/0x1711`, and `0x16F5/0x16F6`. Motion statistics alone do not distinguish enemies, bullets, HUD, or scrolling.

Offline annotations of frames 540, 560, 580, 600, and 620 showed occasional overlap between candidate boxes and visible aircraft, but the same pairs also mapped to unrelated/HUD/terrain regions in other frames. This is evidence of ambiguity/reuse, not validation; all remain unverified.

## Controls

- Main gun: SNES `Y`, verified by visible player shots during the pulsed Y segment of the zero-Jev gun test. Pattern: repeated pulses, not continuous hold.
- Movement: Up/Down/Left/Right inputs are verified effective from the six-step zero-Jev calibration. `0x1011`/`0x002C` are accepted as repeatable screen-coordinate observations for the tested ROM/core/savestate and positions. Full screen-edge bounds, clean mid-run reload behavior, and a captured live Lua overlay remain unverified.

The provisional pairs (`0x0901`,`0x002C`), (`0x1011`,`0x1022`), and candidate C (`0x0069`, low byte `0x1023`) were rejected. `0x1011`/`0x002C` are now the validated player-coordinate pair within the documented evidence boundary. `0x1024` remains an unverified movement-correlated candidate and must not be used as player Y.

## Audit boundary (2026-09-18)

- `lua/main.lua` reads player X from `0x1011` and player Y from `0x002C`.
- `lua/calibrate_all.lua` still contains an older display label using `0x1022`; that script is an inconsistent legacy artifact and must not be used to promote a Y address.
- No health, enemy, hostile-projectile, pickup, collision-box, danger-recovery, or invulnerability address is validated. The tracks listed above remain provisional until visual continuity and a fresh slot-1 check succeed.
- See [`AUDIT_2026-09-18.md`](AUDIT_2026-09-18.md) for the next zero-Jev identity experiment and the exact evidence boundary.
