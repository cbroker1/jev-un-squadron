memory.usememorydomain("WRAM")
local addrs = {0x002C,0x0098,0x009B,0x009D,0x00FA,0x00FB,0x0629,0x062B,0x0901,0x0905,0x100D,0x1014,0x1024}
local f = io.open("C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\evidence\\probes\\candidate_watch.log", "w")
if f then f:write("frame", ","); for _,a in ipairs(addrs) do f:write(string.format("0x%04X,", a)) end; f:write("\n") end
while true do
  local line = tostring(emu.framecount()) .. ","
  for _,a in ipairs(addrs) do line = line .. tostring(memory.read_u8(a)) .. "," end
  if f then f:write(line .. "\n"); f:flush() end
  emu.frameadvance()
end
