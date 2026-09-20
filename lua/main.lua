-- BizHawk Lua bridge. Validated positions and remaining candidates are documented in MEMORY_MAP.md.
local action_file = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\runtime_action.json"
local state_file = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\runtime_state.json"
local running = true
memory.usememorydomain("WRAM")
local last_run = ""
local last_frame = nil
local blocked_run = ""
local reload_active = false
local PLAYER_X = 0x1011
local PLAYER_Y = 0x1014
-- Only the six visually checked slots. These bytes stay local to Python;
-- they are not a claim that every hostile object has this layout.
local projectile_bases = {0x1AC0,0x1B00,0x1B40,0x1B80,0x1BC0,0x1C00}
-- Checked aircraft slots; must equal brain/observations.py ENEMY_BASES (test_combat checks this).
local enemy_bases = {0x16C0,0x1780,0x17C0,0x1800,0x1840,0x1880,0x1940}
-- Whole object table (first 22 bytes of each 0x40 record); Python types records by routine.
-- Must equal brain/observations.py TABLE_BASES/RECORD_BYTES (test_combat checks this).
local TABLE_START, TABLE_STRIDE, TABLE_COUNT, RECORD_BYTES = 0x1000, 0x40, 64, 22
local function table_hex()
  local length = TABLE_STRIDE * TABLE_COUNT
  local byte_at
  if memory.read_bytes_as_binary_string then
    local raw = memory.read_bytes_as_binary_string(TABLE_START, length, "WRAM")
    byte_at = function(i) return raw:byte(i + 1) end
  else
    local bytes = memory.read_bytes_as_array(TABLE_START, length, "WRAM")
    byte_at = function(i) return bytes[i + 1] end
  end
  local parts = {}
  for record = 0, TABLE_COUNT - 1 do
    for offset = 0, RECORD_BYTES - 1 do
      parts[#parts+1] = string.format("%02x", byte_at(record * TABLE_STRIDE + offset))
    end
  end
  return table.concat(parts)
end
local function write_observation_profile(f)
  f:write('"observation_profile":{"schema":1,"domain":"WRAM","rom_hash":"',
    gameinfo.getromhash(), '","slots":[')
  for i, base in ipairs(projectile_bases) do
    local bytes = {}
    for offset=0,21 do bytes[#bytes+1] = string.format("%02x", memory.read_u8(base+offset)) end
    if i > 1 then f:write(',') end
    f:write('{"base":',base,',"bytes_hex":"',table.concat(bytes),'"}')
  end
  f:write('],"enemy_slots":[')
  for i, base in ipairs(enemy_bases) do
    local bytes = {}
    for offset=0,21 do bytes[#bytes+1] = string.format("%02x", memory.read_u8(base+offset)) end
    if i > 1 then f:write(',') end
    f:write('{"base":',base,',"bytes_hex":"',table.concat(bytes),'"}')
  end
  f:write('],"object_table":{"start":', TABLE_START, ',"stride":', TABLE_STRIDE, ',"count":', TABLE_COUNT,
    ',"record_bytes":', RECORD_BYTES, ',"bytes_hex":"', table_hex(), '"}},')
end
-- A new Lua instance and every savestate load invalidate all older movement.
local session = tostring(os.time()) .. "-" .. tostring({}):gsub("[^%w]", "")
local epoch = 0
local keys = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}
local function neutral()
  local pad = {}; for _, key in ipairs(keys) do pad[key] = false end; return pad
end
local function mask(pad)
  local value = 0
  for i, key in ipairs(keys) do if pad[key] then value = value + 2^(i-1) end end
  return value
end
local poll_mask, polls = -1, 0
event.oninputpoll(function()
  poll_mask = mask(joypad.getwithmovie(1)); polls = polls + 1
end, "bridge_input_readback")
event.onloadstate(function()
  epoch = epoch + 1; reload_active = true; blocked_run = last_run
  joypad.set(neutral(), 1)
end, "bridge_invalidate_save")
event.onexit(function() joypad.set(neutral(), 1) end, "bridge_release")
local run_label = os.getenv("JEV_RUN_LABEL") or "-"
-- Reaching the boss takes about 3500 frames of flying. When asked, this writes slot 2 once
-- on the way past, so the fight itself can be practised without replaying the whole stage.
-- Slot 1, the evidence baseline, is never written.
local save_at_frame = tonumber(os.getenv("JEV_SAVE_AT_FRAME") or "")
local saved_boss_entry = false
local function maybe_save_entry(frame)
  if save_at_frame and not saved_boss_entry and frame >= save_at_frame then
    saved_boss_entry = true
    local ok = pcall(savestate.saveslot, 2)
    console.log(string.format("boss entry slot 2 %s at frame %d", ok and "saved" or "FAILED", frame))
  end
end
-- Narration overlay: the run label and frame are what Carl calls out by voice.
-- gui.text's fifth argument is an anchor, not a background colour, so draw with
-- gui.drawText and never let a drawing error interrupt a run.
local function draw_overlay(frame, a, player_x, player_y, paused)
  local drawn = pcall(function()
    gui.drawRectangle(2, 2, 96, 34, 0xFF000000, 0xC0101010)
    gui.drawText(5, 3, string.format("d%d %s%s", a.call or 0, a.action,
      paused and "*" or ""), 0xFFFFFF00, 0xFF000000, 11)
    gui.drawText(5, 14, string.format("R%s F%d", run_label, frame), 0xFFFFFFFF, 0xFF000000, 11)
    gui.drawText(5, 25, string.format("%d,%d s%d", player_x, player_y,
      memory.read_u16_le(0x007B)), 0xFF40FF40, 0xFF000000, 11)
  end)
  if not drawn then
    pcall(gui.text, 4, 4, string.format("RUN %s  FRAME %d  %s", run_label, frame, a.action or ""))
  end
end
local trace_dir = os.getenv("JEV_BRIDGE_TRACE") -- Optional offline verification only.
local trace = trace_dir and assert(io.open(trace_dir .. "/inputs.csv", "w")) or nil
local preview_trace = os.getenv("JEV_BRAIN_PREVIEW") == "1"
local trace_start_frame = emu.framecount()
if trace then
  trace:write("source_frame,result_frame,run_id,call,action,requested_mask,poll_mask,input_polls,player_x,player_y,speed_percent,epoch\n")
  client.speedmode(50); emu.limitframerate(true); client.frameskip(0)
  client.setscreenshotosd(false)
end
event.onexit(function() if trace then trace:close(); trace = nil end end, "bridge_close_trace")
local first_apply_frame, applied_id = -1, ""
local lease_id, lease_end_frame = "", -1

local function read_action(frame)
  local f = io.open(action_file, "r")
  if not f then return {action="stop", fire=false, fire_button="Y", fire_pulse=false, run_id="", call=0} end
  local s = f:read("*a"); f:close()
  local action = s:match('"action"%s*:%s*"([%w_]+)"') or "stop"
  local fire = s:match('"fire"%s*:%s*true') ~= nil
  local fire_button = s:match('"fire_button"%s*:%s*"([ABXY])"') or "Y"
  local fire_pulse = s:match('"fire_pulse"%s*:%s*true') ~= nil
  local run_id = s:match('"run_id"%s*:%s*"([%w%-]+)"') or ""
  local issued = tonumber(s:match('"issued_at_frame"%s*:%s*(%d+)')) or -1
  local expires = tonumber(s:match('"expires_at_frame"%s*:%s*(%d+)')) or 0
  local call = tonumber(s:match('"call"%s*:%s*(%d+)')) or 0
  local target_session = s:match('"lua_session_id"%s*:%s*"([%w%-]+)"') or ""
  local target_epoch = tonumber(s:match('"reload_epoch"%s*:%s*(%d+)')) or -1
  local timestamp = tonumber(s:match('"ts"%s*:%s*([%d%.]+)')) or 0
  local duration = tonumber(s:match('"duration_frames"%s*:%s*(%d+)')) or 0
  local id = run_id .. ":" .. call
  -- The command's initial expiry is a latest-start deadline. Once accepted,
  -- duration is counted from the actual Lua application frame, not Python's snapshot.
  if id == lease_id then expires = lease_end_frame end
  if run_id ~= last_run then last_run = run_id end
  if (action ~= "hold" and action ~= "up" and action ~= "down" and action ~= "left" and action ~= "right")
      or not s:match('^%s*{.*}%s*$') or run_id == "" or expires <= 0
      or duration < 1 or duration > 120 or frame < issued or frame >= expires
      or target_session ~= session or target_epoch ~= epoch
      or os.time() - timestamp > 6 then
    return {action="stop", fire=false, fire_button="Y", fire_pulse=false, run_id=run_id, issued_at_frame=issued, call=call}
  end
  if id ~= lease_id then
    lease_id = id; lease_end_frame = frame + duration
  end
  return {action=action, fire=fire, fire_button=fire_button, fire_pulse=fire_pulse, run_id=run_id, issued_at_frame=issued, call=call}
end

local freeze_heartbeat = 0
local function write_state(a, frame, p, frame_regressed, source_frame, frozen)
  local vertical = memory.read_u8(0x1024)
  local candidate_x = memory.read_u8(0x0901)
  local candidate_y = memory.read_u8(PLAYER_Y)
  local candidate16_y = memory.read_u16_le(0x1023)
  local candidate16_xy = memory.read_u16_le(0x0068)
  local player_x = memory.read_u8(PLAYER_X)
  local player_y = memory.read_u8(PLAYER_Y)
  local vals = {0x002C,0x0098,0x009B,0x009D,0x00FA,0x00FB,0x0629,0x062B,0x0901,0x0905,0x100D,0x1014,0x1024}
  local f = io.open(state_file, "w")
  if f then
    f:write('{'); write_observation_profile(f)
    f:write('"lua_session_id":"', session, '","reload_epoch":', epoch,
      ',"bridge_run_id":"', a.run_id or "", '","applied_call":', a.call or 0,
      ',"last_applied_run_id":"', applied_id:match('^(.-):') or "",
      '","last_applied_call":', tonumber(applied_id:match(':(%d+)$')) or 0,
      ',"first_apply_frame":', first_apply_frame, ',"input_poll_mask":', poll_mask,
      ',"input_polls":', polls, ',"requested_mask":', mask(p),
      ',"speed_percent":', tostring(client.getconfig().SpeedPercent), ',"frame":', frame,
      ',"experiment_start_frame":', trace_start_frame,
      ',"scroll_x":', memory.read_u16_le(0x007B), ',"source_frame":', source_frame, ',"frame_regressed":', tostring(frame_regressed == true), ',"frozen":', tostring(frozen == true), ',"freeze_heartbeat":', freeze_heartbeat, ',"vertical_position_candidate":', vertical, ',"player_x_candidate":', player_x, ',"player_y_candidate":', player_y, ',"candidate_x":', candidate_x, ',"candidate_y":', candidate_y, ',"candidate16_y":', candidate16_y, ',"candidate16_xy":', candidate16_xy, ',"health":null,"applied_action":"', a.action, '","applied_fire":', tostring(a.fire), ',"applied_fire_button":"', a.fire_button, '","fire_pulse":', tostring(a.fire_pulse), ',"applied_buttons":{"Up":', tostring(p.Up == true), ',"Down":', tostring(p.Down == true), ',"Left":', tostring(p.Left == true), ',"Right":', tostring(p.Right == true), ',"A":', tostring(p.A == true), ',"B":', tostring(p.B == true), ',"X":', tostring(p.X == true), ',"Y":', tostring(p.Y == true), '},"candidate_values":{'); for i,addr in ipairs(vals) do f:write(string.format('"0x%04X":%d',addr,memory.read_u8(addr))); if i<#vals then f:write(',') end end; f:write('}}\n'); f:close()
  end
  -- A paused frame is not a new input frame: one trace row per emulated frame.
  if trace and not frozen then
    trace:write(source_frame, ",", frame, ",", a.run_id or "", ",", a.call or 0, ",", a.action,
      ",", mask(p), ",", poll_mask, ",", polls, ",", player_x, ",", player_y,
      ",", tostring(client.getconfig().SpeedPercent), ",", epoch, "\n")
    trace:flush()
    if a.action ~= "stop" and (frame - first_apply_frame == 1 or frame - first_apply_frame == 18) then
      client.screenshot(trace_dir .. "/frame_" .. frame .. "_call_" .. a.call .. ".png")
    end
    if preview_trace and (frame - trace_start_frame) % 20 == 0 then
      client.screenshot(trace_dir .. "/brain_frame_" .. frame .. ".png")
    end
  end
end

-- Pause-and-step: a command may name the frame at which the emulator pauses until
-- the next command arrives. STOP or the watchdog always resumes; neither injects input.
local function command_fields()
  local f = io.open(action_file, "r")
  if not f then return nil end
  local s = f:read("*a"); f:close()
  local run_id = s:match('"run_id"%s*:%s*"([%w%-]+)"') or ""
  return {id=run_id .. ":" .. (s:match('"call"%s*:%s*(%d+)') or "0"), run_id=run_id,
    freeze_at=tonumber(s:match('"freeze_at_frame"%s*:%s*(%d+)')) or 0,
    session=s:match('"lua_session_id"%s*:%s*"([%w%-]+)"') or "",
    epoch=tonumber(s:match('"reload_epoch"%s*:%s*(%d+)')) or -1,
    stop=s:match('"action"%s*:%s*"stop"') ~= nil}
end
local function hold_for_next_command(frame, a, p)
  local c = command_fields()
  if not c or c.freeze_at ~= frame or c.stop or c.run_id == "" or c.run_id == blocked_run
      or c.session ~= session or c.epoch ~= epoch then return end
  local started = os.time()
  client.pause()
  while true do
    local now = command_fields()
    -- An unreadable file keeps waiting; a new command, STOP or 5 s resumes.
    if (now and (now.id ~= c.id or now.stop)) or os.time() - started >= 5 then break end
    freeze_heartbeat = freeze_heartbeat + 1
    write_state(a, frame, p, reload_active, frame, true)
    draw_overlay(frame, a, memory.read_u8(PLAYER_X), memory.read_u8(PLAYER_Y), true)
    emu.yield()
  end
  client.unpause()
end
event.onexit(function() client.unpause() end, "bridge_unpause")

local was_injecting = false
local last_a, last_p = {action="stop", fire=false, fire_button="Y", fire_pulse=false, run_id="", call=0}, neutral()
while running do
  -- The offline reload harness calls the real savestate API here, never from
  -- an in-frame callback (which stalled the earlier reload test).
  if type(bridge_test_tick) == "function" then bridge_test_tick() end
  local frame = emu.framecount()
  local frame_regressed = last_frame ~= nil and frame < last_frame
  if frame_regressed then
    local stale = read_action(frame)
    blocked_run = stale.run_id or ""
    reload_active = true
    epoch = epoch + 1
  end
  last_frame = frame
  hold_for_next_command(frame, last_a, last_p)
  local a = read_action(frame)
  if blocked_run ~= "" and a.run_id == blocked_run then
    a = {action="stop", fire=false, fire_button="Y", fire_pulse=false, run_id=blocked_run, call=a.call}
  elseif a.run_id ~= "" and a.run_id ~= blocked_run then
    blocked_run = ""
    reload_active = false
  end
  local candidate_x = memory.read_u8(0x0901)
  local candidate_y = memory.read_u8(PLAYER_Y)
  local candidate16_y = memory.read_u16_le(0x1023)
  local candidate16_xy = memory.read_u16_le(0x0068)
  local player_x = memory.read_u8(PLAYER_X)
  local player_y = memory.read_u8(PLAYER_Y)
  local p = neutral()
  if a.fire and (not a.fire_pulse or (frame % 8) < 4) then p[a.fire_button] = true end
  if a.action == "up" then p.Up = true elseif a.action == "down" then p.Down = true elseif a.action == "left" then p.Left = true elseif a.action == "right" then p.Right = true end
  -- STOP releases injection once, then leaves the physical controller alone.
  if a.action ~= "stop" or was_injecting then joypad.set(p, 1) end
  was_injecting = a.action ~= "stop"
  local action_id = (a.run_id or "") .. ":" .. tostring(a.call or 0)
  if a.action ~= "stop" and action_id ~= applied_id then
    applied_id = action_id; first_apply_frame = frame
  end
  maybe_save_entry(frame)
  draw_overlay(frame, a, player_x, player_y, false)
  gui.drawBox(player_x - 4, player_y - 4, player_x + 4, player_y + 4, 0xFF00FF00, 0x00000000)
  poll_mask = -1; polls = 0
  emu.frameadvance()
  write_state(a, emu.framecount(), p, reload_active, frame)
  last_a, last_p = a, p
end
joypad.set(neutral(), 1)
