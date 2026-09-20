Write-Host "LIVE JEV MODE CHECKLIST"
Write-Host "- BizHawk: aircraft visible in active gameplay"
Write-Host "- Lua main.lua: active"
Write-Host "- Keep BizHawk unpaused"
Write-Host "- Stop early with Ctrl+C; controls release safely"
Write-Host "- Maximum calls: 60"
Write-Host ""
$keyFile = Join-Path (Get-Location) 'typesafe_api_key.txt'
if (Test-Path -LiteralPath $keyFile) {
  $env:TYPESAFE_API_KEY = (Get-Content -LiteralPath $keyFile -Raw).Trim()
  $ptr = [IntPtr]::Zero
} else {
  $secret = Read-Host "Enter TypeSafe API key (input is masked; it will not be saved)" -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
  $env:TYPESAFE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
}
try {
  python bridge.py --live
} finally {
  if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
  Remove-Item Env:TYPESAFE_API_KEY -ErrorAction SilentlyContinue
}
