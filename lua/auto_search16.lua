-- Zero-Jev exploratory scan for 16-bit little-endian WRAM candidates.
-- Stop main.lua before starting; visual validation is still required.
memory.usememorydomain("WRAM")
local N = 0x1FFFF
local function snap()
  local t = {}
  for a = 0, N - 1 do t[a] = memory.read_u16_le(a) end
  return t
end
local function frames(n, pad)
  for i=1,n do joypad.set(pad or {},1); emu.frameadvance() end
  joypad.set({},1)
end
local f = io.open("C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\evidence\\probes\\ram_candidates16.txt", "w")
frames(10,{})
local base=snap(); frames(30,{}); local neutral=snap()
frames(20,{Up=true}); local up=snap()
frames(20,{Down=true}); local down=snap()
frames(20,{Left=true}); local left=snap()
frames(20,{Right=true}); local right=snap()
local count=0
if f then f:write("address,base,neutral,up,down,left,right\n") end
for a=0,N-1 do
  local du=up[a]-neutral[a]; local dd=down[a]-neutral[a]
  local dl=left[a]-neutral[a]; local dr=right[a]-neutral[a]
  local y=(du ~= 0 and dd ~= 0 and ((du > 0 and dd < 0) or (du < 0 and dd > 0)))
  local x=(dl ~= 0 and dr ~= 0 and ((dl > 0 and dr < 0) or (dl < 0 and dr > 0)))
  if y or x then
    count=count+1
    if f then f:write(string.format("0x%04X,%d,%d,%d,%d,%d,%d\n",a,base[a],neutral[a],up[a],down[a],left[a],right[a])) end
  end
end
if f then f:write("candidates=",count,"\n"); f:close() end
console.log("16-bit scan complete: " .. count .. " candidates; see ram_candidates16.txt")
