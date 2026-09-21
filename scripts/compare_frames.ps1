param(
  [Parameter(Mandatory=$true)][string]$A,
  [Parameter(Mandatory=$true)][string]$B,
  [string]$Out = 'frame_diff.png'
)
Add-Type -AssemblyName System.Drawing
$ia=[Drawing.Bitmap]::new($A); $ib=[Drawing.Bitmap]::new($B)
if($ia.Width -ne $ib.Width -or $ia.Height -ne $ib.Height){ throw 'Image dimensions differ' }
$o=[Drawing.Bitmap]::new($ia.Width,$ia.Height)
$different=0
for($y=0;$y -lt $ia.Height;$y++){
  for($x=0;$x -lt $ia.Width;$x++){
    $p=$ia.GetPixel($x,$y); $q=$ib.GetPixel($x,$y)
    if([Math]::Abs($p.R-$q.R)+[Math]::Abs($p.G-$q.G)+[Math]::Abs($p.B-$q.B) -gt 24){ $o.SetPixel($x,$y,[Drawing.Color]::Red); $different++ }
    else { $o.SetPixel($x,$y,[Drawing.Color]::Black) }
  }
}
$o.Save($Out,[Drawing.Imaging.ImageFormat]::Png)
$ia.Dispose(); $ib.Dispose(); $o.Dispose()
Write-Output "different_pixels=$different output=$Out"
