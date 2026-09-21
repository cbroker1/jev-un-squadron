-- Replay a run's recorded inputs and write a save state at a chosen frame.
--
-- Reaching the boss live happens in about a third of runs, so waiting for one to get there
-- while carrying a --save-at-frame is slow and wasteful. A run that already reached it is
-- on disk; replaying its inputs reproduces the same frames exactly.
--
-- Read-only apart from the save slot it is told to write. Slot 1, the evidence baseline,
-- is refused outright. No Jev, no decisions.
local ROOT = "C:/Users/Carl-MainRig/Projects/jev-un-squadron/"
local TARGET = tonumber(os.getenv("JEV_SAVE_AT_FRAME") or "") or 0
local SLOT = tonumber(os.getenv("JEV_SAVE_SLOT") or "") or 3
local INPUTS = os.getenv("JEV_REPLAY_INPUTS")

local KEYS = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}

local function pad_from_mask(mask)
  local pad = {}
  for index, key in ipairs(KEYS) do
    pad[key] = (mask % (2^index)) >= 2^(index-1)
  end
  return pad
end

local function main()
  assert(SLOT ~= 1, "slot 1 is the evidence baseline and is never written")
  assert(INPUTS, "needs JEV_REPLAY_INPUTS")
  assert(TARGET > 0, "needs JEV_SAVE_AT_FRAME")
  local replay = {}
  local first = true
  for line in io.lines(INPUTS) do
    if first then
      first = false
    else
      local frame, mask = line:match("^(%d+),%d+,[^,]*,%d+,[^,]*,(%d+),")
      if frame then replay[tonumber(frame)] = tonumber(mask) end
    end
  end
  client.speedmode(400)
  emu.limitframerate(false)
  while emu.framecount() < TARGET do
    joypad.set(pad_from_mask(replay[emu.framecount()] or 0), 1)
    emu.frameadvance()
  end
  -- Render a frame at normal speed so the saved state is a clean one.
  client.speedmode(100)
  emu.limitframerate(true)
  joypad.set(pad_from_mask(replay[emu.framecount()] or 0), 1)
  emu.frameadvance()
  local ok = pcall(savestate.saveslot, SLOT)
  memory.usememorydomain("WRAM")
  local note = assert(io.open(ROOT .. "evidence/probes/vram_probe.txt", "w"))
  note:write(string.format("slot %d %s at frame %d, player %d,%d\n", SLOT,
    ok and "saved" or "FAILED", emu.framecount(),
    memory.read_u8(0x1011), memory.read_u8(0x1014)))
  note:close()
end

local ok, err = pcall(main)
if not ok then
  local note = assert(io.open(ROOT .. "evidence/probes/vram_probe.txt", "w"))
  note:write("probe failed: " .. tostring(err) .. "\n")
  note:close()
end
client.exit()
