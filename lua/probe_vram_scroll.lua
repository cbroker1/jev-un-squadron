-- Find the stage tilemap in VRAM by watching what changes as the level scrolls.
--
-- Carl's point: probing walls by shooting them cannot scale to a level full of terrain.
-- The stage geometry is in the game's own layers, so this looks for the region of VRAM
-- that streams new columns as the scroll advances, the way a tilemap does.
--
-- Read-only: advances frames with no input, writes two dumps, exits. No API, no controls.
local ROOT = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\"
local SAMPLES = 3
local FRAMES_BETWEEN = 120

local function dump(path, frame, scroll)
  local out = assert(io.open(path, "w"))
  out:write(string.format("frame %d scroll %d\n", frame, scroll))
  memory.usememorydomain("VRAM")
  local size = memory.getmemorydomainsize("VRAM")
  local parts = {}
  for address = 0, size-1 do
    parts[#parts+1] = string.format("%02x", memory.read_u8(address))
    if #parts == 4096 then
      out:write(table.concat(parts)); parts = {}
    end
  end
  out:write(table.concat(parts), "\n")
  out:close()
end

local function scroll_now()
  memory.usememorydomain("WRAM")
  return memory.read_u16_le(0x007B)
end

local function main()
  client.speedmode(400)
  emu.limitframerate(false)
  for sample = 1, SAMPLES do
    dump(string.format("%svram_dump_%d.txt", ROOT, sample), emu.framecount(), scroll_now())
    for _ = 1, FRAMES_BETWEEN do emu.frameadvance() end
  end
end

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "evidence/probes/vram_probe.txt", "w"))
note:write(ok and "dumps written\n" or ("probe failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
