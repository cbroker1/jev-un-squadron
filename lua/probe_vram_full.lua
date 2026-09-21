-- Full VRAM plus the screenshot for the same frame, so candidate tilemap regions can be
-- searched offline against what was actually on screen, instead of guessing a base.
--
-- Paths use forward slashes on purpose: a heredoc collapsed the doubled backslashes in an
-- earlier version and Lua rejected "C:\U" as an invalid escape sequence.
--
-- Read-only: holds up, advances a few frames at normal speed so the frame renders, writes
-- two files, exits. No Jev, no decisions, no controls beyond holding up.
local ROOT = "C:/Users/Carl-MainRig/Projects/jev-un-squadron/"
local ADVANCE = tonumber(os.getenv("JEV_PROBE_ADVANCE") or "") or 6

local function main()
  client.speedmode(100)
  emu.limitframerate(true)
  for _ = 1, ADVANCE do
    joypad.set({Up = true}, 1)
    emu.frameadvance()
  end
  memory.usememorydomain("WRAM")
  local scroll = memory.read_u16_le(0x007B)
  local px, py = memory.read_u8(0x1011), memory.read_u8(0x1014)
  client.screenshot(ROOT .. "evidence/probes/vram_full_frame.png")
  memory.usememorydomain("VRAM")
  local size = memory.getmemorydomainsize("VRAM")
  local out = assert(io.open(ROOT .. "evidence/probes/vram_full.txt", "w"))
  out:write(string.format("frame %d scroll %d player %d %d size %d\n",
    emu.framecount(), scroll, px, py, size))
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

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "evidence/probes/vram_probe.txt", "w"))
note:write(ok and "full vram written\n" or ("probe failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
