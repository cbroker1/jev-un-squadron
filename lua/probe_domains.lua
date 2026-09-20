-- Read-only probe: which memory domains this core exposes, and a sample of VRAM.
-- Carl's idea: the stage geometry lives in the game's own layers, so the tilemap can be
-- read the way the object table is, instead of discovering walls by flying into them.
-- Writes one file and exits. Touches nothing, sends nothing.
local report = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\vram_probe.txt"

local function main()
  local out = assert(io.open(report, "w"))
  out:write("frame ", emu.framecount(), "\n")
  for _, name in ipairs(memory.getmemorydomainlist()) do
    local size = memory.getmemorydomainsize(name)
    out:write(string.format("domain %s size %d\n", name, size))
  end
  -- A first look at VRAM: tilemaps are 2 bytes per tile, so dump a few windows.
  if memory.getmemorydomainsize("VRAM") > 0 then
    memory.usememorydomain("VRAM")
    for _, base in ipairs({0x0000, 0x0800, 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000}) do
      local parts = {}
      for offset = 0, 63 do
        parts[#parts+1] = string.format("%02x", memory.read_u8(base + offset))
      end
      out:write(string.format("vram %04x %s\n", base, table.concat(parts)))
    end
  end
  out:close()
end

local ok, err = pcall(main)
if not ok then
  local fallback = assert(io.open(report, "w"))
  fallback:write("probe failed: ", tostring(err), "\n")
  fallback:close()
end
client.exit()
