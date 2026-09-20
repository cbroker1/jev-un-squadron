-- Focused first-damage observation with verified main-gun pulses.
memory.usememorydomain("WRAM")
client.unpause()
local root="C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\health_observation\\first_damage_fire_"..os.time()
os.execute('mkdir "'..root..'" 2>nul')
local log=io.open(root.."\\changes.csv","w")
if log then log:write("frame,address,previous,current\n") end
local previous={}
for a=0,0x1FFFF do previous[a]=memory.read_u8(a) end
for i=1,700 do
  local pad={}
  if i%6==0 then pad.Y=true end
  joypad.set(pad,1)
  emu.frameadvance()
  if i%2==0 then
    for a=0,0x1FFFF do
      local v=memory.read_u8(a)
      if v~=previous[a] and log then log:write(string.format("%d,0x%04X,%d,%d\n",emu.framecount(),a,previous[a],v)) end
      previous[a]=v
    end
    if log then log:flush() end
  end
  if i>=500 and i%2==0 then client.screenshot(root.."\\frame_"..tostring(i)..".png") end
end
joypad.set({},1)
if log then log:close() end
client.exit()
