"""Read capture evidence, not the action file. No network or controller writes.

The observed projectile-family decoder is not complete hazard enumeration.
Its exact-byte gate is an evidence profile, not a general object-type decoder.
The bounded experimental controller uses only the explicitly checked slots.
"""
import csv
import json
import math
from pathlib import Path

WRAM_SIZE = 0x20000
PLAYER_X = 0x1011
PLAYER_Y = 0x1014
SLOT = 0x1AC0
PROJECTILE_X = 0x1AD0
PROJECTILE_Y = 0x1AD3
# Discovered by an exact-header search, then checked against frame-matched images.
# Do not extend this list by assuming a slot stride or a game object ID.
PROJECTILE_BASES = (0x1AC0, 0x1B00, 0x1B40, 0x1B80, 0x1BC0, 0x1C00)
# 0x17C0/0x1800/0x1840/0x1880 added after per-slot gate/lifetime checks in both captures:
# hazard_observation/AIRCRAFT_SLOTS_2026-09-19.md. Slots held orange and later green
# helicopters, so no base implies a colour or type. 0x1700/0x1740 remain unchecked.
ENEMY_BASES = (0x16C0, 0x1780, 0x17C0, 0x1800, 0x1840, 0x1880, 0x1940)
# Object table: 0x40-byte records from 0x1000 (player 0x1000, its shots 0x1080/0x10C0).
# Bytes 1..3 of a record hold its routine address, which identifies the object type.
# Each type below was matched to screenshots in two recordings; see
# hazard_observation/OBJECT_TYPES_2026-09-19.md. Unknown routines are never tracks.
TABLE_BASES = tuple(range(0x1000, 0x2000, 0x40))
RECORD_BYTES = 22
_TANK = ("ground_tank", {0xC8, 0xD8, 0xE0}, None)
OBJECT_TYPES = {
    bytes.fromhex("4ab002"): ("enemy_aircraft", {0xC8}, {3}),      # $02:B04A helicopters, any colour
    bytes.fromhex("7ff904"): ("hostile_projectile", {0xCC}, {1}),  # $04:F97F bullets, blue or orange
    bytes.fromhex("bafa04"): ("power_up", {0xC8}, None),           # $04:FABA dropped weapon power-up
    # $04:FAD9: touching it destroyed every live target within a few frames in two runs.
    bytes.fromhex("d9fa04"): ("clear_screen_power_up", {0xC8, 0xD8}, None),
    **{bytes.fromhex(r): _TANK for r in ("749202", "f09002", "199102", "319102",
                                         "669102", "db9102", "ff9102", "039202")},  # $02:9274, $02:90F0..9203
    bytes.fromhex("dd9302"): ("turret", {0xD8, 0xC8, 0xE0}, None),  # $02:93DD ground gun emplacement
    # Past frame 22400, confirmed in two long recordings by measured motion and screenshots.
    # $02:9649 flies at 3.4-3.9 px/frame diagonally: the shells the fortified line throws,
    # a whole class of fire the aircraft could not see, and it died there in both runs.
    bytes.fromhex("499602"): ("hostile_projectile", {0xDC}, None),
    # Gun emplacements of the fortified line, each stationary or drifting with the scroll
    # at turret altitudes (Y 174-192) in both recordings.
    bytes.fromhex("1b9502"): ("turret", {0xD8}, None),      # $02:951B
    bytes.fromhex("cd9302"): ("turret", {0xD0}, None),      # $02:93CD
    bytes.fromhex("089502"): ("turret", {0xD0}, None),      # $02:9508
    bytes.fromhex("8fb002"): ("turret", {0xD8}, None),      # $02:B08F
    # $02:B05A: the helicopter that sits on the ground and climbs away, one byte from the
    # flying routine $02:B04A. Carl flagged it four times as a target Jev never engages.
    bytes.fromhex("5ab002"): ("enemy_aircraft", {0xC8}, None),
}
ROM_SHA256 = "0b155a54b6134601fc0791252a63ca73efd522667c3d6fd7a44f5b3c500039d7"
SLOT1_SHA256 = "c1ea750e24cdb17e2050eb4f490c82b3e7544c11441f736f60df7c014fde0f3d"
ROM_SHA1 = "a2dd48574b9f7a49977c91d12d5c52c17c2c82aa"


def fixed24(raw, address):
    """Signed 16.8 candidate, supported by continuous motion across the left edge."""
    return int.from_bytes(raw[address:address+3], "little", signed=True) / 256


