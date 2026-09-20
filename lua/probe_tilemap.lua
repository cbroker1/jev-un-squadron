-- Record the stage tilemap as the level scrolls, so terrain can be read from the game's
-- own layer instead of discovered by flying into it.
--
-- VRAM 0xA000 is the scrolling stage map: diffing dumps 60 px apart showed about eight
-- tile columns rewritten each time, which is what streaming a 32-wide map looks like.
-- 0x9800 is captured too, so the layers can be told apart offline.
--
-- Read-only: advances frames with no input, writes one file, exits. No API, no controls.
local ROOT = "C:/Users/Carl-MainRig/Projects/jev-un-squadron/"
local EVERY = 20
local FRAMES = tonumber(os.getenv("JEV_PROBE_FRAMES") or "") or 2400
local MAPS = {0x9800, 0xa000}
local MAP_BYTES = 0x1000   -- both halves, so a 64-wide layout can be tested

local function window(base)
  local parts = {}
  for offset = 0, MAP_BYTES-1 do
    parts[#parts+1] = string.format("%02x", memory.read_u8(base + offset))
  end
  return table.concat(parts)
end

-- Holding up dies before the far half of the stage, so the deep columns were never
-- captured: at level x 1717 the map had nothing and Jev fired into a structure it could
-- not see. Replaying a run that got there keeps the aircraft alive the whole way.
local replay = nil
local replay_path = os.getenv("JEV_REPLAY_INPUTS")
if replay_path then
  replay = {}
  local first = true
  for line in io.lines(replay_path) do
    if first then
      first = false
    else
      local frame, mask = line:match("^(%d+),%d+,[^,]*,%d+,[^,]*,(%d+),")
      if frame then replay[tonumber(frame)] = tonumber(mask) end
    end
  end
end

local KEYS = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}
local function pad_from_mask(mask)
  local pad = {}
  for index, key in ipairs(KEYS) do
    pad[key] = (mask % (2^index)) >= 2^(index-1)
  end
  return pad
end

local function apply_input()
  if replay then
    joypad.set(pad_from_mask(replay[emu.framecount()] or 0), 1)
  else
    joypad.set({Up = true}, 1)
  end
end

local function main()
  client.speedmode(400)
  emu.limitframerate(false)
  -- With no input the aircraft dies within a few hundred frames and the stage restarts,
  -- so the probe never reaches the far half of the level. Holding up keeps it clear of
  -- the ground for longer. This is a deterministic capture: no Jev, no decisions.
  apply_input()
  local out = assert(io.open(ROOT .. (os.getenv("JEV_PROBE_OUT") or "tilemap_samples.jsonl"), "w"))
  for step = 1, FRAMES do
    if step % EVERY == 1 then
      memory.usememorydomain("WRAM")
      local scroll = memory.read_u16_le(0x007B)
      local px, py = memory.read_u8(0x1011), memory.read_u8(0x1014)
      memory.usememorydomain("VRAM")
      local maps = {}
      for _, base in ipairs(MAPS) do
        maps[#maps+1] = string.format('"%04x":"%s"', base, window(base))
      end
      out:write(string.format('{"frame":%d,"scroll":%d,"player":[%d,%d],"maps":{%s}}\n',
        emu.framecount(), scroll, px, py, table.concat(maps, ",")))
      out:flush()
    end
    apply_input()
    emu.frameadvance()
  end
  out:close()
end

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "vram_probe.txt", "w"))
note:write(ok and "tilemap samples written\n" or ("probe failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
