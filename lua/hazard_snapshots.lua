-- Bounded, deterministic observation. No Jev calls or game-memory writes.
-- The Python runner supplies a unique output folder; legacy launchers still work.
local project = "C:/Users/Carl-MainRig/Projects/jev-un-squadron"
local root = os.getenv("HAZARD_OUTPUT") or (project .. "/hazard_observation/snap_" .. os.time())
-- Every setup or loop error lands in error.txt and closes BizHawk, so the runner
-- never waits on an error that only the Lua console shows.
local function main()
  local mode = os.getenv("HAZARD_MODE") or (os.getenv("HAZARD_FIRE") == "1" and "pulse6" or "neutral")
  local frames = tonumber(os.getenv("HAZARD_FRAMES")) or 660
  local capture_from = tonumber(os.getenv("HAZARD_CAPTURE_FROM")) or 500
  local capture_to = tonumber(os.getenv("HAZARD_CAPTURE_TO")) or 640
  local fire_from = tonumber(os.getenv("HAZARD_FIRE_FROM")) or 1
  local fire_until = tonumber(os.getenv("HAZARD_FIRE_UNTIL")) or frames
  local movement = os.getenv("HAZARD_MOVE") or "neutral"
  local move_from = tonumber(os.getenv("HAZARD_MOVE_FROM")) or 1
  local move_until = tonumber(os.getenv("HAZARD_MOVE_UNTIL")) or 0
  assert(movement == "neutral" or movement == "Up" or movement == "Down" or movement == "Left" or movement == "Right", "Invalid calibration direction")
  assert(mode == "neutral" or mode == "held" or mode == "pulse6" or mode == "pulse8" or mode == "replay", "Invalid probe mode")
  -- Replay mode presses the exact requested masks a runner logged per source frame.
  local replay = nil
  if mode == "replay" then
    replay = {}
    -- assert returns its message too; io.lines would read it as a format argument.
    local replay_path = assert(os.getenv("HAZARD_REPLAY"), "Replay mode needs HAZARD_REPLAY")
    for line in io.lines(replay_path) do
      local f, m = line:match("^(%d+),(%d+)")
      if f then replay[tonumber(f)] = tonumber(m) end
    end
  end
  assert(frames > 0 and frames <= 1800, "Probe frame budget out of range")
  os.execute('mkdir "' .. root .. '" 2>nul')
  memory.usememorydomain("WRAM")
  local size = memory.getmemorydomainsize("WRAM")
  assert(size == 0x20000, "Unexpected WRAM size")
  client.speedmode(50)
  emu.limitframerate(true)
  client.frameskip(0)
  client.setscreenshotosd(false)
  client.displaymessages(false)
  client.clearautohold()

  local keys = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}
  local function neutral()
    local pad = {}; for _, k in ipairs(keys) do pad[k] = false end; return pad
  end
  local function mask(pad)
    local value = 0
    for i, k in ipairs(keys) do if pad[k] then value = value + 2^(i-1) end end
    return value
  end
  local function from_mask(value)
    local pad = neutral()
    for i, k in ipairs(keys) do pad[k] = math.floor(value / 2^(i-1)) % 2 == 1 end
    return pad
  end
  local function exists(path)
    local file = io.open(path, "r")
    if file then file:close(); return true end
    return false
  end
  local bin = assert(io.open(root .. "/wram_u8.bin", "wb"))
  local meta = assert(io.open(root .. "/frames.csv", "w"))
  local inputs = assert(io.open(root .. "/inputs.csv", "w"))
  meta:write("sample,emu_frame,player_x,player_y,mode,snapshot_index,screenshot,legacy_y_scratch\n")
  inputs:write("sample,source_frame,result_frame,requested_mask,poll_mask,input_polls,speed_percent,lagged\n")
  local poll_mask, poll_count = -1, 0
  event.oninputpoll(function()
    poll_mask = mask(joypad.getwithmovie(1)); poll_count = poll_count + 1
  end, "hazard_input_readback")
  local start_frame, last_frame = emu.framecount(), emu.framecount()
  local index, last_sample, closed = 0, 0, false
  local function finish(reason)
    joypad.set(neutral(), 1)
    if closed then return end
    closed = true
    meta:close(); bin:close(); inputs:close()
    local status = assert(io.open(root .. "/status.txt", "w"))
    status:write("status=", reason, "\nstart_frame=", start_frame,
      "\nend_frame=", emu.framecount(), "\nsamples=", last_sample,
      "\nsnapshots=", index, "\ncontrols_released=true\njev_requests=0\n")
    status:close()
  end
  event.onexit(function() finish("script_exit") end, "hazard_release")
  local info = assert(io.open(root .. "/emulator.txt", "w"))
  info:write("bizhawk=", client.getversion(), "\nsystem=", emu.getsystemid(),
    "\ndisplay=", emu.getdisplaytype(), "\nstart_frame=", start_frame,
    "\nspeed_percent=", tostring(client.getconfig().SpeedPercent),
    "\ndomain=WRAM\ndomain_size=", size, "\nmode=", mode,
    "\nplayer_x_address=0x1011\nplayer_y_address=0x1014\nlegacy_y_scratch_address=0x002C",
    "\ninput_mask_keys=", table.concat(keys, ","), "\n")
  info:close()

  local function snapshot(sample)
    local name = string.format("frame_%04d.png", sample)
    -- One bulk API read instead of 131072 separate interop calls.
    local raw
    if memory.read_bytes_as_binary_string then
      raw = memory.read_bytes_as_binary_string(0, size, "WRAM")
    else
      local bytes = memory.read_bytes_as_array(0, size, "WRAM")
      local pieces = {}
      for i = 1, size, 1024 do
        pieces[#pieces+1] = string.char(table.unpack(bytes, i, math.min(i+1023, size)))
      end
      raw = table.concat(pieces)
    end
    assert(#raw == size, "WRAM snapshot length mismatch")
    bin:write(raw); bin:flush()
    client.screenshot(root .. "/" .. name)
    meta:write(string.format("%d,%d,%d,%d,%s,%d,%s,%d\n", sample, emu.framecount(),
      memory.read_u8(0x1011), memory.read_u8(0x1014), mode, index, name, memory.read_u8(0x002C)))
    meta:flush(); index = index + 1
  end

  client.unpause()
  local ok, err = xpcall(function()
    snapshot(0)
    for sample = 1, frames do
      if exists(root .. "/STOP") or exists(project .. "/STOP") or input.get().Escape then
        finish("stopped"); return
      end
      if emu.framecount() ~= last_frame then finish("frame_discontinuity"); return end
      local pad = neutral()
      if replay then
        pad = from_mask(replay[emu.framecount()] or 0)
      elseif movement ~= "neutral" and sample >= move_from and sample <= move_until then pad[movement] = true end
      if not replay and sample >= fire_from and sample <= fire_until then
        pad.Y = mode == "held" or (mode == "pulse6" and sample%6 == 0)
          or (mode == "pulse8" and emu.framecount()%8 < 4)
      end
      local source = emu.framecount()
      poll_mask, poll_count = -1, 0
      joypad.set(pad, 1)
      -- gui.text's fifth argument is an anchor, not a background colour, so draw the
      -- label the same way main.lua does and never let drawing break a capture.
      pcall(function()
        gui.drawRectangle(2, 2, 150, 23, 0xFF000000, 0xC0101010)
        gui.drawText(5, 3, "OFFLINE CAPTURE - no Jev", 0xFFFF8040, 0xFF000000, 11)
        gui.drawText(5, 14, string.format("%s %d/%d  f%d  Esc stops", mode, sample, frames, emu.framecount()),
          0xFFFFFFFF, 0xFF000000, 11)
      end)
      emu.frameadvance()
      last_frame = emu.framecount(); last_sample = sample
      inputs:write(string.format("%d,%d,%d,%d,%d,%d,%d,%s\n", sample, source,
        last_frame, mask(pad), poll_mask, poll_count, client.getconfig().SpeedPercent, tostring(emu.islagged())))
      inputs:flush()
      if last_frame ~= source+1 then finish("frame_discontinuity"); return end
      if sample%2 == 0 and (sample <= 60 or (sample >= capture_from and sample <= capture_to)) then
        snapshot(sample)
      end
    end
    finish("complete")
  end, debug.traceback)
  if not ok then
    local error_file = io.open(root .. "/error.txt", "w")
    if error_file then error_file:write(tostring(err)); error_file:close() end
    finish("error")
  end
end
local ok_main, main_err = xpcall(main, debug.traceback)
if not ok_main then
  local error_file = io.open(root .. "/error.txt", "w")
  if error_file then error_file:write(tostring(main_err)); error_file:close() end
end
client.exit()
