# Put the eigentliCH icon on the Desktop.
#
# The product was eigentliCH until 20 September 2026. Display name is eigentliCH; filenames are
# lowercase `eigentlich`, which is why the .cmd and the .ico below are spelled that way.
#
#   powershell -ExecutionPolicy Bypass -File desktop\install-shortcut.ps1
#
# Creates ONE shortcut pointing at this repo rather than copying anything, so an edit here updates the
# program and the icon keeps working. Re-running is safe: an existing shortcut is overwritten in place.
#
# This does NOT touch the estate's two icons ("eigentliCH - Onboarding" and "eigentliCH - Uebersicht"). Those
# launch the existing desktop hub, which is still live -- DECISIONS.md A1 keeps both estates. Three icons
# is the intended end state, not an accident.
#
# Remove it with:  powershell -ExecutionPolicy Bypass -File desktop\install-shortcut.ps1 -Remove

param([switch]$Remove)

$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$root    = Resolve-Path (Join-Path $here '..')
$icon    = Join-Path $here 'eigentlich.ico'
$target  = Join-Path $here 'eigentlich.cmd'
$desktop = [Environment]::GetFolderPath('Desktop')
$name    = 'eigentliCH.lnk'
$path    = Join-Path $desktop $name

if ($Remove) {
  if (Test-Path $path) { Remove-Item $path -Force; Write-Host "  removed $name" }
  else { Write-Host "  not present: $name" }
  exit 0
}

if (-not (Test-Path $icon)) {
  Write-Host "  The icon is missing. Generate it first:" -ForegroundColor Yellow
  Write-Host "    .venv\Scripts\python.exe desktop\make_icon.py"
  exit 1
}
if (-not (Test-Path $target)) {
  Write-Host "  MISSING target: $target" -ForegroundColor Yellow
  exit 1
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($path)
$sc.TargetPath       = $target
# Start in the prototype2 root so relative paths resolve the way they do from a terminal.
$sc.WorkingDirectory = $root.Path
$sc.IconLocation     = "$icon,0"
$sc.Description      = 'eigentliCH - the member application'
# Minimised: the console exists to be closed when you are finished, and a window of HTTP log lines in
# front of the browser looks like something went wrong.
$sc.WindowStyle      = 7
$sc.Save()

Write-Host "  created $name"
Write-Host ""
Write-Host "  Double-click it; the browser opens by itself at http://127.0.0.1:8420/"
Write-Host "  Close the (minimised) console window to stop the program."
Write-Host ""
Write-Host "  The estate's two icons are untouched and still work."
