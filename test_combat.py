"""Offline combat tests; simulated API responses are not gameplay evidence."""
from contextlib import ExitStack
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from brain.combat import aim_error, combat_digest, combat_request, edge_words, field_forecast, future_shots, retreat_room, shot_intersections, warning_room
from brain.digest import ACTIONS
from brain.observations import CombatTracker, ENEMY_BASES, PROJECTILE_BASES, RECORD_BYTES, ROM_SHA1, SlotTracker, TABLE_BASES, TableTracker
import play_segment as player
from test_brain import ram


def fixture(frame=100):
    data=ram(220,100)
    base=ENEMY_BASES[0]
    data[base:base+4]=bytes.fromhex("c84ab002")
    data[base+8]=3
    data[base+16:base+19]=int(180*256).to_bytes(3,"little",signed=True)
    data[base+19:base+22]=int(80*256).to_bytes(3,"little",signed=True)
    return {"frame":frame,"lua_session_id":"unit","reload_epoch":0,
            "bridge_run_id":"unit","player_x_candidate":96,"player_y_candidate":112,
            "input_poll_mask":0,"requested_mask":0,
            "observation_profile":{"schema":1,"domain":"WRAM","rom_hash":ROM_SHA1,
                "slots":[{"base":b,"bytes_hex":data[b:b+22].hex()} for b in PROJECTILE_BASES],
                "enemy_slots":[{"base":b,"bytes_hex":data[b:b+22].hex()} for b in ENEMY_BASES],
                "object_table":{"start":TABLE_BASES[0],"stride":0x40,"count":len(TABLE_BASES),"record_bytes":RECORD_BYTES,
                                "bytes_hex":b"".join(bytes(data[b:b+RECORD_BYTES]) for b in TABLE_BASES).hex()}}}


