-- One frame, three candidate tilemaps in full, plus the screenshot for that frame.
-- If the terrain on screen can be seen in a tile grid, the layer and the coordinate
-- mapping are right; if not, they are not, and no amount of correlation will save it.
-- Read-only: holds up, advances to a chosen frame, writes files, exits.
local ROOT = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\"
local ADVANCE = tonumber(os.getenv("JEV_PROBE_ADVANCE") or "") or 400
local MAPS = {0x9800, 0xa000, 0xd800}
local MAP_BYTES = 0x1000            -- a 64x32 map is two 32x32 halves, 0x800 each

local function main()
  client.speedmode(400)
  emu.limitframerate(false)
  -- Advance at normal speed so frames render, and stop early if the aircraft is
  -- destroyed: a probe that dies mid-advance captures a restarted stage, which is what
  -- made the previous attempt report scroll 0 and a blank player.
  client.speedmode(100)
  emu.limitframerate(true)
  for _ = 1, ADVANCE do
    joypad.set({Up = true}, 1)
    emu.frameadvance()
    memory.usememorydomain("WRAM")
    if memory.read_u8(0x1001) == 0x9b and memory.read_u8(0x1002) == 0xe1 then break end
  end
  -- Render properly before the screenshot: at speed 400 the frame buffer is skipped and
  -- the capture comes out black, which is no use for checking the alignment by eye.
  client.speedmode(100)
  emu.limitframerate(true)
  for _ = 1, 4 do joypad.set({Up = true}, 1); emu.frameadvance() end
  memory.usememorydomain("WRAM")
  local scroll = memory.read_u16_le(0x007B)
  local px, py = memory.read_u8(0x1011), memory.read_u8(0x1014)
  client.screenshot(ROOT .. "tile_grid_frame.png")
  memory.usememorydomain("VRAM")
  local out = assert(io.open(ROOT .. "tile_grid.json", "w"))
  local maps = {}
  for _, base in ipairs(MAPS) do
    local parts = {}
    for offset = 0, MAP_BYTES-1 do
      parts[#parts+1] = string.format("%02x", memory.read_u8(base + offset))
    end
    maps[#maps+1] = string.format('"%04x":"%s"', base, table.concat(parts))
  end
  out:write(string.format('{"frame":%d,"scroll":%d,"player":[%d,%d],"maps":{%s}}\n',
    emu.framecount(), scroll, px, py, table.concat(maps, ",")))
  out:close()
end

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "vram_probe.txt", "w"))
note:write(ok and "tile grid written\n" or ("probe failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
