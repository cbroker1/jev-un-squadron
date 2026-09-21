-- Continuous, passive marker check. No input injection, no savestate reloads.
memory.usememorydomain("WRAM")
client.unpause()
local shotdir = "C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\evidence\\screenshots"
os.execute('mkdir "' .. shotdir .. '" 2>nul')
local log=io.open(shotdir .. "\\marker_observations.csv","w")
if log then log:write("sample,frame,a_x1011,a_y1022,b_x0901,b_y002c,c_x0069,c_y1023,d_x0900,d_y1022\n") end
for i=1,600 do
  local x=memory.read_u8(0x1011); local y=memory.read_u8(0x002C)
  joypad.set({},1)
  gui.text(4,4,"PASSIVE candidate E marker (provisional)","white","black")
  gui.text(4,16,string.format("X=0x1011:%d Y=0x002C:%d frame=%d",x,y,emu.framecount()),"lime","black")
  gui.drawRectangle(x-8,y-8,16,16,0x00FF00FF,0x00000000)
  emu.frameadvance()
  if i==120 or i==360 or i==600 then
    client.screenshot(shotdir .. "\\marker_" .. tostring(i) .. ".png")
    if log then log:write(string.format("%d,%d,%d,%d\n",i,emu.framecount(),x,y)); log:flush() end
  end
end
joypad.set({},1)
if log then log:close() end
client.exit()
