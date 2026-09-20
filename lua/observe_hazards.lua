-- Hazard observation groundwork. Uses verified firing only; no guessed object addresses.
memory.usememorydomain("WRAM")
client.unpause()
local root="C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\hazard_observation\\run_"..os.time()
os.execute('mkdir "'..root..'" 2>nul')
local log=io.open(root.."\\changes.csv","w")
if log then log:write("frame,address,previous,current\n") end
local previous={}
for a=0,0x1FFFF do previous[a]=memory.read_u8(a) end
for i=1,900 do
  local x=memory.read_u8(0x1011); local y=memory.read_u8(0x002C)
  joypad.set({Y=true},1)
  emu.frameadvance()
  if i%2==0 then
    for a=0,0x1FFFF do
      local v=memory.read_u8(a)
      if v~=previous[a] and log then log:write(string.format("%d,0x%04X,%d,%d\n",emu.framecount(),a,previous[a],v)) end
      previous[a]=v
    end
    if log then log:flush() end
  end
  gui.text(4,4,"HAZARD OBSERVATION: object addresses unverified","white","black")
  gui.text(4,16,string.format("player candidate X=%d Y=%d; fire=Y",x,y),"lime","black")
  gui.drawBox(x-4,y-4,x+4,y+4,0x00FF00FF,0x00000000)
  if i%10==0 then client.screenshot(root.."\\frame_"..tostring(i)..".png") end
end
joypad.set({},1)
if log then log:close() end
client.exit()
