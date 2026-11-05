$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $installation) { throw 'Existing MSVC toolchain unavailable' }
$developer = Join-Path $installation 'Common7/Tools/VsDevCmd.bat'
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'windows/prepare_directory.cpp')).Path
$output = Join-Path $env:RUNNER_TEMP 'directory-helper'
if (Test-Path -LiteralPath $output) { throw 'Fresh helper output required' }
New-Item -ItemType Directory -Path $output | Out-Null
$executable = Join-Path $output 'NEXUS-Directory-Helper.exe'
$object = Join-Path $output 'prepare-directory.obj'
$command = '""{0}" -arch=x64 -host_arch=x64 && cl /nologo /std:c++17 /MT /O2 /W4 /WX /EHsc /DUNICODE /D_UNICODE "{1}" /Fo"{2}" /link /SUBSYSTEM:WINDOWS /OUT:"{3}" advapi32.lib shell32.lib ntdll.lib"' -f $developer,$source,$object,$executable
& $env:ComSpec /d /s /c $command
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path -LiteralPath $executable)) { throw 'Native helper not produced' }
"NEXUS_PERMISSION_HELPER=$executable" >> $env:GITHUB_ENV
Write-Output 'Built static-CRT native folder helper; no download or launcher execution authority'
