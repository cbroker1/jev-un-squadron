param(
  [Parameter(Mandatory=$true)][string]$Run,
  [Parameter(Mandatory=$true)][string[]]$Routines,
  [Parameter(Mandatory=$true)][int[]]$Samples,
  [string]$Name='object_types.png'
)
# Boxes each surveyed object of the given routine addresses on its exact captured frame.
# Reads object_points.csv from survey_objects.py. Boxes are reference points, NOT hitboxes.
Add-Type -AssemblyName System.Drawing
$folder=(Resolve-Path -LiteralPath $Run).Path
$rows=@(Import-Csv (Join-Path $folder 'frames.csv'))
$points=@(Import-Csv (Join-Path $folder 'object_points.csv') | Where-Object { $Routines -contains $_.routine -and $_.on_screen -eq 'True' })
$colors=@([Drawing.Color]::Lime,[Drawing.Color]::Magenta,[Drawing.Color]::Cyan,[Drawing.Color]::Yellow,[Drawing.Color]::OrangeRed,[Drawing.Color]::White)
$sheet=[Drawing.Bitmap]::new(768,260*[int][math]::Ceiling($Samples.Count/3))
$g=[Drawing.Graphics]::FromImage($sheet)
$g.Clear([Drawing.Color]::FromArgb(20,20,20))
$font=[Drawing.Font]::new('Consolas',8)
$n=0
foreach ($sample in $Samples) {
  $row=$rows | Where-Object {[int]$_.sample -eq $sample} | Select-Object -First 1
  if (-not $row) { throw "Missing sample $sample" }
  $ox=($n%3)*256; $oy=[int][math]::Floor($n/3)*260
  $im=[Drawing.Bitmap]::new((Join-Path $folder $row.screenshot))
  $g.DrawImage($im,[Drawing.Rectangle]::new($ox,$oy+24,256,224),0,0,256,224,[Drawing.GraphicsUnit]::Pixel)
  $im.Dispose()
  foreach ($p in ($points | Where-Object {[int]$_.sample -eq $sample})) {
    $c=$colors[[array]::IndexOf($Routines,$p.routine) % $colors.Count]
    $pen=[Drawing.Pen]::new($c,1)
    $g.DrawRectangle($pen,[single]($ox+[double]$p.x-4),[single]($oy+24+[double]$p.y-4),[single]8,[single]8)
    $g.DrawString($p.slot.Substring(2),$font,[Drawing.SolidBrush]::new($c),[single]($ox+[double]$p.x+5),[single]($oy+24+[double]$p.y-5))
    $pen.Dispose()
  }
  $g.DrawString("sample $sample / game $($row.emu_frame)",$font,[Drawing.Brushes]::White,$ox,$oy+4)
  $legend=($Routines | ForEach-Object { $_ }) -join '  '
  $g.DrawString($legend,$font,[Drawing.Brushes]::Silver,$ox,$oy+248)
  $n++
}
$out=Join-Path $folder $Name
$sheet.Save($out,[Drawing.Imaging.ImageFormat]::Png)
$font.Dispose(); $g.Dispose(); $sheet.Dispose()
Write-Output $out
