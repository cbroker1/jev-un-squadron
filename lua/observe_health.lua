-- Passive health/damage observation. No controls, no Jev, no savestate reload.
memory.usememorydomain("WRAM")
client.unpause()
local root="C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\health_observation\\run_"..os.time()
os.execute('mkdir "'..root..'" 2>nul')
local log=io.open(root.."\\changes.csv","w")
if log then log:write("frame,address,previous,current\n") end
local previous={}
for a=0,0x1FFFF do previous[a]=memory.read_u8(a) end
for i=1,900 do
  joypad.set({},1)
  emu.frameadvance()
  if i%10==0 then
    for a=0,0x1FFFF do
      local v=memory.read_u8(a); if v~=previous[a] and log then log:write(string.format("%d,0x%04X,%d,%d\n",emu.framecount(),a,previous[a],v)) end; previous[a]=v
    end
    if log then log:flush() end
  end
  if i%60==0 then client.screenshot(root.."\\frame_"..tostring(i)..".png") end
end
joypad.set({},1)
if log then log:close() end
client.exit()
