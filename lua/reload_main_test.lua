-- Test-only wrapper: rewind slot 1 once while main.lua is active.
local count=0
function bridge_test_tick()
  count=count+1
  if count==60 then savestate.loadslot(1, true) end
end
dofile("C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\lua\\main.lua")
