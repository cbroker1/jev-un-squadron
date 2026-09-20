-- Zero-Jev 16-bit scan with an in-memory savestate before every probe.
-- Start this at the desired gameplay point; it does not use the Python bridge.
memory.usememorydomain("WRAM")
local N = 0x1FFFF
local function snap()
  local t={}; for a=0,N-1 do t[a]=memory.read_u16_le(a) end; return t
end
local function frames(n,pad)
  for i=1,n do joypad.set(pad or {},1); emu.frameadvance() end
  joypad.set({},1)
end
local anchor = memorysavestate.savecorestate()
frames(10,{})
local base=snap()
local probes={up={Up=true},down={Down=true},left={Left=true},right={Right=true}}
local values={}
for name,pad in pairs(probes) do
  memorysavestate.loadcorestate(anchor)
  frames(30,pad)
  values[name]=snap()
end
memorysavestate.loadcorestate(anchor)
local f=io.open("C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\ram_candidates16_reload.txt","w")
local count=0
if f then f:write("address,base,up,down,left,right\n") end
for a=0,N-1 do
  local up,down,left,right=values.up[a],values.down[a],values.left[a],values.right[a]
  local y=(up~=base[a] and down~=base[a] and ((up>base[a] and down<base[a]) or (up<base[a] and down>base[a])))
  local x=(left~=base[a] and right~=base[a] and ((left>base[a] and right<base[a]) or (left<base[a] and right>base[a])))
  if y or x then count=count+1; if f then f:write(string.format("0x%04X,%d,%d,%d,%d,%d\n",a,base[a],up,down,left,right)) end end
end
if f then f:write("candidates=",count,"\n"); f:close() end
console.log("Reloading 16-bit scan complete: "..count.." candidates; see ram_candidates16_reload.txt")
