# Put the two andersCH icons on the Desktop.
#
#   powershell -ExecutionPolicy Bypass -File desktop\install-shortcuts.ps1
#
# Creates two shortcuts, both pointing at this repo rather than copying anything, so a `git pull` updates the
# program and the icons keep working. Re-running is safe: existing shortcuts are overwritten in place.
#
# Remove them with:  powershell -ExecutionPolicy Bypass -File desktop\install-shortcuts.ps1 -Remove

param([switch]$Remove)

$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$icon    = Join-Path $here 'andersCH.ico'
$desktop = [Environment]::GetFolderPath('Desktop')

$links = @(
  @{ Name = 'andersCH - Onboarding.lnk'
     Target = (Join-Path $here 'andersCH.cmd')
     Desc = 'Client interview, then the real engine and the report' },
  @{ Name = 'andersCH - Uebersicht.lnk'
     Target = (Join-Path $here 'andersCH-Uebersicht.cmd')
     Desc = 'Everything that is built, from one page' }
)

if ($Remove) {
  foreach ($l in $links) {
    $p = Join-Path $desktop $l.Name
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  removed $($l.Name)" }
    else { Write-Host "  not present: $($l.Name)" }
  }
  exit 0
}

if (-not (Test-Path $icon)) {
  Write-Host "  The icon is missing. Generate it first:" -ForegroundColor Yellow
  Write-Host "    .venv\Scripts\python.exe desktop\make_icon.py"
  exit 1
}

$shell = New-Object -ComObject WScript.Shell
foreach ($l in $links) {
  if (-not (Test-Path $l.Target)) { Write-Host "  MISSING target: $($l.Target)" -ForegroundColor Yellow; continue }
  $path = Join-Path $desktop $l.Name
  $sc = $shell.CreateShortcut($path)
  $sc.TargetPath       = $l.Target
  # Start in the repo root so relative paths inside the program resolve the way they do from a terminal.
  $sc.WorkingDirectory = (Resolve-Path (Join-Path $here '..')).Path
  $sc.IconLocation     = "$icon,0"
  $sc.Description      = $l.Desc
  # Minimised: the console is only there to be closed when the user is finished, and a window full of HTTP log
  # lines in front of the browser looks like something went wrong.
  $sc.WindowStyle      = 7
  $sc.Save()
  Write-Host "  created $($l.Name)"
}
Write-Host ""
Write-Host "  Two icons are on your Desktop. Double-click either one; the browser opens by itself."
Write-Host "  Close the (minimised) console window to stop the program."
