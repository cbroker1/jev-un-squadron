-- Play a recorded run back on screen at normal speed, so it can be watched.
--
-- The inputs Lua actually sent are in the run's inputs.csv, so replaying them reproduces
-- the run exactly. Nothing is decided here and no request is made: it is a recording.
local ROOT = "C:/Users/Carl-MainRig/Projects/jev-un-squadron/"
local INPUTS = assert(os.getenv("JEV_REPLAY_INPUTS"), "needs JEV_REPLAY_INPUTS")
local LABEL = os.getenv("JEV_REPLAY_LABEL") or "?"
local STOP_AT = tonumber(os.getenv("JEV_REPLAY_STOP") or "") or 0
local SPEED = tonumber(os.getenv("JEV_REPLAY_SPEED") or "") or 100

local KEYS = {"Up", "Down", "Left", "Right", "A", "B", "X", "Y", "L", "R", "Start", "Select"}

local function pad_from_mask(mask)
  local pad = {}
  for index, key in ipairs(KEYS) do
    pad[key] = (mask % (2^index)) >= 2^(index-1)
  end
  return pad
end

local function label_frame(frame, first, last)
  pcall(function()
    gui.drawRectangle(2, 2, 116, 23, 0xFF000000, 0xC0101010)
    gui.drawText(5, 3, string.format("REPLAY R%s", LABEL), 0xFFFF8040, 0xFF000000, 11)
    gui.drawText(5, 14, string.format("f%d  %d of %d", frame, frame-first, last-first),
      0xFFFFFFFF, 0xFF000000, 11)
  end)
end

local function main()
  local replay, first, last = {}, nil, 0
  local header = true
  for line in io.lines(INPUTS) do
    if header then
      header = false
    else
      local frame, mask = line:match("^(%d+),%d+,[^,]*,%d+,[^,]*,(%d+),")
      if frame then
        frame = tonumber(frame)
        replay[frame] = tonumber(mask)
        first = first or frame
        if frame > last then last = frame end
      end
    end
  end
  if STOP_AT > 0 then last = STOP_AT end
  client.speedmode(SPEED)
  emu.limitframerate(true)
  client.setscreenshotosd(false)
  while emu.framecount() <= last do
    joypad.set(pad_from_mask(replay[emu.framecount()] or 0), 1)
    label_frame(emu.framecount(), first or 0, last)
    emu.frameadvance()
  end
  -- Hold the final frame briefly so the ending is visible rather than flashing past.
  for _ = 1, 90 do
    label_frame(emu.framecount(), first or 0, last)
    emu.frameadvance()
  end
end

local ok, err = pcall(main)
local note = assert(io.open(ROOT .. "replay_note.txt", "w"))
note:write(ok and "replay finished\n" or ("replay failed: " .. tostring(err) .. "\n"))
note:close()
client.exit()
