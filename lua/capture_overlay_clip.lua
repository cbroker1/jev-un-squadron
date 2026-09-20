memory.usememorydomain("WRAM")
client.unpause()
client.setscreenshotosd(true)
for i=1,180 do
  local x=memory.read_u8(0x1011)
  local y=memory.read_u8(0x002C)
  gui.text(4,4,"OVERLAY MARKER CHECK","white","black")
  gui.text(4,16,string.format("PROVISIONAL X=%d Y=%d",x,y),"lime","black")
  gui.drawBox(x-5,y-5,x+5,y+5,0x00FF00FF,0x00000000)
  emu.frameadvance()
  if i==120 then client.screenshottoclipboard() end
end
client.exit()
