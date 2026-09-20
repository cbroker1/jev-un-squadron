-- Passive comparison of candidate coordinate pairs; no input, no savestate reload.
memory.usememorydomain("WRAM")
local pairs = {
  {"A",0x1011,0x1022,0x00FF00FF},
  {"B",0x0901,0x002C,0xFF00FFFF},
  {"C",0x0069,0x1023,0x00FFFFFF},
  {"D",0x0900,0x1022,0xFFFF00FF},
}
for i=1,900 do
  joypad.set({},1)
  gui.text(4,4,"PASSIVE candidate comparison", "white", "black")
  for n,p in ipairs(pairs) do
    local x=memory.read_u8(p[2]); local y=memory.read_u8(p[3])
    gui.text(4,4+n*12,string.format("%s X=%d Y=%d",p[1],x,y),p[4],"black")
    gui.drawRectangle(x-5,y-5,10,10,p[4],0x00000000)
  end
  emu.frameadvance()
end
joypad.set({},1)
client.exit()
