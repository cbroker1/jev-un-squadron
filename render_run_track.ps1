param(
  [Parameter(Mandatory=$true)][string]$Run,
  [string]$Slot='WRAM:0x1840',
  [Parameter(Mandatory=$true)][int[]]$Frames,
  [string]$Name='run_track_reference.png'
)
# Overlays one exported track (lime) and the player reference (cyan) from a runner's
# states.jsonl onto that run's own brain_frame screenshots. Boxes are reference points, NOT hitboxes.
Add-Type -AssemblyName System.Drawing
$folder=(Resolve-Path -LiteralPath $Run).Path
$wanted=@{}
foreach ($line in [IO.File]::ReadLines((Join-Path $folder 'states.jsonl'))) {
  if ($line -notmatch '"frame": (\d+),') { continue }
  if ($Frames -notcontains [int]$Matches[1] -or $wanted.ContainsKey([int]$Matches[1])) { continue }
  $record=$line | ConvertFrom-Json
  $track=@($record.observation.tracks | Where-Object { $_.slot -eq $Slot })
  if ($track.Count -ne 1) { throw "Slot $Slot missing from frame $($record.state.frame)" }
  $wanted[[int]$record.state.frame]=@{track=$track[0]; player=$record.observation.player}
}
$sheet=[Drawing.Bitmap]::new(768,260*[int][math]::Ceiling($Frames.Count/3))
$g=[Drawing.Graphics]::FromImage($sheet)
$g.Clear([Drawing.Color]::FromArgb(20,20,20))
$font=[Drawing.Font]::new('Consolas',9)
$pen=[Drawing.Pen]::new([Drawing.Color]::Lime,2)
$cyan=[Drawing.Pen]::new([Drawing.Color]::Cyan,1)
$n=0
foreach ($frame in $Frames) {
  $shot=Join-Path $folder "brain_frame_$frame.png"
  if (-not $wanted.ContainsKey($frame) -or -not (Test-Path -LiteralPath $shot)) { throw "No state/screenshot pair for frame $frame" }
  $t=$wanted[$frame].track; $p=$wanted[$frame].player
  $ox=($n%3)*256; $oy=[int][math]::Floor($n/3)*260
  $im=[Drawing.Bitmap]::new($shot)
  $g.DrawImage($im,[Drawing.Rectangle]::new($ox,$oy+24,256,224),0,0,256,224,[Drawing.GraphicsUnit]::Pixel)
  $im.Dispose()
  $marked=$t.phase -eq 'observed_moving_signature' -and $t.on_screen
  if ($marked) { $g.DrawRectangle($pen,[single]($ox+$t.x-5),[single]($oy+24+$t.y-5),[single]10,[single]10) }
  $g.DrawRectangle($cyan,[single]($ox+$p.x-4),[single]($oy+24+$p.y-4),[single]8,[single]8)
  $g.DrawString("game $frame / generation $($t.generation)",$font,[Drawing.Brushes]::White,$ox,$oy+4)
  $state=if ($marked) { 'marked' } elseif ($t.phase -ne 'observed_moving_signature') { 'gate off' } else { 'off-screen' }
  $g.DrawString(('{0} {1} XY={2:0.0},{3:0.0}' -f $Slot,$state,$t.x,$t.y),$font,[Drawing.Brushes]::Lime,$ox,$oy+246)
  $n++
}
$out=Join-Path $folder $Name
$sheet.Save($out,[Drawing.Imaging.ImageFormat]::Png)
$pen.Dispose(); $cyan.Dispose(); $font.Dispose(); $g.Dispose(); $sheet.Dispose()
Write-Output $out
