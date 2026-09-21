$root=(Get-Location).Path
$cfg=Get-Content -Raw (Join-Path $root 'config.json') | ConvertFrom-Json
$exe=Join-Path $root 'bizhawk\EmuHawk.exe'
$lua=Join-Path $root 'lua\compare_markers.lua'
$args=@('--load-slot','1','--lua',('"'+$lua+'"'),('"'+$cfg.rom_path+'"'))
Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory (Join-Path $root 'bizhawk') -Wait
