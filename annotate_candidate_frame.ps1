param(
  [Parameter(Mandatory=$true)][string]$Run,
  [int]$Sample = 600,
  [string]$ImageName = ''
)
Add-Type -AssemblyName System.Drawing
$raw=[IO.File]::ReadAllBytes((Join-Path $Run 'wram_u8.bin'))
$meta=@(Import-Csv (Join-Path $Run 'frames.csv'))
$row=$meta | Where-Object {[int]$_.sample -eq $Sample} | Select-Object -First 1
if (-not $row) { throw 'Requested sample is not present in frames.csv' }
if (-not $ImageName) {
  $ImageName=if ($row.screenshot) { $row.screenshot } else { 'frame_'+$Sample+'.png' }
}
$img=[System.Drawing.Bitmap]::new((Join-Path $Run $ImageName))
$g=[System.Drawing.Graphics]::FromImage($img)
$scaleX=$img.Width/256.0; $scaleY=$img.Height/224.0
$rawIndex=if ($null -ne $row.snapshot_index) { [int]$row.snapshot_index } else { [array]::IndexOf($meta,$row) }
if ($raw.Length -ne $meta.Count*0x20000) { throw 'Incomplete binary or frame log; refusing annotation' }
if($row){
  $px=[int]$row.player_x; $py=[int]$row.player_y
  $pen=[Drawing.Pen]::new([Drawing.Color]::Blue,3)
  $g.DrawRectangle($pen,[float](($px-6)*$scaleX),[float](($py-6)*$scaleY),[float](12*$scaleX),[float](12*$scaleY))
  $g.DrawString("P:$px,$py",[Drawing.Font]::new('Arial',10),[Drawing.Brushes]::Blue,[float]($px*$scaleX),[float](($py+8)*$scaleY))
  $pen.Dispose()
}
$candidates=@(
  @('A',0x00CF,0x00D0,[Drawing.Color]::Magenta),
  @('B',0x0068,0x0069,[Drawing.Color]::Yellow),
  @('C',0x090B,0x090C,[Drawing.Color]::Cyan),
  @('D',0x1710,0x1711,[Drawing.Color]::Lime),
  @('E',0x16F5,0x16F6,[Drawing.Color]::Orange),
  @('F',0x0908,0x0909,[Drawing.Color]::Red),
  @('G',0x0917,0x0918,[Drawing.Color]::White)
  ,@('H',0x0958,0x0959,[Drawing.Color]::DeepPink)
)
foreach($c in $candidates){
  $x=$raw[$rawIndex*0x20000+$c[1]]; $y=$raw[$rawIndex*0x20000+$c[2]]
  Write-Output "$($c[0]) rawIndex=$rawIndex x=$x y=$y"
  if($x -lt 256 -and $y -lt 224){
    $pen=[Drawing.Pen]::new($c[3],2)
    $g.DrawRectangle($pen,[float](($x-5)*$scaleX),[float](($y-5)*$scaleY),[float](10*$scaleX),[float](10*$scaleY))
    $g.DrawString("$($c[0]):$x,$y",[Drawing.Font]::new('Arial',9),[Drawing.Brushes]::White,[float]($x*$scaleX),[float]($y*$scaleY))
    $pen.Dispose()
  }
}
$out=Join-Path $Run ('annotated_'+[IO.Path]::GetFileNameWithoutExtension($ImageName)+'.png')
$img.Save($out,[Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $img.Dispose()
Write-Output $out
