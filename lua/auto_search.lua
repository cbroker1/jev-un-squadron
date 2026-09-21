-- Automated exploratory RAM search. Stop main.lua before starting this.
-- It reports candidates only; a candidate still needs visual validation.
memory.usememorydomain("WRAM")
local N = 0x20000
local function snap()
  local t = {}
  for a = 0, N - 1 do t[a] = memory.read_u8(a) end
  return t
end
local function frames(n, pad)
  for i = 1, n do joypad.set(pad or {}, 1); emu.frameadvance() end
  joypad.set({}, 1)
end
local function save_report(lines)
  local f = io.open("C:\\Users\\Carl-MainRig\\Projects\\jev-un-squadron\\evidence\\probes\\ram_candidates.txt", "w")
  if f then for _, line in ipairs(lines) do f:write(line, "\n") end; f:close() end
end

local out = {"Automated RAM search; WRAM; 8-bit unsigned; 3 cycles", "address,consistent_cycles,last_baseline,last_neutral,last_up,last_down"}
local scores = {}; local last = {}
for cycle = 1, 3 do
  frames(10, {})
  local base = snap(); frames(30, {}); local neutral = snap()
  frames(20, {Up=true}); local up = snap()
  frames(20, {Down=true}); local down = snap()
  for a = 0, N - 1 do
    if neutral[a] == base[a] and up[a] ~= neutral[a] and down[a] ~= up[a] then
      local du, dd = up[a] - neutral[a], down[a] - up[a]
      if (du > 0 and dd < 0) or (du < 0 and dd > 0) then
        scores[a] = (scores[a] or 0) + 1
        last[a] = {base[a], neutral[a], up[a], down[a]}
      end
    end
  end
end
local count = 0
for a = 0, N - 1 do
  if scores[a] == 3 then
    local v = last[a]
    out[#out + 1] = string.format("0x%04X,%d,%d,%d,%d,%d", a, scores[a], v[1], v[2], v[3], v[4])
    count = count + 1
  end
end
out[1] = out[1] .. "\ncandidates=" .. count
save_report(out)
console.log("Automated RAM search complete: " .. count .. " candidates. See ram_candidates.txt")
joypad.set({}, 1)
