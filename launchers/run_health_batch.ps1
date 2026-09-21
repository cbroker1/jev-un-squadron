$root=(Get-Location).Path
for ($i=1; $i -le 3; $i++) {
  Write-Host "Starting passive health run $i/3"
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'launchers\run_health_observe.ps1')
  if (Get-Process EmuHawk -ErrorAction SilentlyContinue) {
    Write-Warning "EmuHawk remained after run $i; stopping it before the next clean run."
    Get-Process EmuHawk -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500
  }
}
