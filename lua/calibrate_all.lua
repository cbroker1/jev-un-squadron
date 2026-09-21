-- Single BizHawk-API calibration pass. Zero Jev/Python calls.
-- Start at active gameplay; stop other Lua scripts first.
memory.usememorydomain("WRAM")
client.unpause()
local report_path = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\evidence\\probes\\bizhawk_calibration.txt"
local anchor = memorysavestate.savecorestate()
local probes = {
  {name="neutral", pad={}, frames=20},
  {name="up", pad={Up=true}, frames=20},
  {name="down", pad={Down=true}, frames=20},
  {name="left", pad={Left=true}, frames=20},
  {name="right", pad={Right=true}, frames=20},
}
local function snap8()
  local t={}; for a=0,0x1FFFF do t[a]=memory.read_u8(a) end; return t
end
local function run_probe(p)
  memorysavestate.loadcorestate(anchor)
  for i=1,p.frames do
    joypad.set(p.pad,1)
    emu.frameadvance()
    local px=memory.read_u8(0x1011); local py=memory.read_u8(0x1022)
    gui.text(4,4,"API calibration: "..p.name.." frame "..emu.framecount(),"white","black")
    gui.text(4,16,string.format("UNVERIFIED X=0x1011:%d Y=0x1022:%d",px,py),"lime","black")
    gui.drawRectangle(px-8,py-8,16,16,0x00FF00FF,0x00000000)
  end
  joypad.set({},1)
  return snap8()
end
local results={}
for _,p in ipairs(probes) do results[p.name]=run_probe(p) end
memorysavestate.loadcorestate(anchor)
local f=io.open(report_path,"w")
if f then
  f:write("BizHawk API calibration; zero Jev calls\n")
  f:write("probe_frames=20; domain=WRAM; type=u8\n")
  f:write("address,neutral,up,down,left,right\n")
  local base=results.neutral
  local count=0
  for a=0,0x1FFFF do
    local u,d,l,r=results.up[a],results.down[a],results.left[a],results.right[a]
    local y=(u~=base[a] and d~=base[a] and ((u>base[a] and d<base[a]) or (u<base[a] and d>base[a])))
    local x=(l~=base[a] and r~=base[a] and ((l>base[a] and r<base[a]) or (l<base[a] and r>base[a])))
    if x or y then
      count=count+1; f:write(string.format("0x%04X,%d,%d,%d,%d,%d\n",a,base[a],u,d,l,r))
    end
  end
  f:write("candidates=",count,"\n"); f:close()
end
joypad.set({},1)
gui.text(4,4,"API calibration complete; report written", "lime", "black")
console.log("BizHawk API calibration complete: "..report_path)
for i=1,120 do emu.frameadvance() end
client.exit()