class CombatTests(unittest.TestCase):
    def test_enemy_export_matches_full_coordinates_and_rejects_unknown_slot(self):
        state=fixture()
        tracker=CombatTracker()
        first=tracker.observe_bridge(state)
        second=tracker.observe_bridge(dict(state,frame=102))
        enemy=next(t for t in second if t["slot"]=="WRAM:0x16C0")
        self.assertEqual((enemy["x"],enemy["y"],enemy["vx"],enemy["vy"]),(180,80,0,0))
        self.assertEqual(enemy["kind"],"enemy_aircraft")
        self.assertEqual(len(first),13)
        state["observation_profile"]["enemy_slots"][0]["base"]=0x1800
        with self.assertRaises(ValueError):
            tracker.observe_bridge(state)

    def test_slot_1840_recorded_exit_and_reuse_never_carry_velocity(self):
        # Real 22-byte payloads, neutral capture probe_20260919-114543-d95c1f (samples 764..892).
        recorded=[(20947,"c84ab00236b10200030002030900000052fc00a86100"),
                  (20949,"c84ab00236b102000300020309000000baff00a86100"),
                  (20951,"c84ab00236b102000300020309000000220301a86100"),
                  (20957,"c84ab00236b1020003000203090000005a0d01a86100"),
                  (20959,"004ab00236b1020003000203090000000e0f01a86100"),
                  (21071,"004ab00236b1020003000203090000000e0f01a86100"),
                  (21073,"c84ab00236b102000300020309000000800e01008000"),
                  (21075,"c84ab00236b102000300020309000000800b01008000")]
        tracker=SlotTracker(base=0x1840)
        seen={frame:tracker.observe_slot(bytes.fromhex(payload),frame,"neutral") for frame,payload in recorded}
        self.assertEqual((seen[20949]["slot"],seen[20949]["kind"],seen[20949]["on_screen"]),("WRAM:0x1840","enemy_aircraft",True))
        self.assertEqual((seen[20949]["vx"],seen[20949]["vy"]),(436/256,0))
        # 24-bit X continues past 255 instead of wrapping to the left edge.
        self.assertAlmostEqual(seen[20951]["x"],259.1328125)
        self.assertFalse(seen[20951]["on_screen"])
        for frame in (20959,21071):
            self.assertEqual((seen[frame]["phase"],seen[frame]["vx"]),("inactive_or_unclassified",None))
        self.assertEqual(seen[21073]["generation"],seen[20957]["generation"]+1)
        self.assertIsNone(seen[21073]["vx"])
        self.assertEqual((seen[21075]["vx"],seen[21075]["vy"]),(-1.5,0))

    def test_slot_17c0_recorded_hit_and_ground_reuse_are_not_aircraft(self):
        # Real payloads, Left/firing replay probe_20260919-132216-1dd64b (samples 486, 488, 490, 526).
        tracker=SlotTracker(base=0x17C0)
        before=[tracker.observe_slot(bytes.fromhex(p),f,"replay") for f,p in
                ((20669,"c84ab00236b10200030002030900000020c800f36b00"),(20671,"c84ab00236b10200030002030900000088c400d47100"))]
        self.assertIsNotNone(before[1]["vx"])
        hit=tracker.observe_slot(bytes.fromhex("d0c0fc0436b10200ff00020309000000bcc200ab7400"),20673,"replay")
        self.assertEqual((hit["phase"],hit["vx"]),("inactive_or_unclassified",None))
        # Byte 0 is C8 again, but the other header bytes differ: not the aircraft gate.
        ground=tracker.observe_slot(bytes.fromhex("c8f090024a930200050002030900000000100100b800"),20709,"replay")
        self.assertEqual((ground["phase"],ground["vx"]),("inactive_or_unclassified",None))

    # Real 22-byte records, replay capture probe_20260919-164616-e5ae0a (frames 20883..21539).
    RECORDS={0x1A00:"c84ab00236b1020003000203091a8001a00101004000",  # helicopter entering at X 257.6
             0x1C40:"cc7ff904cbf90400010001000004a001f4d8000c3800",  # bullet outside the six checked slots
             0x1400:"c8bafa0473fb04000000000000000000b057007a7200",  # dropped power-up
             0x1700:"e074920236b10200050002030902000000900000b000",  # tank $02:9274
             0x1900:"d80392024a9302000100020309000000307e0000b800",  # tank $02:9203
             0x1980:"9a8da702a0a702000a000203091b80018af800ae5000",  # invisible $02:A78D (flags 9A)
             0x1040:"c0a1f80400000000000000000000000000ef00004e00",  # player hit marker candidate
             0x1000:"c896df04b6e1040008000a000010800280ef00004900",  # the player
             0x1640:"d8dd93022cfc0400060001030f07000000fc00009c00"}  # turret $02:93DD

    def table_ram(self,shift=0):
        data=bytearray(0x20000)
        for base,record in self.RECORDS.items():
            payload=bytearray.fromhex(record)
            x=int.from_bytes(payload[16:19],"little",signed=True)-shift
            payload[16:19]=x.to_bytes(3,"little",signed=True)
            data[base:base+22]=payload
        return data

    def test_a_wrapped_scroll_counter_is_not_a_level_position(self):
        """The level stops scrolling at the boss and 0x007B wraps; 0..65529 was observed there."""
        from brain import combat
        columns={200:{"hit_min_y":174,"safe_max_y":174,"ground_object_y":156.0}}
        with patch.object(combat,"_terrain",(columns,4)):
            self.assertEqual(combat.terrain_at([40,170],760),([174],174,156.0))   # normal scroll
            self.assertEqual(combat.terrain_at([40,170],65529),(None,None,None))
            self.assertEqual(combat.terrain_at([40,170],None),(None,None,None))

    def test_the_level_one_boss_is_classified(self):
        """Confirmed across two boss encounters by measured motion and screenshots."""
        from brain.observations import classify_record
        from brain.combat import TARGETS, KINDS
        def record(routine_hex, flags, byte8=0):
            payload=bytearray(22)
            payload[0]=flags
            payload[1:4]=bytes.fromhex(routine_hex)
            payload[8]=byte8
            return classify_record(payload)
        # Its fire carries the same gating as the known bullet routine.
        self.assertEqual(record("fcc404",0xCC,1),("hostile_projectile",True))
        # Its body parts collide, and Carl reports every one of them is vulnerable, so they
        # are shot at as well as avoided.
        for routine, flags in (("b1c304",0x89),("e6c304",0xC0),("05c004",0xC8),("e6c504",0xD0)):
            self.assertEqual(record(routine,flags),("boss_part",True),routine)
        self.assertIn("boss_part",KINDS)
        self.assertIn("boss_part",TARGETS)
        self.assertEqual(record("59c504",0xC8,3),("enemy_aircraft",True))

    def test_the_fortified_line_past_frame_22400_is_classified(self):
        """Routines confirmed in two long recordings by measured motion and screenshots."""
        from brain.observations import classify_record
        def record(routine_hex, flags, byte8=0):
            payload=bytearray(22)
            payload[0]=flags
            payload[1:4]=bytes.fromhex(routine_hex)
            payload[8]=byte8
            return classify_record(payload)
        # The diagonal shells the aircraft died to in both long runs.
        self.assertEqual(record("499602",0xDC),("hostile_projectile",True))
        self.assertEqual(record("499602",0x00),("hostile_projectile",False))   # gated on its flag byte
        # Gun emplacements of the fortified line.
        for routine, flags in (("1b9502",0xD8),("cd9302",0xD0),("089502",0xD0),("8fb002",0xD8)):
            self.assertEqual(record(routine,flags),("turret",True),routine)
        # The helicopter that sits on the ground and climbs away.
        self.assertEqual(record("5ab002",0xC8),("enemy_aircraft",True))
        # Our own shots travel right at 11 px/frame and are not an enemy of anything.
        self.assertEqual(record("afe604",0xC8)[0],"unclassified")

    def test_the_aircraft_is_told_what_it_has_been_doing(self):
        """Nothing else in the request carries the previous choice, so a multi-move
        commitment cannot be sustained: run 73 reversed left/right for forty decisions."""
        from brain.combat import what_you_have_been_doing, combat_digest, combat_request
        self.assertIsNone(what_you_have_been_doing([]))
        steady=what_you_have_been_doing(["up","left","left","left","left"])
        self.assertEqual(steady["decisions_spent_going_the_same_way"],4)
        self.assertEqual(steady["times_you_reversed_in_those"],0)
        stutter=what_you_have_been_doing(["left","right","left","right"])
        self.assertEqual(stutter["times_you_reversed_in_those"],3)
        self.assertEqual(stutter["decisions_spent_going_the_same_way"],1)
        # Only the last eight are carried, so the fact stays small.
        self.assertEqual(len(what_you_have_been_doing(["up"]*20)["last_choices_oldest_first"]),8)
        body=combat_request(combat_digest({"source_frame":101,"player":{"x":80,"y":112},"tracks":[]},6,
                                          recent_choices=["left","right","left"]))
        self.assertEqual(body["state"]["what_you_have_been_doing"]["times_you_reversed_in_those"],2)

    def test_lingering_in_the_collision_range_is_counted_across_decisions(self):
        """R20 died after four straight decisions at 20-21 px from a tank; each looked fine alone."""
        from brain.combat import time_in_the_collision_range
        self.assertIsNone(time_in_the_collision_range([]))
        self.assertIsNone(time_in_the_collision_range([(f,80.0) for f in range(100,200,6)]))
        lingering=[(21299,20.4),(21305,31.2),(21311,21.6),(21317,21.2),(21323,20.1)]
        report=time_in_the_collision_range(lingering)
        self.assertEqual(report["decisions_inside_the_collision_range"],4)
        self.assertEqual(report["consecutive_decisions_inside_it_now"],3)   # since the 31 px break
        # Leaving the band resets the streak but keeps the history.
        left=time_in_the_collision_range(lingering+[(21329,60.0)])
        self.assertEqual(left["consecutive_decisions_inside_it_now"],0)
        self.assertEqual(left["decisions_inside_the_collision_range"],4)
        # None gaps (nothing tracked) are not counted as safety or as danger.
        self.assertIsNone(time_in_the_collision_range([(100,None),(106,None)]))

    def test_recent_station_keeping_is_reported_from_measured_positions(self):
        """Runs that camped at either extreme scored worst, and no single decision can show it."""
        from brain.combat import where_you_have_been
        forward=[(f,200,112) for f in range(100,400,6)]
        back=[(f,40,112) for f in range(100,400,6)]
        middle=[(f,110,112) for f in range(100,400,6)]
        self.assertEqual(where_you_have_been(forward)["mostly_in"],"the forward third of the flyable area")
        self.assertEqual(where_you_have_been(back)["mostly_in"],"the back third of the flyable area")
        self.assertEqual(where_you_have_been(middle)["mostly_in"],"the middle of the flyable area")
        self.assertEqual(where_you_have_been(forward)["share_of_that_window_in_the_forward_third"],1.0)
        self.assertEqual(where_you_have_been(forward)["frames_sampled"],forward[-1][0]-forward[0][0])
        self.assertIsNone(where_you_have_been([]))          # nothing measured, nothing claimed
        self.assertIsNone(where_you_have_been(forward[:2]))
        body=combat_request(combat_digest({"source_frame":101,"player":{"x":200,"y":112},"tracks":[]},
                                          6,recent_positions=forward))
        self.assertEqual(body["state"]["where_you_have_been_recently"]["median_x"],200)

    def test_a_screen_clearing_power_up_leads_every_option(self):
        """Carl's instruction: on the board, it changes the approach, so it cannot be buried."""
        up={"kind":"clear_screen_power_up","x":136.0,"y":81.0,"vx":-0.47,"vy":0.0,
            "phase":"observed_moving_signature","on_screen":True,"in_play":True,
            "slot":"WRAM:0x1400","generation":1}
        text=combat_request(combat_digest({"source_frame":101,"player":{"x":36,"y":81},
                                           "tracks":[up]},6))["questions"]["movement"]["criteria"]["right"]
        self.assertIn("SCREEN-CLEARING POWER-UP IN PLAY",text)
        self.assertLess(text.index("SCREEN-CLEARING"),text.index("Attack:"))
        self.assertEqual(text.count("SCREEN-CLEARING POWER-UP IN PLAY"),1)
        # With none in play the lead is absent entirely.
        plain=combat_request(combat_digest({"source_frame":101,"player":{"x":36,"y":81},
                                            "tracks":[]},6))["questions"]["movement"]["criteria"]["right"]
        self.assertNotIn("SCREEN-CLEARING",plain)

    def test_reaching_a_power_up_is_judged_over_the_whole_approach(self):
        """A screen-clear power-up 100 px away is 8 moves: no single step shows the payoff."""
        up={"kind":"clear_screen_power_up","x":136.0,"y":81.0,"vx":-0.47,"vy":0.0,
            "phase":"observed_moving_signature","on_screen":True,"in_play":True,
            "slot":"WRAM:0x1400","generation":1}
        digest=combat_digest({"source_frame":101,"player":{"x":36,"y":81},"tracks":[up]},6)
        toward,away=digest["actions"]["right"],digest["actions"]["left"]
        self.assertLess(toward["holding_this_direction_closes_to_px_of_clear_screen_power_up"],20)
        self.assertGreater(away["holding_this_direction_closes_to_px_of_clear_screen_power_up"],
                           toward["holding_this_direction_closes_to_px_of_clear_screen_power_up"])
        text=combat_request(digest)["questions"]["movement"]["criteria"]["right"]
        self.assertIn("holding this direction for those frames closes to",text.lower())

    def test_a_multi_move_transit_is_judged_over_its_whole_path(self):
        """A commitment that pays off in four moves looks bad at every single step."""
        tank={"kind":"ground_tank","x":60.0,"y":176.0,"vx":-0.5,"vy":0.0,
              "phase":"observed_moving_signature","on_screen":True,"in_play":True,
              "slot":"WRAM:0x1840","generation":1}
        digest=combat_digest({"source_frame":101,"player":{"x":140,"y":176},"tracks":[tank]},6)
        left,right=digest["actions"]["left"],digest["actions"]["right"]
        # Flying back gets past it and lines the gun up; flying away never does.
        self.assertTrue(left["holding_this_direction_reaches_a_shot_on_it"])
        self.assertFalse(right["holding_this_direction_reaches_a_shot_on_it"])
        # The path's tightest gap is reported, and closing on the tank is tighter than fleeing it.
        self.assertIsNotNone(left["tightest_gap_if_this_direction_is_held_px"])
        self.assertLess(left["tightest_gap_if_this_direction_is_held_px"],
                        right["tightest_gap_if_this_direction_is_held_px"])
        text=combat_request(digest)["questions"]["movement"]["criteria"]["left"]
        self.assertIn("tightest gap of",text)
        # Getting past it is only half the move: the drop onto its firing line is counted.
        self.assertIn("getting past it and onto its firing line takes about",text)
        self.assertEqual(left["frames_to_drop_onto_its_line"],0)      # already level with it
        self.assertEqual(left["frames_to_get_past_it_and_onto_its_line"],
                         left["frames_to_get_behind_nearest_target_behind"])

    def test_targets_about_to_slip_behind_are_forecast_before_they_do(self):
        """Once something is behind, the gun cannot reach it; the crossing is the moment that matters."""
        track={"kind":"enemy_aircraft","x":130.0,"y":112.0,"vx":-1.8,"vy":0.0,
               "phase":"observed_moving_signature","on_screen":True,"in_play":True,
               "slot":"WRAM:0x1840","generation":1}
        digest=combat_digest({"source_frame":101,"player":{"x":110,"y":112},"tracks":[track]},6)
        hold=digest["actions"]["hold"]
        self.assertEqual(hold["targets_that_will_slip_behind_you"],1)
        self.assertLess(hold["first_slips_behind_in_frames"],30)
        # Moving back buys frames before the same target crosses.
        self.assertGreater(digest["actions"]["left"]["first_slips_behind_in_frames"],
                           hold["first_slips_behind_in_frames"])
        # Something already behind is not double-counted as about to cross.
        past={**track,"x":80.0}
        behind_digest=combat_digest({"source_frame":101,"player":{"x":110,"y":112},"tracks":[past]},6)
        self.assertEqual(behind_digest["actions"]["hold"]["targets_that_will_slip_behind_you"],0)
        self.assertIn("pass behind you",combat_request(digest)["questions"]["movement"]["criteria"]["hold"])

    def test_power_up_reach_and_expiry_are_reported_in_frames(self):
        """A power-up 24 px away was abandoned because nothing said how little time it had left."""
        track={"kind":"power_up","x":56.0,"y":145.0,"vx":-0.5,"vy":0.0,"phase":"observed_moving_signature",
               "on_screen":True,"in_play":True,"slot":"WRAM:0x1400","generation":1}
        digest=combat_digest({"source_frame":101,"player":{"x":96,"y":145},"tracks":[track]},6)
        hold=digest["actions"]["hold"]
        # It leaves play once it passes the tracked margin off the left edge.
        self.assertAlmostEqual(hold["frames_until_power_up_leaves_play"],round((56+32)/0.5),delta=2)
        self.assertAlmostEqual(hold["frames_to_reach_power_up"],
                               round(hold["power_up_closest_px"]/2.5),delta=1)
        text=combat_request(digest)["questions"]["movement"]["criteria"]["hold"]
        self.assertIn("frames of flying away",text)
        self.assertIn("drifts out of play in about",text)

    def test_room_is_reported_as_time_against_what_is_actually_closing(self):
        """The same pixels of room are a long warning against a tank and none against a helicopter."""
        def room(vx):
            track={"kind":"enemy_aircraft","x":240.0,"y":112.0,"vx":vx,"vy":0.0,
                   "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                   "slot":"WRAM:0x1840","generation":1}
            obs={"source_frame":101,"player":{"x":180,"y":112},"tracks":[track]}
            digest=combat_digest(obs,6,entry_edges={"right":5})
            return digest["actions"]["hold"]
        slow,fast=room(-0.5),room(-2.0)
        self.assertEqual(slow["warning_room_px"],fast["warning_room_px"])   # identical pixels
        self.assertGreater(slow["warning_time_frames"],fast["warning_time_frames"]*3)
        # Falling back is flying, so the buffer behind is time too.
        self.assertAlmostEqual(fast["retreat_time_frames"],round(fast["retreat_room_px"]/2.5),delta=1)
        text=combat_request(combat_digest({"source_frame":101,"player":{"x":180,"y":112},
            "tracks":[{"kind":"enemy_aircraft","x":240.0,"y":112.0,"vx":-2.0,"vy":0.0,
                       "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                       "slot":"WRAM:0x1840","generation":1}]},6,entry_edges={"right":5}))["questions"]["movement"]["criteria"]["hold"]
        self.assertIn("frames of warning",text)

    def test_going_back_for_a_ground_target_counts_the_drop_as_well(self):
        """Run 87 was told 'this does not line up a shot' at every decision with a tank
        behind it, because flying back never changes altitude. The move is back, then down."""
        from brain.combat import combat_digest, combat_request
        tank={"kind":"ground_tank","x":60.0,"y":180.0,"vx":-0.5,"vy":0.0,
              "phase":"observed_moving_signature","on_screen":True,"in_play":True,
              "slot":"WRAM:0x1840","generation":1}
        high=combat_digest({"source_frame":101,"player":{"x":140,"y":110},"tracks":[tank]},6)["actions"]["left"]
        self.assertGreater(high["frames_to_drop_onto_its_line"],20)     # 70 px above its line
        self.assertEqual(high["frames_to_get_past_it_and_onto_its_line"],
                         high["frames_to_get_behind_nearest_target_behind"]+high["frames_to_drop_onto_its_line"])
        level=combat_digest({"source_frame":101,"player":{"x":140,"y":178},"tracks":[tank]},6)["actions"]["left"]
        self.assertEqual(level["frames_to_drop_onto_its_line"],0)
        text=combat_request(combat_digest({"source_frame":101,"player":{"x":140,"y":110},
                                           "tracks":[tank]},6))["questions"]["movement"]["criteria"]["left"]
        self.assertIn("of which",text)
        self.assertIn("are the drop onto its altitude",text)

    def test_cost_of_going_back_for_a_target_is_reported_in_frames(self):
        """Distance alone cannot say whether a target behind is catchable; speed decides it."""
        def behind(kind,vx):
            track={"kind":kind,"x":60.0,"y":112.0,"vx":vx,"vy":0.0,"phase":"observed_moving_signature",
                   "on_screen":True,"in_play":True,"slot":"WRAM:0x1840","generation":1}
            obs={"source_frame":101,"player":{"x":150,"y":112},"tracks":[track]}
            digest=combat_digest(obs,6)
            return digest["actions"]["hold"],combat_request(digest)["questions"]["movement"]["criteria"]["hold"]
        # A tank drifting with the scroll is caught in well under a second of play.
        option,text=behind("ground_tank",-0.5)
        self.assertEqual(option["nearest_target_behind_kind"],"ground_tank")
        self.assertAlmostEqual(option["frames_to_get_behind_nearest_target_behind"],
                               round(option["pixels_to_pass_nearest_behind"]/2.0),delta=1)
        self.assertIn("takes about",text)
        # A helicopter running left at nearly the aircraft's own speed costs far more frames
        # than the forecast window, so the cost is visible rather than hidden behind a distance.
        option,_=behind("enemy_aircraft",-2.4)
        self.assertGreater(option["frames_to_get_behind_nearest_target_behind"],300)
        # Matching or beating the aircraft's own speed makes it uncatchable outright.
        option,text=behind("enemy_aircraft",-2.6)
        self.assertIsNone(option["frames_to_get_behind_nearest_target_behind"])
        self.assertIn("cannot be caught",text)

    def test_scroll_drift_is_measured_despite_a_fixed_decision_cadence(self):
        """An object stationary in the level moves 1 px every other frame with the scroll.

        Sampling a one-frame difference on a fixed cadence always lands on the same parity
        and reads exactly 0, which told Jev a drifting power-up was parked.
        """
        tracker=TableTracker()
        seen=[]
        for frame in range(100,160):
            # Half a pixel per frame, stored as whole pixels: 1 px every other frame.
            tracks={t["slot"]:t for t in tracker.observe(self.table_ram(shift=256*((frame-100)//2)),frame,"unit")}
            turret=next(t for t in tracks.values() if t["kind"]=="turret")
            if frame>=130 and (frame-100)%6==0:      # the decision cadence, always one parity
                seen.append(turret["vx"])
        self.assertTrue(seen)
        for vx in seen:
            self.assertAlmostEqual(vx,-0.5,delta=0.05)

    def test_object_table_types_records_by_routine_address(self):
        tracker=TableTracker()
        tracker.observe(self.table_ram(),100,"unit")
        tracks={t["slot"]:t for t in tracker.observe(self.table_ram(shift=256),101,"unit")}
        self.assertEqual({s:t["kind"] for s,t in tracks.items()},
                         {"WRAM:0x1A00":"enemy_aircraft","WRAM:0x1C40":"hostile_projectile","WRAM:0x1400":"power_up",
                          "WRAM:0x1700":"ground_tank","WRAM:0x1900":"ground_tank","WRAM:0x1640":"turret"})
        entering=tracks["WRAM:0x1A00"]
        self.assertEqual((entering["on_screen"],entering["in_play"],entering["vx"]),(False,True,-1.0))
        self.assertEqual(entering["routine"],"$02:B04A")

    def test_digest_counts_entering_aircraft_and_scores_power_up_and_tanks(self):
        tracker=TableTracker()
        tracker.observe(self.table_ram(),100,"unit")
        obs={"source_frame":101,"player":{"x":60,"y":112},"tracks":tracker.observe(self.table_ram(shift=256),101,"unit")}
        digest=combat_digest(obs,30)
        self.assertEqual((digest["enemy_count"],digest["projectile_count"],digest["power_up_count"],digest["tank_count"],digest["turret_count"]),(1,1,1,2,1))
        actions=digest["actions"]
        # The power-up is ahead and lower (87.7,114.5): moving right approaches it more than moving up.
        self.assertLess(actions["right"]["power_up_closest_px"],actions["up"]["power_up_closest_px"])
        # Tanks sit near Y 176..184: moving down lines the gun up better than moving up.
        self.assertLess(actions["down"]["tank_firing_line_error_px"],actions["up"]["tank_firing_line_error_px"])
        body=combat_request(digest)
        self.assertIn("power-up",body["questions"]["movement"]["criteria"]["right"])
        self.assertIn("ground-tank firing-line error",body["questions"]["movement"]["criteria"]["down"])
        self.assertEqual(body["state"]["known_tracks"],{"aircraft":1,"bullets":1,"power_ups":1,"tanks":2,"turrets":1,"screen_clearing_power_ups":0})

    def test_tanks_are_collision_bodies_and_absent_kinds_read_none_tracked(self):
        tracker=TableTracker()
        tracker.observe(self.table_ram(),100,"unit")
        tracks=[t for t in tracker.observe(self.table_ram(shift=256),101,"unit") if t["kind"] in ("ground_tank","power_up")]
        digest=combat_digest({"source_frame":101,"player":{"x":126,"y":150},"tracks":tracks},30)
        # The tank at (125.2,184) sits right below: descending onto it closes the body gap.
        self.assertLess(digest["actions"]["down"]["enemy_body_anchor_gap_px"],digest["actions"]["up"]["enemy_body_anchor_gap_px"])
        text=combat_request(digest)["questions"]["movement"]["criteria"]["hold"]
        self.assertIn("Bullet-reference gap: none tracked",text)
        self.assertNotIn("unknown (not evidence",text)
        # The option leads with the single smallest gap to any tracked threat, and names edges it ends on.
        self.assertTrue(text.startswith("No directional buttons. Closest tracked threat: 26.0 pixels (aircraft or tank, below, right)."),text)
        # Inside the measured collision range, the option says so.
        tight=combat_digest({"source_frame":101,"player":{"x":120,"y":180},"tracks":tracks},6)
        self.assertIn("inside the range where collisions have happened",
                      combat_request(tight)["questions"]["movement"]["criteria"]["hold"])
        self.assertIn("the right edge",edge_words([239,48]))
        self.assertIn("top edge",edge_words([239,48]))
        self.assertEqual(edge_words([120,112]),"")

    def test_shot_geometry_uses_measured_speed_and_only_reachable_targets(self):
        def target(x,y,vx=0.0,vy=0.0,kind="enemy_aircraft"): return {"x":x,"y":y,"vx":vx,"vy":vy,"kind":kind}
        # 110 px ahead and level: the 11 px/frame shot lands in 10 frames.
        self.assertEqual(shot_intersections([50,112],[target(160,112)],6),[(10.0,"enemy_aircraft",160)])
        # Behind, out of the vertical band, off the right edge, or outrunning the shot: no hit.
        for miss in (target(20,112),target(160,140),target(300,112),target(160,112,vx=12.0)):
            self.assertEqual(shot_intersections([50,112],[miss],6),[])
        # A target drifting into the band while the shot travels still counts.
        self.assertEqual(shot_intersections([50,112],[target(160,132,vy=-2.0)],6)[0][1],"enemy_aircraft")
        self.assertEqual(shot_intersections(None,[target(160,112)],6),[])
        # With no immediate hit, the aim error says how far off the gun line the target is.
        self.assertEqual(aim_error([50,112],[target(160,140)],6),(28.0,10.0))
        self.assertIsNone(aim_error([50,112],[target(20,112)],6))
        # A target flying left toward the aircraft will cross the gun line; one already behind will not.
        self.assertEqual(future_shots([50,112],[target(200,112,vx=-2.0)])[0],1)
        self.assertEqual(future_shots([50,112],[target(20,112,vx=-2.0)])[0],0)
        # The field map covers the flyable area with an opportunity and a danger number per cell.
        cells=field_forecast([target(200,112,vx=-2.0)],[target(200,112,vx=-2.0)])
        self.assertEqual(len(cells),32)
        self.assertEqual({tuple(c["xy"]) for c in cells} & {(16,48),(239,191)},{(16,48),(239,191)})
        # Rows are close enough together to see a firing line, and the best cell is level with the target.
        self.assertLessEqual(max(b-a for a,b in zip(sorted({c["xy"][1] for c in cells}),sorted({c["xy"][1] for c in cells})[1:])),21)
        best=max(cells,key=lambda c:c["targets_into_line"])
        self.assertTrue(best["targets_into_line"])
        self.assertLessEqual(abs(best["xy"][1]-112),11)
        # Room is measured from whichever edge objects have actually been entering from.
        self.assertEqual(warning_room([200,112],{"right":9,"left":1}),(56.0,"right"))
        self.assertEqual(warning_room([200,112],{"left":4}),(200.0,"left"))
        self.assertEqual(warning_room([200,112],{}),(None,None))
        # Room behind, measured to the far bound away from the entry side.
        self.assertEqual(retreat_room([16,112],{"right":9}),0.0)
        self.assertEqual(retreat_room([40,112],{"right":9}),24.0)

    def test_option_reports_the_threat_that_arrives_after_the_move(self):
        tracker=TableTracker()
        tracker.observe(self.table_ram(),100,"unit")
        # The tank closes 1 px per frame: six frames look clear, thirty do not.
        tracks=[t for t in tracker.observe(self.table_ram(shift=256),101,"unit") if t["kind"]=="ground_tank"]
        digest=combat_digest({"source_frame":101,"player":{"x":100,"y":176},"tracks":tracks},6)
        hold=digest["actions"]["hold"]
        self.assertGreater(hold["enemy_body_anchor_gap_px"],hold["threat_gap_if_you_hold_px"])
        self.assertIn("Staying there afterwards",combat_request(digest)["questions"]["movement"]["criteria"]["hold"])

    def test_measured_terrain_is_reported_and_unmeasured_stays_unknown(self):
        from brain import combat
        columns={200:{"hit_min_y":174,"safe_max_y":174,"ground_object_y":156.0},
                 201:{"hit_min_y":None,"safe_max_y":160,"ground_object_y":None}}
        with patch.object(combat,"_terrain",(columns,4)):
            self.assertEqual(combat.terrain_at([40,170],760),([174],174,156.0))   # level column 200
            self.assertEqual(combat.terrain_at([40,170],9000),(None,None,None))  # nothing measured out there
            tracker=TableTracker(); tracker.observe(self.table_ram(),100,"unit")
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":170},
                 "tracks":tracker.observe(self.table_ram(shift=256),101,"unit")}
            text=combat.combat_request(combat.combat_digest(obs,6))["questions"]["movement"]["criteria"]["hold"]
            self.assertIn("A terrain collision was recorded here at Y 174",text)
            # A ground target's altitude is where the gun must be to hit it, not a floor.
            self.assertIn("Ground targets stand at Y 156 here",text)
            self.assertIn("firing line, not a floor",text)
            # Ending at or below a RECORDED collision altitude is called out as disqualifying.
            self.assertIn("TERRAIN: this ends at Y 170, level with an altitude where a collision was actually "
                          "recorded",text)
            # A column where only a ground object stands is not a floor: flying its line stays allowed.
            only_object={202:{"hit_min_y":None,"safe_max_y":187,"ground_object_y":176.0}}
            with patch.object(combat,"_terrain",(only_object,4)):
                low={"source_frame":101,"scroll_x":768,"player":{"x":40,"y":176},"tracks":[]}
                digest=combat.combat_digest(low,6)
                self.assertIsNone(digest["actions"]["hold"]["terrain_floor_y"])
                self.assertFalse(any(o["ends_at_or_below_terrain"] for o in digest["actions"].values()))
            high={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":90},"tracks":[]}
            self.assertNotIn("TERRAIN:",combat.combat_request(combat.combat_digest(high,6))["questions"]["movement"]["criteria"]["hold"])

    def test_the_firing_band_matches_what_has_actually_killed_each_kind(self):
        """Run 73 held Y 180 for 40 decisions while its shots sailed over tanks at Y 188."""
        from brain.combat import combat_digest, on_the_gun_line
        # Measured: ground targets are hit from level to about 10 px below, and the rate
        # at 8 px above is 5.8%, where the old symmetric band claimed a hit.
        self.assertFalse(on_the_gun_line(180,188,"ground_tank"))   # 8 px above: the stutter
        self.assertTrue(on_the_gun_line(188,188,"ground_tank"))    # level: 54%
        self.assertTrue(on_the_gun_line(194,188,"ground_tank"))    # 6 px below: 96%
        self.assertFalse(on_the_gun_line(200,188,"ground_tank"))   # too far below
        self.assertTrue(on_the_gun_line(180,188,"enemy_aircraft")) # aircraft tolerate it
        tank={"kind":"ground_tank","x":200.0,"y":188.0,"vx":-0.5,"vy":0.0,
              "phase":"observed_moving_signature","on_screen":True,"in_play":True,
              "slot":"WRAM:0x1840","generation":1}
        high=combat_digest({"source_frame":101,"player":{"x":80,"y":180},"tracks":[tank]},6)
        self.assertEqual(high["actions"]["hold"]["targets_the_gun_would_hit"],0)
        level=combat_digest({"source_frame":101,"player":{"x":80,"y":190},"tracks":[tank]},6)
        self.assertEqual(level["actions"]["hold"]["targets_the_gun_would_hit"],1)

    def test_a_target_about_to_be_lost_is_reported_with_its_clock(self):
        """Runs destroy about 40% of the units they meet; the rest leave alive."""
        from brain.combat import combat_digest, combat_request
        # Well below the gun line and heading for the left edge: it will never be shot.
        missed={"kind":"enemy_aircraft","x":90.0,"y":190.0,"vx":-1.5,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":"WRAM:0x1840","generation":1}
        digest=combat_digest({"source_frame":101,"player":{"x":60,"y":100},"tracks":[missed]},6)
        hold=digest["actions"]["hold"]
        self.assertEqual(hold["targets_leaving_unshot"],1)
        self.assertAlmostEqual(hold["soonest_one_leaves_in_frames"],round((90+32)/1.5),delta=2)
        self.assertIn("without ever crossing the gun's line",
                      combat_request(digest)["questions"]["movement"]["criteria"]["hold"])
        # Dropping onto its line means it is no longer being lost.
        lined_up=combat_digest({"source_frame":101,"player":{"x":60,"y":190},"tracks":[missed]},6)
        self.assertEqual(lined_up["actions"]["hold"]["targets_leaving_unshot"],0)

    def test_measured_danger_comes_from_what_happened_to_past_runs(self):
        """Every frame ever flown is evidence, which covers far more than collisions do."""
        from brain import combat
        cells={"100,22":{"frames":80,"deaths_soon_after":44,"hits_soon_after":60},  # the deck
               "100,12":{"frames":300,"deaths_soon_after":0,"hits_soon_after":0}}   # mid screen
        with patch.object(combat,"_danger",(cells,8,8,60,30)):
            deadly=combat.danger_at([40,180],760)               # column 100, altitude 22
            self.assertEqual(deadly["frames_flown_here_in_past_runs"],80)
            self.assertEqual(deadly["how_many_were_within_a_second_of_being_destroyed"],44)
            safe=combat.danger_at([40,100],760)                 # column 100, altitude 12
            self.assertEqual(safe["how_many_were_within_a_second_of_being_destroyed"],0)
            self.assertIsNone(combat.danger_at([40,60],760))    # never flown enough: unknown
            self.assertIsNone(combat.danger_at([40,180],65529)) # wrapped scroll
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":180},"tracks":[]}
            text=combat.combat_request(combat.combat_digest(obs,6))["questions"]["movement"]["criteria"]["hold"]
            self.assertIn("Past runs flew 80 frames at this exact position",text)
            self.assertIn("44 of those frames came within 60 frames",text)
            # Hits are the denser signal: several per run against one death.
            self.assertEqual(deadly["how_many_were_just_before_taking_a_hit"],60)
            self.assertIn("60 came within 30 frames of it taking a hit",text)

    def test_the_boss_hull_is_reported_separately_from_its_fire(self):
        """Carl's method needs both: its fire wants you low, its hull wants you off the deck."""
        from brain.combat import boss_body, combat_request, combat_digest
        parts=[{"kind":"boss_part","x":float(x),"y":float(y),"vx":-1.0,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":f"WRAM:0x15{x:02X}","generation":1}
               for x,y in ((160,128),(180,144),(200,192))]
        body=boss_body([120,180],parts)
        self.assertEqual(body["top_of_the_hull_y"],128)
        self.assertEqual(body["its_front_edge_x"],160)
        self.assertTrue(body["you_are_level_with_the_hull"])        # on the deck, it can crush
        self.assertFalse(boss_body([120,100],parts)["you_are_level_with_the_hull"])
        self.assertIsNone(boss_body([120,180],[]))
        state=combat_request(combat_digest({"source_frame":101,"player":{"x":120,"y":180},
                                            "tracks":parts},6))["state"]
        self.assertEqual(state["boss_body"]["top_of_the_hull_y"],128)

    def test_the_boss_hull_is_reported_separately_from_its_fire(self):
        """Carl's method needs both: the fire wants the aircraft low, the hull can crush it there."""
        from brain.combat import boss_body, combat_request, combat_digest
        parts=[{"kind":"boss_part","x":float(x),"y":float(y),"vx":-1.0,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":f"WRAM:0x15{x:02X}","generation":1}
               for x,y in ((160,128),(180,144),(200,192))]
        body=boss_body([120,180],parts)
        self.assertEqual(body["top_of_the_hull_y"],128)
        self.assertEqual(body["its_front_edge_x"],160)
        self.assertTrue(body["you_are_level_with_the_hull"])
        self.assertFalse(boss_body([120,100],parts)["you_are_level_with_the_hull"])
        self.assertIsNone(boss_body([120,180],[]))
        state=combat_request(combat_digest({"source_frame":101,"player":{"x":120,"y":180},
                                            "tracks":parts},6))["state"]
        self.assertEqual(state["boss_body"]["top_of_the_hull_y"],128)

    def test_the_quietest_altitude_is_reported(self):
        """Boss fire sits between Y 120 and 144 in about a thousand frames per band and is
        almost absent above Y 112, while attempts kept dying at Y 176 to 183."""
        from brain.combat import quietest_altitude, combat_request, combat_digest
        fire=[{"kind":"hostile_projectile","x":180.0,"y":float(y),"vx":-3.5,"vy":0.0,
               "phase":"observed_moving_signature","on_screen":True,"in_play":True,
               "slot":"WRAM:0x1B00","generation":1} for y in (120,128,136,144)]
        quiet=quietest_altitude([100,140],fire)
        self.assertLess(quiet["altitude"],112)            # above the band the fire occupies
        self.assertGreater(quiet["clearance_px"],20)
        self.assertGreater(quiet["frames_to_reach_it"],0)
        self.assertIsNone(quietest_altitude(None,fire))
        self.assertIsNone(quietest_altitude([100,140],[]))
        body=combat_request(combat_digest({"source_frame":101,"player":{"x":100,"y":140},
                                           "tracks":fire},6))
        self.assertLess(body["state"]["quietest_altitude_right_now"]["altitude"],112)

    def test_the_gap_to_slip_west_through_is_measured(self):
        """Carl: when they come at you above and below, there is a thread in the middle to
        traverse west and get behind them, and it has never been taken."""
        from brain.combat import lane_going_back, combat_digest, combat_request
        def threat(y):
            return {"kind":"enemy_aircraft","x":150.0,"y":float(y),"vx":-1.5,"vy":0.0,
                    "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                    "slot":"WRAM:0x1840","generation":1}
        pair=[threat(70),threat(170)]
        lane=lane_going_back([100,120],pair)
        self.assertEqual(lane["altitude"],120)          # the gap between them
        self.assertGreater(lane["width_px"],50)
        self.assertEqual(lane["how_far_you_are_from_it_px"],0)
        self.assertIsNone(lane_going_back([100,120],[]))         # nothing coming
        self.assertIsNone(lane_going_back(None,pair))
        text=combat_request(combat_digest({"source_frame":101,"player":{"x":100,"y":120},
                                           "tracks":pair},6))["questions"]["movement"]["criteria"]["hold"]
        self.assertIn("widest gap through what is coming",text)
        self.assertIn("ends up west of them",text)

    def test_the_altitude_a_ground_target_needs_is_stated(self):
        """Runs have spent a hundred decisions shooting over a tank without being told how
        low the shot has to be, and some tanks sit below the altitude that can be flown."""
        from brain.combat import combat_digest, combat_request
        def ground(y):
            t={"kind":"ground_tank","x":200.0,"y":float(y),"vx":-0.5,"vy":0.0,
               "phase":"observed_moving_signature","on_screen":True,"in_play":True,
               "slot":"WRAM:0x1840","generation":1}
            d=combat_digest({"source_frame":101,"player":{"x":80,"y":150},"tracks":[t]},6)
            return d["actions"]["hold"], combat_request(d)["questions"]["movement"]["criteria"]["hold"]
        option,text=ground(182)
        self.assertEqual(option["altitude_that_hits_the_nearest_ground_target"],[176,192])
        self.assertEqual(option["pixels_too_high_for_it"],26)       # sitting at Y 150
        self.assertIn("hit from Y 176 to 192",text)
        self.assertIn("26 pixels above that: dropping that far lines it up",text)
        # Carl: a ground target is always reachable, you just drop a little. A tank on the
        # deck is hit from inside the flyable range, so nothing is written off.
        option,_=ground(196)
        low,high=option["altitude_that_hits_the_nearest_ground_target"]
        self.assertLessEqual(low,191)

    def test_a_wall_found_this_run_is_remembered_by_position(self):
        """A third of the shots fired along a ground target's line in R89 stopped short of
        it. A wall does not move, so finding it once should be enough for the whole run."""
        from brain.combat import combat_digest, found_blocked
        found={(int((150+800)//4), 112): 2}        # a wall at level x 950, altitude 112
        self.assertTrue(found_blocked([60,112],200,800,found))
        # One stop is not a wall: it can be an unclassified enemy that was hit and lived.
        self.assertFalse(found_blocked([60,112],200,800,{(int((150+800)//4), 112): 1}))
        self.assertFalse(found_blocked([60,60],200,800,found))    # different altitude
        self.assertFalse(found_blocked([60,112],100,800,found))   # stops before the wall
        self.assertFalse(found_blocked([60,112],200,800,None))
        target={"kind":"enemy_aircraft","x":200.0,"y":112.0,"vx":-1.0,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":"WRAM:0x1840","generation":1}
        obs={"source_frame":101,"scroll_x":800,"player":{"x":60,"y":112},"tracks":[target]}
        self.assertEqual(combat_digest(obs,6)["actions"]["hold"]["targets_the_gun_would_hit"],1)
        blocked=combat_digest(obs,6,walls_found_this_run=found)
        self.assertEqual(blocked["actions"]["hold"]["targets_the_gun_would_hit"],0)

    def test_shots_stopping_short_reject_the_firing_line_live(self):
        """Carl watched forty-five decisions spent firing into a wall the map did not know,
        while four killable targets sat on screen. The game was saying so every few frames."""
        from brain.combat import combat_digest, combat_request, wall_in_front_of_you
        stops=[(100,150,112),(103,151,112),(106,149,113)]
        self.assertIsNone(wall_in_front_of_you(stops,60))         # a different altitude
        self.assertIsNone(wall_in_front_of_you(stops[:1],112))    # one stop is not a wall
        wall=wall_in_front_of_you(stops,112)
        self.assertEqual(wall["shots_stopped_recently"],3)
        self.assertEqual(wall["nearest_stop_x"],149)
        target={"kind":"enemy_aircraft","x":200.0,"y":112.0,"vx":-1.0,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":"WRAM:0x1840","generation":1}
        obs={"source_frame":101,"player":{"x":60,"y":112},"tracks":[target]}
        # Without the evidence the target reads as hittable; with it, it does not.
        self.assertEqual(combat_digest(obs,6)["actions"]["hold"]["targets_the_gun_would_hit"],1)
        blocked=combat_digest(obs,6,recent_shot_stops=stops)
        self.assertEqual(blocked["actions"]["hold"]["targets_the_gun_would_hit"],0)
        text=combat_request(blocked)["questions"]["movement"]["criteria"]["hold"]
        self.assertIn("stopped short",text)
        self.assertIn("nothing beyond it can be hit",text)

    def test_the_gun_cannot_shoot_through_a_structure(self):
        """Carl: you cannot fire through structures to reach enemies on the other side."""
        from brain import combat
        target={"kind":"enemy_aircraft","x":200.0,"y":112.0,"vx":-1.0,"vy":0.0,
                "phase":"observed_moving_signature","on_screen":True,"in_play":True,
                "slot":"WRAM:0x1840","generation":1}
        # A structure at the aircraft's own altitude, between it and the target.
        wall={c:{"hit_min_y":None,"collision_altitudes":None,"safe_max_y":None,
                 "ground_object_y":None,"shots_stopped_at":[112]} for c in range(230,240)}
        with patch.object(combat,"_terrain",(wall,4)):
            obs={"source_frame":101,"scroll_x":800,"player":{"x":60,"y":112},"tracks":[target]}
            hold=combat.combat_digest(obs,6)["actions"]["hold"]
            self.assertEqual(hold["targets_the_gun_would_hit"],0)
            self.assertEqual(hold["targets_hidden_behind_structure"],1)
            text=combat.combat_request(combat.combat_digest(obs,6))["questions"]["movement"]["criteria"]["hold"]
            self.assertIn("sit behind a structure from here",text)
        # With the structure at another altitude the same shot connects.
        clear={c:{"hit_min_y":None,"collision_altitudes":None,"safe_max_y":None,
                  "ground_object_y":None,"shots_stopped_at":[60]} for c in range(230,240)}
        with patch.object(combat,"_terrain",(clear,4)):
            obs={"source_frame":101,"scroll_x":800,"player":{"x":60,"y":112},"tracks":[target]}
            hold=combat.combat_digest(obs,6)["actions"]["hold"]
            self.assertEqual(hold["targets_the_gun_would_hit"],1)
            self.assertEqual(hold["targets_hidden_behind_structure"],0)

    def test_a_blocked_option_says_so_before_anything_else(self):
        """Every untracked hit past frame 22400 happened where the map already had evidence."""
        from brain import combat
        columns={c:{"hit_min_y":174,"collision_altitudes":[174],"safe_max_y":191,
                    "ground_object_y":None,"shots_stopped_at":[174]} for c in range(150,260)}
        with patch.object(combat,"_terrain",(columns,4)):
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":174},"tracks":[]}
            criteria=combat.combat_request(combat.combat_digest(obs,6))["questions"]["movement"]["criteria"]
            self.assertTrue(criteria["hold"].startswith("No directional buttons. BLOCKED ("),criteria["hold"][:90])
            self.assertIn("Y 174 on this path, where a collision was recorded",criteria["hold"])
            # The warning always carries a gradient, so a blocked option can still be compared.
            self.assertIn("BLOCKED (0 px clear)",criteria["hold"])
            # An option that climbs clear of the band is not labelled blocked.
            self.assertNotIn("BLOCKED",criteria["up"])

    def test_when_every_option_is_blocked_the_least_bad_one_is_named(self):
        """In 11% of decisions four or five options were blocked, with no way to choose."""
        from brain import combat
        columns={c:{"hit_min_y":None,"collision_altitudes":None,"safe_max_y":191,
                    "ground_object_y":None,"shots_stopped_at":[160,174,188]} for c in range(150,260)}
        with patch.object(combat,"_terrain",(columns,4)):
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":174},"tracks":[]}
            digest=combat.combat_digest(obs,6)
            self.assertTrue(all(o["ends_level_with_something_that_stopped_a_shot"]
                                for o in digest["actions"].values()))
            self.assertIn("the most clearance is",digest["every_option_is_blocked"])
            gaps={a:o["distance_to_nearest_blocked_altitude_px"] for a,o in digest["actions"].items()}
            self.assertEqual(min(gaps.values()),0)          # holding sits on one
            self.assertGreater(max(gaps.values()),0)        # something is further from the band

    def test_a_stopped_shot_maps_structure_where_no_collision_was_ever_taken(self):
        """Shots fly straight at 11 px/frame; one that stops short has hit something solid."""
        from brain import combat
        columns={c:{"hit_min_y":None,"collision_altitudes":None,"safe_max_y":None,
                    "ground_object_y":None,"shots_stopped_at":[176]} for c in range(150,260)}
        with patch.object(combat,"_terrain",(columns,4)):
            self.assertEqual(combat.blocked_altitudes([40,170],760),[176])
            self.assertIsNone(combat.blocked_altitudes([40,170],65529))     # wrapped scroll
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":176},"tracks":[]}
            digest=combat.combat_digest(obs,6)
            self.assertTrue(digest["actions"]["hold"]["ends_level_with_something_that_stopped_a_shot"])
            self.assertFalse(digest["actions"]["up"]["ends_level_with_something_that_stopped_a_shot"])
            text=combat.combat_request(digest)["questions"]["movement"]["criteria"]["hold"]
            self.assertIn("STRUCTURE: shots fired along this path have been stopped at Y 176",text)
            # No collision was ever recorded here, so it must not claim one.
            self.assertNotIn("collision was actually recorded",text)

    def test_a_structure_is_an_altitude_band_not_a_floor(self):
        """At one measured column a collision happened at Y 171 while Y 189 was flown safely."""
        from brain import combat
        columns={c:{"hit_min_y":171,"collision_altitudes":[171],"safe_max_y":189,
                    "ground_object_y":None} for c in range(150,260)}
        with patch.object(combat,"_terrain",(columns,4)):
            obs={"source_frame":101,"scroll_x":760,"player":{"x":40,"y":171},"tracks":[]}
            digest=combat.combat_digest(obs,6)
            # Holding at the recorded altitude is flagged; flying under it is not.
            self.assertTrue(digest["actions"]["hold"]["ends_at_or_below_terrain"])
            self.assertFalse(digest["actions"]["down"]["ends_at_or_below_terrain"])
            self.assertFalse(digest["actions"]["up"]["ends_at_or_below_terrain"])
            text=combat.combat_request(digest)["questions"]["movement"]["criteria"]["hold"]
            self.assertIn("level with an altitude where a collision was actually recorded",text)
            self.assertIn("structure to go around or over, not a floor",text)

    def test_lua_object_table_matches_python(self):
        source=(Path(player.ROOT) / "lua" / "main.lua").read_text()
        match=re.search(r"local TABLE_START, TABLE_STRIDE, TABLE_COUNT, RECORD_BYTES = (\w+), (\w+), (\w+), (\w+)",source)
        start,stride,count,record=(int(v,0) for v in match.groups())
        self.assertEqual((tuple(range(start,start+stride*count,stride)),record),(TABLE_BASES,RECORD_BYTES))

    def test_lua_export_matches_checked_slot_lists(self):
        source=(Path(player.ROOT) / "lua" / "main.lua").read_text()
        for name,bases in (("projectile_bases",PROJECTILE_BASES),("enemy_bases",ENEMY_BASES)):
            match=re.search(r"local "+name+r" = \{([^}]*)\}",source)
            self.assertEqual(tuple(int(v,16) for v in match.group(1).split(",")),bases)

    def test_combat_request_is_explicit_partial_geometry_and_same_action_horizon(self):
        tracker=CombatTracker()
        state=fixture()
        tracker.observe_bridge(state)
        obs={"source_frame":102,"player":{"x":96,"y":112},
             "tracks":tracker.observe_bridge(dict(state,frame=102))}
        digest=combat_digest(obs,30)
        body=combat_request(digest)
        self.assertEqual(set(body["questions"]["movement"]["criteria"]),set(ACTIONS))
        self.assertEqual(body["state"]["action_horizon_game_frames"],30)
        self.assertEqual(digest["enemy_count"],1)
        self.assertFalse(digest["complete_hazard_coverage"])
        self.assertIsNotNone(digest["actions"]["hold"]["firing_alignment_error_px"])
        self.assertIn("not hitboxes",body["state"]["uncertainty"])
        self.assertIn("9 to 22 pixels",body["state"]["uncertainty"])

    def test_distribution_validation_does_not_make_confidence_override(self):
        answer={"answers":{"movement":{"choice":"up","confidence":0.01,
                 "probabilities":{a:0.2 for a in ACTIONS},"untrusted_extra":"ignored"}}}
        self.assertEqual(player.validate_answer(answer)["choice"],"up")
        self.assertNotIn("untrusted_extra",player.validate_answer(answer))
        for bad in (float("nan"),-1,True):
            answer["answers"]["movement"]["confidence"]=bad
            with self.assertRaises(ValueError): player.validate_answer(answer)

    def test_dry_decision_cannot_use_network(self):
        with patch("socket.socket",side_effect=AssertionError("No network")), patch.object(player.time,"sleep"):
            for n in range(1,6):
                answer,_=player.decide({},"dry",n)
                self.assertIn(answer["choice"],ACTIONS)

    def test_live_transport_uses_one_attempt_and_does_not_retry_error(self):
        with patch.object(player.urllib.request,"urlopen",side_effect=TimeoutError) as http:
            with self.assertRaises(TimeoutError): player.decide({},"live",1,"unit-test-placeholder")
        self.assertEqual(http.call_count,1)

    def test_reply_freshness_uses_frames_session_epoch_and_no_rewind(self):
        observed=fixture(100)
        for state in (dict(observed,frame=121),dict(observed,frame=99),
                      dict(observed,lua_session_id="other"),dict(observed,reload_epoch=1)):
            self.assertFalse(player.reply_is_fresh(observed,state,20))
        self.assertTrue(player.reply_is_fresh(observed,dict(observed,frame=120),20))

    def simulated_loop(self,delay=8,error=False,reload=False,lose_tracks=False,stepped=False,lua_freezes=True,threat_from=None,policy="legacy"):
        """Advance synthetic game frames while a future remains pending.

        With stepped=True the fake Lua holds the frame while the current command's
        freeze_at_frame equals it, as main.lua does with client.pause()."""
        with tempfile.TemporaryDirectory(prefix="combat-unit-",dir=player.ROOT / "runs") as temp:
            output=Path(temp)
            state=fixture()
            state["bridge_run_id"]=output.name
            cursor={"frame":100,"duplicate":False,"command":None,"seen":100,"heartbeat":0}
            submitted=[]; keys_used=[]
            def read():
                frame=cursor["frame"]
                cursor["seen"]=frame
                result=dict(state,frame=frame)
                if lose_tracks and frame>=130:
                    profile=dict(state["observation_profile"])
                    for field in ("slots","enemy_slots"):
                        profile[field]=[{"base":s["base"],"bytes_hex":"00"*22} for s in profile[field]]
                    profile["object_table"]=dict(profile["object_table"],bytes_hex="00"*RECORD_BYTES*len(TABLE_BASES))
                    result["observation_profile"]=profile
                if reload and frame==110: result["reload_epoch"]=1
                if threat_from and frame>=threat_from:
                    # A helicopter appears 16 px right of the player and closes 1 px per frame.
                    profile=dict(state["observation_profile"]); table=dict(profile["object_table"])
                    data=bytearray.fromhex(table["bytes_hex"]); index=TABLE_BASES.index(0x1A00)*RECORD_BYTES
                    record=bytearray(RECORD_BYTES); record[:4]=bytes.fromhex("c84ab002"); record[8]=3
                    record[16:19]=((112-(frame-threat_from))*256).to_bytes(3,"little",signed=True)
                    record[19:22]=(112*256).to_bytes(3,"little",signed=True)
                    data[index:index+RECORD_BYTES]=record
                    profile["object_table"]=dict(table,bytes_hex=data.hex()); result["observation_profile"]=profile
                cmd=cursor["command"]
                if cmd and frame>cmd["issued_at_frame"]:
                    # Paused Lua applies a released command from the frozen frame itself.
                    result.update(last_applied_run_id=output.name,last_applied_call=cmd["call"],
                                  first_apply_frame=cmd["issued_at_frame"]+(0 if stepped else 1))
                if stepped and lua_freezes and cmd and cmd.get("freeze_at_frame")==frame:
                    cursor["heartbeat"]+=1
                    return dict(result,frozen=True,freeze_heartbeat=cursor["heartbeat"])
                cursor["duplicate"]=not cursor["duplicate"]
                if not cursor["duplicate"]: cursor["frame"]+=1
                return result
            class Delayed:
                def __init__(self,ready): self.ready=ready
                def done(self): return cursor["seen"]>=self.ready
                def result(self):
                    if error: raise TimeoutError("not logged")
                    return {"choice":"up","confidence":0.5,"probabilities":{a:0.2 for a in ACTIONS}},250
            class Executor:
                def __init__(self,**kwargs): pass
                def submit(self,*args):
                    submitted.append(cursor["seen"])
                    return Delayed(cursor["seen"]+delay)
                def shutdown(self,**kwargs): pass
            with ExitStack() as stack:
                stop=stack.enter_context(patch.object(player.bridge,"release_controls"))
                stack.enter_context(patch.object(player.bridge,"wait_for_fresh_state",return_value=state))
                stack.enter_context(patch.object(player.bridge,"read_state",side_effect=read))
                stack.enter_context(patch.object(player.bridge,"write_json",side_effect=lambda _,cmd:cursor.update(command=cmd)))
                stack.enter_context(patch.object(player,"ThreadPoolExecutor",Executor))
                if stepped:
                    def decide(body,mode,attempt,key=None,delay_ms=250):
                        submitted.append(cursor["seen"])
                        keys_used.append(key)
                        if policy != "legacy":
                            from brain.decisions import compose
                            answers = {name:{"choice":"up","confidence":0.1,
                                             "probabilities":{action:0.2 for action in ACTIONS}}
                                       for name in body["questions"]}
                            return compose(body, answers), 250
                        return Delayed(0).result()
                    stack.enter_context(patch.object(player,"decide",side_effect=decide))
                stack.enter_context(patch.object(player.time,"sleep"))
                stack.enter_context(patch("socket.socket",side_effect=AssertionError("No network")))
                stack.enter_context(patch("builtins.print"))
                report=player.run(output,"live",limit=3,warmup=2,frame_budget=150,key="unit-test-placeholder",stepped=stepped,policy=policy)
            events=[json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
            observations=[json.loads(line) for line in (output / "states.jsonl").read_text().splitlines()]
            self.assertEqual(stop.call_count,2)
            # Every stepped request must carry the caller's key, not a shadowed local.
            self.assertTrue(all(k=="unit-test-placeholder" for k in keys_used),keys_used)
            return report,events,observations,submitted

    def test_continuous_observation_one_future_no_duplicate_or_extra_response_wait(self):
        report,events,observations,submitted=self.simulated_loop()
        self.assertEqual(report["reason"],"decision_budget")
        self.assertEqual(report["jev_requests"],3)  # synthetic; transport was forbidden
        self.assertEqual(report["applied_jev_decisions"],3)
        self.assertEqual([b-a for a,b in zip(submitted,submitted[1:])],[30,30])
        frames=[o["state"]["frame"] for o in observations]
        self.assertEqual(len(frames),len(set(frames)))
        self.assertTrue(all(f in frames for f in range(submitted[0],submitted[0]+8)))
        responses=[e for e in events if e["event"]=="response"]
        self.assertTrue(all(e["received_frame"]-e["source_frame"]==8 for e in responses))

    def test_pause_and_step_applies_each_choice_from_the_observed_frame(self):
        report,events,observations,submitted=self.simulated_loop(stepped=True)
        self.assertEqual((report["reason"],report["jev_requests"],report["applied_jev_decisions"]),("decision_budget",3,3))
        self.assertEqual([b-a for a,b in zip(submitted,submitted[1:])],[30,30])
        responses=[e for e in events if e["event"]=="response"]
        self.assertTrue(all(e["received_frame"]==e["source_frame"] and e["frozen_throughout"] for e in responses))
        jev=[e["command"] for e in events if e["event"]=="command" and e["command"]["decision_source"]=="jev"]
        self.assertTrue(all(c["issued_at_frame"]==c["observed_frame"] for c in jev))
        # Each choice names the next pause; the last one lets the game run out its lease.
        self.assertEqual([c["freeze_at_frame"] for c in jev],[jev[0]["issued_at_frame"]+30,jev[1]["issued_at_frame"]+30,0])
        acks=[e for e in events if e["event"]=="input_ack" and e["decision_source"]=="jev"]
        self.assertTrue(all(e["observe_to_apply_frames"]==0 for e in acks))
        frames=[o["state"]["frame"] for o in observations]
        self.assertEqual(len(frames),len(set(frames)))

    def test_threat_mid_action_pauses_next_frame_and_asks_again(self):
        report,events,_,submitted=self.simulated_loop(stepped=True,threat_from=112)
        trigger=next(e for e in events if e["event"]=="replan_trigger")
        self.assertLess(trigger["gap_px"],trigger["gap_at_decision_px"]/2)
        # The second request comes from the frame right after the trigger, not 30 frames after the first.
        self.assertEqual(submitted[1],trigger["frame"]+1)
        self.assertLess(submitted[1]-submitted[0],30)
        responses=[e for e in events if e["event"]=="response"]
        self.assertTrue(all(e["frozen_throughout"] for e in responses))

    def test_late_emulator_start_stops_before_any_request(self):
        with tempfile.TemporaryDirectory(prefix="combat-unit-",dir=player.ROOT / "runs") as temp:
            output=Path(temp); state=dict(fixture(),experiment_start_frame=player.SAVE_FRAME+900)
            state["bridge_run_id"]=output.name
            with ExitStack() as stack:
                stack.enter_context(patch.object(player.bridge,"release_controls"))
                stack.enter_context(patch.object(player.bridge,"wait_for_fresh_state",return_value=state))
                stack.enter_context(patch.object(player.bridge,"read_state",return_value=state))
                stack.enter_context(patch.object(player,"decide",side_effect=AssertionError("no request")))
                stack.enter_context(patch.object(player.time,"sleep")); stack.enter_context(patch("builtins.print"))
                report=player.run(output,"live",limit=3,warmup=2,frame_budget=150,key="unit-test-placeholder",stepped=True)
        self.assertEqual((report["reason"],report["jev_requests"]),("emulator_started_late",0))

    def test_pause_not_confirmed_stops_without_a_request(self):
        report,events,_,submitted=self.simulated_loop(stepped=True,lua_freezes=False)
        self.assertEqual((report["reason"],report["jev_requests"]),("freeze_not_confirmed",0))
        self.assertEqual(submitted,[])

    def test_late_response_is_logged_but_never_injected(self):
        report,events,_,submitted=self.simulated_loop(delay=25)
        self.assertEqual(report["reason"],"stale_reply_rejected")
        self.assertEqual(len(submitted),1)
        self.assertFalse(any(e["event"]=="command" and e["command"]["decision_source"]=="jev" for e in events))

    def test_api_error_counts_attempt_and_stops_without_a_fallback(self):
        report,events,_,submitted=self.simulated_loop(error=True)
        self.assertEqual((report["reason"],report["jev_requests"],report["applied_jev_decisions"]),("error",1,0))
        self.assertEqual(len(submitted),1)
        detail=next(e["detail"] for e in events if e["event"]=="error")
        # Type and source location, never the exception message.
        self.assertTrue(detail.startswith("TimeoutError at "),detail)
        self.assertNotIn("secret-bearing",detail)

    def test_save_epoch_change_cancels_old_reply_without_injection(self):
        report,events,_,_=self.simulated_loop(reload=True)
        self.assertEqual(report["reason"],"reload_or_other_bridge")
        self.assertEqual(report["applied_jev_decisions"],0)

    def test_missing_tracks_does_not_shorten_last_model_action(self):
        report,events,_,_=self.simulated_loop(lose_tracks=True)
        commands=[e["command"] for e in events if e["event"]=="command"]
        chosen=next(c for c in commands if c["decision_source"]=="jev")
        next_command=commands[commands.index(chosen)+1]
        self.assertGreaterEqual(next_command["issued_at_frame"],chosen["issued_at_frame"]+1+30)
        self.assertEqual(report["reason"],"game_frame_budget")


if __name__=="__main__": unittest.main()
