$root=(Get-Location).Path
$old=Get-Process EmuHawk -ErrorAction SilentlyContinue
if ($old) { $old | Stop-Process -Force; Start-Sleep -Milliseconds 500 }
$cfg=Get-Content -Raw (Join-Path $root 'config.json') | ConvertFrom-Json
$exe=Join-Path $root 'bizhawk\EmuHawk.exe'
$lua=Join-Path $root 'lua\observe_health_perturb.lua'
$args=@('--load-slot','1','--lua',('"'+$lua+'"'),('"'+$cfg.rom_path+'"'))
$p=Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory (Join-Path $root 'bizhawk') -PassThru
$p.WaitForExit()
for ($n=0; $n -lt 30; $n++) { if (-not (Get-Process EmuHawk -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Milliseconds 500 }
