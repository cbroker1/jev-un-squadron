$root=(Get-Location).Path
$cfg=Get-Content -Raw (Join-Path $root 'config.json') | ConvertFrom-Json
Get-Process EmuHawk -ErrorAction SilentlyContinue | Stop-Process -Force
$exe=Join-Path $root 'bizhawk\EmuHawk.exe'
$lua=Join-Path $root 'lua\main.lua'
$args=@('--load-slot','1','--lua',('"'+$lua+'"'),('"'+$cfg.rom_path+'"'))
Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory (Join-Path $root 'bizhawk') | Out-Null
Start-Sleep -Seconds 4
$keyFile=Join-Path $root 'typesafe_api_key.txt'
if (-not (Test-Path -LiteralPath $keyFile)) { throw 'typesafe_api_key.txt is missing; no key was requested or printed.' }
$env:TYPESAFE_API_KEY=(Get-Content -LiteralPath $keyFile -Raw).Trim()
try { python bridge.py --live --max-calls 5 }
finally {
  Remove-Item Env:TYPESAFE_API_KEY -ErrorAction SilentlyContinue
  Get-Process EmuHawk -ErrorAction SilentlyContinue | Stop-Process -Force
}
