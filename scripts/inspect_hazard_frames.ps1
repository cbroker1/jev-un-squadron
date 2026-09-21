param(
  [Parameter(Mandatory=$true)][string]$Run,
  [ValidateSet('cyan','shot','green','orange')][string]$Kind='cyan'
)
# Offline visual measurement only. Cyan pixels are NOT an enemy/object classifier.
Add-Type -AssemblyName System.Drawing
$folder = (Resolve-Path -LiteralPath $Run).Path
$rows = @(Import-Csv (Join-Path $folder 'frames.csv'))
$measurements = [Collections.Generic.List[object]]::new()
foreach ($row in $rows) {
  if (-not $row.screenshot) { throw 'Requires explicit screenshot/snapshot metadata' }
  $im = [Drawing.Bitmap]::new((Join-Path $folder $row.screenshot))
  if ($im.Width -ne 256 -or $im.Height -ne 224) { $im.Dispose(); throw 'Expected raw 256x224 image' }
  $remaining = [Collections.Generic.HashSet[int]]::new()
  for ($y=40; $y -lt 200; $y++) {
    for ($x=0; $x -lt 256; $x++) {
      $pixel = $im.GetPixel($x,$y)
      $selected = if ($Kind -eq 'cyan') {
        $pixel.R -le 100 -and $pixel.G -ge 140 -and $pixel.B -ge 225
      } elseif ($Kind -eq 'shot') {
        # Early single-shot probes only: orange/white pixels to the right of player.
        [int]$row.sample -le 60 -and $x -gt 114 -and $pixel.R -ge 230 -and $pixel.G -ge 60
      } elseif ($Kind -eq 'orange') {
        # Discovery only: color cannot distinguish an aircraft from effects.
        $pixel.R -ge 220 -and $pixel.G -ge 100 -and $pixel.G -le 220 -and $pixel.B -le 100
      } else {
        $y -lt 125 -and $pixel.G -gt ($pixel.R+10) -and $pixel.G -gt ($pixel.B+40)
      }
      if ($selected) {
        [void]$remaining.Add($y*256+$x)
      }
    }
  }
  $im.Dispose()
  $component=0
  while ($remaining.Count -gt 0) {
    $first = @($remaining)[0]
    [void]$remaining.Remove($first)
    $queue = [Collections.Generic.Queue[int]]::new()
    $queue.Enqueue($first)
    $xs=[Collections.Generic.List[int]]::new(); $ys=[Collections.Generic.List[int]]::new()
    while ($queue.Count -gt 0) {
      $p=$queue.Dequeue(); $x=$p%256; $y=[math]::Floor($p/256)
      $xs.Add($x); $ys.Add($y)
      foreach ($dy in -1,0,1) {
        foreach ($dx in -1,0,1) {
          $xx=$x+$dx; $yy=$y+$dy
          if ($xx -ge 0 -and $xx -lt 256 -and $yy -ge 40 -and $yy -lt 200) {
            $q=$yy*256+$xx
            if ($remaining.Remove($q)) { $queue.Enqueue($q) }
          }
        }
      }
    }
    if ($xs.Count -lt 2) { continue }
    $xm=$xs | Measure-Object -Minimum -Maximum
    $ym=$ys | Measure-Object -Minimum -Maximum
    $measurements.Add([pscustomobject]@{
      sample=$row.sample; emu_frame=$row.emu_frame; snapshot_index=$row.snapshot_index
      component=$component; pixels=$xs.Count
      min_x=$xm.Minimum; max_x=$xm.Maximum; min_y=$ym.Minimum; max_y=$ym.Maximum
      center_x=($xm.Minimum+$xm.Maximum)/2; center_y=($ym.Minimum+$ym.Maximum)/2
      screenshot=$row.screenshot; interpretation="unclassified $Kind sprite pixels"
    })
    $component++
  }
}
$out=Join-Path $folder ($Kind+'_components.csv')
$measurements | Export-Csv -LiteralPath $out -NoTypeInformation
Write-Output "Measured $($measurements.Count) $Kind components: $out"