def captures(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("rom_sha256", "").lower() != ROM_SHA256 or manifest.get("state_sha256") != SLOT1_SHA256:
        raise ValueError("Capture does not match this ROM/save evidence profile")
    validation = json.loads((folder / "validation.json").read_text())
    if not validation.get("pass"):
        raise ValueError("Capture runner checks did not pass")
    with (folder / "frames.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    raw = (folder / "wram_u8.bin").read_bytes()
    if len(raw) != len(rows) * WRAM_SIZE:
        raise ValueError("RAM capture length does not match the frame index")
    for index, row in enumerate(rows):
        if int(row["snapshot_index"]) != index:
            raise ValueError("Non-contiguous snapshot indices")
        yield row, memoryview(raw)[index*WRAM_SIZE:(index+1)*WRAM_SIZE]


def checked_profile(state):
    profile = state.get("observation_profile", {})
    if (profile.get("schema") != 1 or profile.get("domain") != "WRAM"
            or profile.get("rom_hash", "").lower().removeprefix("sha1:") != ROM_SHA1):
        raise ValueError("Bridge observation schema/domain/ROM does not match the checked profile")
    return profile


class SlotTracker:
    """Never carry velocity across a reload, gap, inactive tag or slot change.

    Reset thresholds are tracking guardrails, not claimed game mechanics.
    """
    allowed = PROJECTILE_BASES + ENEMY_BASES

    def __init__(self, max_gap_frames=6, max_speed_px_per_frame=8, base=SLOT, velocity_baseline_frames=30):
        if base not in self.allowed:
            raise ValueError("Slot is outside the visually checked research profile")
        self.base = base
        self.max_gap = max_gap_frames
        self.max_speed = max_speed_px_per_frame
        self.velocity_baseline = velocity_baseline_frames
        self.previous = None
        # Objects that are stationary in the level slide left with the scroll at 0.5 px per
        # frame, i.e. one pixel every other frame. A one-frame difference sampled on a fixed
        # decision cadence always lands on the same parity and reads exactly 0, so velocity is
        # measured over the longest unbroken run of recent samples instead.
        self.history = []
        self.generation = 0

    def observe(self, raw, frame, session, epoch=0):
        if len(raw) != WRAM_SIZE:
            raise ValueError("Expected one complete WRAM snapshot")
        return self.observe_slot(raw[self.base:self.base+22], frame, session, epoch)

    def classify(self, payload):
        """(kind, gated) from exact observed bytes, not an invented object ID."""
        if self.base in ENEMY_BASES:
            return "enemy_aircraft", bytes(payload[:4]) == bytes.fromhex("c84ab002") and payload[8] == 3
        return "hostile_projectile", bytes(payload[:4]) == bytes.fromhex("cc7ff904") and payload[8] == 1

    def observe_slot(self, payload, frame, session, epoch=0):
        if len(payload) != 22:
            raise ValueError("Expected the 22 observed bytes for one slot")
        base = self.base
        kind, header_match = self.classify(payload)
        signature = bytes(payload[1:7]) + bytes([payload[13]])
        x, y = fixed24(payload, 16), fixed24(payload, 19)
        result = {"slot": f"WRAM:0x{base:04X}", "raw_phase_byte": payload[0], "kind": kind,
                  "routine": f"${payload[3]:02X}:{payload[2]:02X}{payload[1]:02X}",
                  "phase": "observed_moving_signature" if header_match else "inactive_or_unclassified",
                  "x": x, "y": y, "on_screen": 0 <= x < 256 and 0 <= y < 224,
                  # Sprites extend past their reference point: objects just off an edge still count.
                  "in_play": -32 <= x < 288 and -32 <= y < 256,
                  "vx": None, "vy": None, "generation": self.generation,
                  "identity_status": "visually matched family occurrences; other classes unknown",
                  "activity_status": "observed signature, not a general active/type decoder"}
        current = (session, epoch, frame, x, y, signature)
        if not header_match:
            self.previous = None
            return result
        reset = self.previous is None
        if self.previous:
            old_session, old_epoch, old_frame, old_x, old_y, old_signature = self.previous
            delta = frame - old_frame
            reset = (session != old_session or epoch != old_epoch or delta <= 0
                     or delta > self.max_gap or signature != old_signature)
            if not reset:
                vx, vy = (x-old_x)/delta, (y-old_y)/delta
                reset = math.hypot(vx, vy) > self.max_speed
                if not reset:
                    # The same continuous object, measured over as long a baseline as this run
                    # of samples allows, so a half-pixel-per-frame drift is visible.
                    base_frame, base_x, base_y = self.history[0][2], self.history[0][3], self.history[0][4]
                    span = frame - base_frame
                    if span > 0 and math.hypot((x-base_x)/span, (y-base_y)/span) <= self.max_speed:
                        vx, vy = (x-base_x)/span, (y-base_y)/span
                    result.update(vx=vx, vy=vy)
        if reset:
            self.generation += 1
            self.history = []
        self.history.append(current)
        # A baseline of about half a second: long enough to resolve the scroll drift,
        # short enough that a manoeuvring enemy's recent velocity still dominates.
        while len(self.history) > 1 and frame - self.history[0][2] > self.velocity_baseline:
            self.history.pop(0)
        self.previous = current
        result["generation"] = self.generation
        return result


class FamilyTracker:
    """Independent lifetimes for explicitly observed slots, not a broad RAM scan."""
    def __init__(self):
        self.slots = [SlotTracker(base=base) for base in PROJECTILE_BASES]

    def observe(self, raw, frame, session, epoch=0):
        return [tracker.observe(raw, frame, session, epoch) for tracker in self.slots]

    def observe_bridge(self, state):
        profile = checked_profile(state)
        slots = profile.get("slots", [])
        if len(slots) != len(PROJECTILE_BASES) or {item["base"] for item in slots} != set(PROJECTILE_BASES):
            raise ValueError("Missing, duplicated or unknown projectile slot")
        payloads = {item["base"]: bytes.fromhex(item["bytes_hex"]) for item in slots}
        if any(len(payload) != 22 for payload in payloads.values()):
            raise ValueError("Incomplete projectile bytes")
        return [tracker.observe_slot(payloads[tracker.base], state["frame"], state["lua_session_id"], state["reload_epoch"])
                for tracker in self.slots]


class CombatTracker(FamilyTracker):
    """Limited checked aircraft family plus checked projectile family, not all hazards."""
    def __init__(self):
        super().__init__()
        self.enemies = [SlotTracker(base=base) for base in ENEMY_BASES]

    def observe(self, raw, frame, session, epoch=0):
        return super().observe(raw, frame, session, epoch) + [t.observe(raw, frame, session, epoch) for t in self.enemies]

    def observe_bridge(self, state):
        slots = state.get("observation_profile", {}).get("enemy_slots", [])
        if len(slots) != len(ENEMY_BASES) or {s["base"] for s in slots} != set(ENEMY_BASES):
            raise ValueError("Missing or unknown enemy observation slots; current main.lua is required")
        payloads = {s["base"]: bytes.fromhex(s["bytes_hex"]) for s in slots}
        if any(len(p) != 22 for p in payloads.values()):
            raise ValueError("Incomplete enemy observation bytes")
        return super().observe_bridge(state) + [t.observe_slot(payloads[t.base], state["frame"], state["lua_session_id"], state["reload_epoch"]) for t in self.enemies]


def classify_record(payload):
    """(kind, gated) for one object-table record, by routine address and accepted flag bytes."""
    kind, flags, byte8 = OBJECT_TYPES.get(bytes(payload[1:4]), ("unclassified", (), None))
    return kind, payload[0] in flags and (byte8 is None or payload[8] in byte8)


class TableSlotTracker(SlotTracker):
    """One object-table record, typed by its routine address."""
    allowed = TABLE_BASES

    def classify(self, payload):
        return classify_record(payload)


class TableTracker:
    """Every object-table record, classified by routine; only recognised objects become tracks."""
    def __init__(self):
        self.slots = {base: TableSlotTracker(base=base) for base in TABLE_BASES}

    def observe_records(self, records, frame, session, epoch=0):
        tracks = [self.slots[base].observe_slot(records[base], frame, session, epoch) for base in TABLE_BASES]
        return [t for t in tracks if t["phase"] == "observed_moving_signature"]

    def observe(self, raw, frame, session, epoch=0):
        if len(raw) != WRAM_SIZE:
            raise ValueError("Expected one complete WRAM snapshot")
        return self.observe_records({b: raw[b:b+RECORD_BYTES] for b in TABLE_BASES}, frame, session, epoch)

    def observe_bridge(self, state):
        table = checked_profile(state).get("object_table") or {}
        if (table.get("start") != TABLE_BASES[0] or table.get("stride") != 0x40
                or table.get("count") != len(TABLE_BASES) or table.get("record_bytes") != RECORD_BYTES):
            raise ValueError("Missing or unexpected object table; current main.lua is required")
        data = bytes.fromhex(table["bytes_hex"])
        if len(data) != len(TABLE_BASES)*RECORD_BYTES:
            raise ValueError("Incomplete object table bytes")
        records = {b: data[i*RECORD_BYTES:(i+1)*RECORD_BYTES] for i, b in enumerate(TABLE_BASES)}
        return self.observe_records(records, state["frame"], state["lua_session_id"], state["reload_epoch"])


def bridge_observation(state, tracker):
    return {"source_run": state["bridge_run_id"], "source_frame": state["frame"], "scroll_x": state.get("scroll_x"),
            "lua_session_id": state["lua_session_id"], "reload_epoch": state["reload_epoch"],
            "mode": "passive_offline_bridge_preview",
            "player": {"x": state["player_x_candidate"], "y": state["player_y_candidate"],
                       "liveness": "unknown", "health": None},
            "tracks": tracker.observe_bridge(state),
            "coverage": "six visually checked slots in one projectile family; other threats unknown",
            "actual_input_poll_mask": state["input_poll_mask"],
            "injected_mask": state["requested_mask"], "live_control_ready": False}


def observation(raw, row, run_id, tracker):
    frame = int(row["emu_frame"])
    tracks = tracker.observe(raw, frame, run_id)
    if isinstance(tracks, dict):
        tracks = [tracks]
    return {"source_run": run_id, "source_frame": frame, "sample": int(row["sample"]),
            "screenshot": row["screenshot"], "mode": "offline_reference_replay",
            "player": {"x": raw[PLAYER_X], "y": raw[PLAYER_Y],
                       "liveness": "unknown", "health": None},
            "tracks": tracks, "coverage": "six visually checked slots in one projectile family; other threats unknown",
            "live_control_ready": False}
