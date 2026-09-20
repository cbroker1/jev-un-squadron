$root = (Get-Location).Path
$old = Get-Process EmuHawk -ErrorAction SilentlyContinue
if ($old) { $old | Stop-Process -Force; Start-Sleep -Milliseconds 500 }
$cfg = Get-Content -Raw (Join-Path $root 'config.json') | ConvertFrom-Json
$exe = Join-Path $root 'bizhawk\EmuHawk.exe'
$lua = Join-Path $root 'lua\verify_marker.lua'
$args = @('--load-slot', '1', '--lua', ('"' + $lua + '"'), ('"' + $cfg.rom_path + '"'))
Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory (Join-Path $root 'bizhawk') -Wait
