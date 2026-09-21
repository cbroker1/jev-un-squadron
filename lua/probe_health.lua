-- Find the aircraft's health in WRAM by replaying a run and dumping memory around the
-- frames where it is known to have been hit.
--
-- Carl authorised mapping health on 2026-09-20 so that risk can be modulated by how much
-- damage the aircraft can still take. The project rule until then was to leave it unmapped.
--
-- Replays recorded inputs, so the frames reproduce exactly; writes one dump per requested
-- frame. Read-only apart from those dumps: no Jev, no decisions, no save states.
local ROOT = "C:/Users/Carl-MainRig/Projects/jev-un-squadron/"
local INPUTS = assert(os.getenv("JEV_REPLAY_INPUTS"), "needs JEV_REPLAY_INPUTS")
local WANTED = assert(os.getenv("JEV_DUMP_FRAMES"), "needs JEV_DUMP_FRAMES, comma separated")

local KEYS = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}

local function pad_from_mask(mask)
  local pad = {}
  for index, key in ipairs(KEYS) do
    pad[key] = (mask % (2^index)) >= 2^(index-1)
  end
  return pad
end

local function dump(frame)
  memory.usememorydomain("WRAM")
  local size = memory.getmemorydomainsize("WRAM")
  local out = assert(io.open(string.format("%swram_%d.txt", ROOT, frame), "w"))
  out:write(string.format("frame %d size %d\n", frame, size))
  local parts = {}
  for address = 0, size-1 do
    parts[#parts+1] = string.format("%02x", memory.read_u8(address))
    if #parts == 8192 then
      out:write(table.concat(parts))
      parts = {}
    end
  end
  out:write(table.concat(parts), "\n")
  out:close()
end

local function main()
  local wanted, last = {}, 0
  for frame in WANTED:gmatch("(%d+)") do
    frame = tonumber(frame)
    wanted[frame] = true
    if frame > last then last = frame end
  end
  local replay = {}
  local header = true
  for line in io.lines(INPUTS) do
    if header then
      header = false
    else
      local frame, mask = line:match("^(%d+),%d+,[^,]*,%d+,[^,]*,(%d+),")
      if frame then replay[tonumber(frame)] = tonumber(mask) end
    end
  end
  client.speedmode(400)
  emu.limitframerate(false)
  while emu.framecount() <= last do
    if wanted[emu.framecount()] then dump(emu.framecount()) end
    joypad.set(pad_from_mask(replay[emu.framecount()] or 0), 1)
    emu.frameadvance()
  end
end

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "evidence/probes/wram_probe.txt", "w"))
note:write(ok and "dumps written\n" or ("probe failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
