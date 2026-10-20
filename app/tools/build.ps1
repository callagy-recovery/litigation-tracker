# Builds "Litigation Tracker.exe" (the dashboard launcher) into the project folder, and the daily update exe.
#   powershell -ExecutionPolicy Bypass -File "\\crfiles\ALL\Litigation Tracker\app\tools\build.ps1"
# Optional: -Dest <folder> puts the dashboard exe somewhere else (a test copy); -SkipDaily leaves the daily update alone.
#
# The dashboard exe is a launcher (app\launcher.py): it runs the dashboard's code from app\ in the folder it sits in, so
# changes to that code need no rebuild. Rebuild only when the dashboard starts using a new library: the libraries are
# found by app\tools\launcher_imports.py. The exe also carries a backup copy of the code, used if the shared copy
# cannot be loaded.
param([string]$Dest = '', [switch]$SkipDaily)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath  # .Path carries a provider prefix on UNC
if (-not $Dest) { $Dest = $root }
$py = Join-Path $root '.venv\Scripts\python.exe'
$work = Join-Path $env:TEMP 'litigation_tracker_build'   # build scratch stays off the network drive

& $py -m pytest -q -p no:cacheprovider (Join-Path $root 'tests')
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; not building.' }

$imports = & $py (Join-Path $root 'app\tools\launcher_imports.py')
if ($LASTEXITCODE -ne 0 -or -not $imports) { throw 'Could not list the dashboard''s imports.' }
$hidden = foreach ($m in $imports) { '--hidden-import'; $m }
$backup = foreach ($m in 'main', 'data', 'resources', 'signups', 'insurers') { '--add-data'; "$(Join-Path $root "app\$m.py");app_backup" }
& $py -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name 'Litigation Tracker' `
    --icon (Join-Path $root 'app\static\litigation_tracker.ico') `
    @hidden @backup `
    --distpath $Dest --workpath $work --specpath $work `
    (Join-Path $root 'app\launcher.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
Write-Host "Built $(Join-Path $Dest 'Litigation Tracker.exe') (launcher; $($imports.Count) libraries)"

if ($SkipDaily) { return }
# The daily update: a console window, in its own folder; it finds the project as its folder's parent.
$daily = Join-Path $root 'Daily Update'
& $py -m PyInstaller --noconfirm --clean --onefile --console `
    --name 'Litigation Tracker Daily Update' `
    --icon (Join-Path $root 'app\static\litigation_tracker.ico') `
    --paths (Join-Path $root 'app') --paths (Join-Path $root 'app\tools') --hidden-import to_check --hidden-import state_cases --hidden-import newsletter --hidden-import signups --hidden-import PIL.Image `
    --distpath $daily --workpath $work --specpath $work `
    (Join-Path $root 'app\daily_update.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed (daily update).' }
Write-Host "Built $(Join-Path $daily 'Litigation Tracker Daily Update.exe')"
