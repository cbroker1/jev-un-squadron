-- Visual-only validation aid. Candidate boxes are unverified and never control play.
memory.usememorydomain("WRAM")
client.unpause()
local candidates={
 {"A",0x1757,0x1758,0x00FF00FF},
 {"B",0x1717,0x1718,0xFF00FFFF},
 {"C",0x1797,0x1798,0xFFFF00FF},
 {"D",0x16D7,0x16D8,0x00FFFFFF},
 {"E",0x171A,0x171B,0xFF8000FF}
}
for i=1,600 do
  joypad.set({Y=true},1)
  emu.frameadvance()
  gui.text(4,4,"UNVERIFIED HAZARD CANDIDATES; Y FIRE ONLY","white","black")
  for n,c in ipairs(candidates) do
    local x=memory.read_u8(c[2]); local y=memory.read_u8(c[3])
    gui.text(4,4+n*12,string.format("%s X=0x%04X:%d Y=0x%04X:%d",c[1],c[2],x,c[3],y),c[4],"black")
    if x<256 and y<224 then gui.drawRectangle(x-5,y-5,10,10,c[4],0x00000000) end
  end
end
joypad.set({},1)
client.exit()
