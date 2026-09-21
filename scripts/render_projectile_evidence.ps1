param(
  [Parameter(Mandatory=$true)][string]$Run,
  [int]$XAddress=0x1AD1,
  [int]$YAddress=0x1AD4,
  [int]$OffsetX=0,
  [int]$OffsetY=0,
  [int[]]$Samples=@(564,568,580,598,610,622),
  [string]$Name='projectile_contact_sheet.png',
  [switch]$ProjectileProfile,
  [switch]$EnemyProfile,
  [int[]]$ProjectileBases=@(0x1AC0)
)
# Exact captured frame plus a RAM-coordinate marker. The box is NOT a collision box.
Add-Type -AssemblyName System.Drawing
$folder=(Resolve-Path -LiteralPath $Run).Path
$rows=@(Import-Csv (Join-Path $folder 'frames.csv'))
$raw=[IO.File]::ReadAllBytes((Join-Path $folder 'wram_u8.bin'))
if ($raw.Length -ne $rows.Count*0x20000) { throw 'Incomplete frame/RAM capture' }
$sheet=[Drawing.Bitmap]::new(768,260*[int][math]::Ceiling($Samples.Count/3))
$g=[Drawing.Graphics]::FromImage($sheet)
$g.Clear([Drawing.Color]::FromArgb(20,20,20))
$font=[Drawing.Font]::new('Consolas',9)
$pen=[Drawing.Pen]::new([Drawing.Color]::Lime,1)
$n=0
foreach($sample in $Samples) {
  $row=$rows | Where-Object {[int]$_.sample -eq $sample} | Select-Object -First 1
  if (-not $row) { throw "Missing sample $sample" }
  $im=[Drawing.Bitmap]::new((Join-Path $folder $row.screenshot))
  $ox=($n%3)*256; $oy=[int][math]::Floor($n/3)*260
  # Explicit pixel rectangles avoid PNG DPI metadata silently shrinking the image.
  $destination=[Drawing.Rectangle]::new($ox,$oy+24,256,224)
  $g.DrawImage($im,$destination,0,0,256,224,[Drawing.GraphicsUnit]::Pixel)
  $o=[int]$row.snapshot_index*0x20000
  $x=[int]$raw[$o+$XAddress]; $y=[int]$raw[$o+$YAddress]
  $draw=$true
  if ($ProjectileProfile -or $EnemyProfile) {
    foreach ($base in $ProjectileBases) {
      $x=[BitConverter]::ToInt16($raw,$o+$base+17)+$raw[$o+$base+16]/256
      $y=[BitConverter]::ToInt16($raw,$o+$base+20)+$raw[$o+$base+19]/256
      $draw=$raw[$o+$base] -eq 0xCC -and $raw[$o+$base+1] -eq 0x7F -and $raw[$o+$base+2] -eq 0xF9 -and $raw[$o+$base+3] -eq 4 -and $raw[$o+$base+8] -eq 1
      if ($EnemyProfile) { $draw=$raw[$o+$base] -eq 0xC8 -and $raw[$o+$base+1] -eq 0x4A -and $raw[$o+$base+2] -eq 0xB0 -and $raw[$o+$base+3] -eq 2 -and $raw[$o+$base+8] -eq 3 }
      $gated=$draw
      $draw=$draw -and $x -ge 0 -and $x -lt 256 -and $y -ge 0 -and $y -lt 224
      if ($draw) {
        $g.DrawRectangle($pen,[single]($ox+$x-4),[single]($oy+24+$y-4),[single]8,[single]8)
        if ($ProjectileBases.Count -gt 1) { $g.DrawString(('{0:X4}' -f $base),$font,[Drawing.Brushes]::Lime,[single]($ox+$x+5),[single]($oy+24+$y-4)) }
      }
    }
    $draw=$false
  }
  if ($draw) { $g.DrawRectangle($pen,[single]($ox+$x+$OffsetX-4),[single]($oy+24+$y+$OffsetY-4),[single]8,[single]8) }
  $g.DrawString("sample $sample / game $($row.emu_frame)",$font,[Drawing.Brushes]::White,$ox,$oy+4)
  # Single-base enemy sheets show the gate byte and 16.8 decode so hidden markers can be audited.
  $label = if ($EnemyProfile -and $ProjectileBases.Count -eq 1) {
    $state = if (-not $gated) { 'gate off' } elseif ($x -lt 0 -or $x -ge 256 -or $y -lt 0 -or $y -ge 224) { 'off-screen' } else { 'marked' }
    '{0:X4}[0]={1:X2} {2} XY={3:0.0},{4:0.0}' -f $ProjectileBases[0],$raw[$o+$ProjectileBases[0]],$state,$x,$y
  } elseif ($EnemyProfile) { 'Enemy reference candidates, not hitboxes' } elseif ($ProjectileProfile -and $ProjectileBases.Count -gt 1) { 'Gated candidate reference points' } elseif ($ProjectileProfile) { '1AC0={0:X2}  XY={1:0.0},{2:0.0}' -f $raw[$o+0x1AC0],$x,$y } else { 'RAM {0:X4}/{1:X4}: {2},{3}' -f $XAddress,$YAddress,$x,$y }
  $g.DrawString($label,$font,[Drawing.Brushes]::Lime,$ox,$oy+246)
  $im.Dispose(); $n++
}
$out=Join-Path $folder $Name
$sheet.Save($out,[Drawing.Imaging.ImageFormat]::Png)
$pen.Dispose(); $font.Dispose(); $g.Dispose(); $sheet.Dispose()
Write-Output $out
