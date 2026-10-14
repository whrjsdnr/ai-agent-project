param([switch]$Installer)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Run with native Windows PowerShell and Windows uv.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($repo.StartsWith('\\')) { throw 'Build from a checkout on a local Windows drive, not a WSL UNC path.' }
$oldEnvironment = $env:UV_PROJECT_ENVIRONMENT
Push-Location $repo
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    # Never share the WSL/Linux .venv with Windows.
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $repo 'build\windows-venv'
    & uv sync --locked --group build --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
    & uv run --no-sync python -c "import sys; assert sys.platform == 'win32', 'Windows Python required'"
    if ($LASTEXITCODE -ne 0) { throw 'Windows Python verification failed.' }
    & uv run --no-sync python -m pytest tests/packaging -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Packaging tests failed.' }
    # PyInstaller only replaces its known dist/AI-Agent output; no arbitrary deletion.
    & uv run --no-sync python -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/pyinstaller/ai-agent.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $exe = Join-Path $repo 'dist\AI-Agent\AI-Agent.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Expected AI-Agent.exe missing.' }
    & uv run --no-sync python packaging/verify_bundle.py dist/AI-Agent --smoke
    if ($LASTEXITCODE -ne 0) { throw 'Windows bundle acceptance failed.' }
    if ($Installer) {
        $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        $compiler = if ($iscc) { $iscc.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
        if (-not (Test-Path -LiteralPath $compiler)) { throw 'Install Inno Setup 6, then rerun with -Installer.' }
        $version = & uv run --no-sync python -c "from ai_agent_project.desktop_app.resources import application_version; print(application_version())"
        if ($LASTEXITCODE -ne 0) { throw 'Version resolution failed.' }
        & $compiler "/DAppVersion=$version" "/DRepoRoot=$repo" 'packaging/windows/installer/AI-Agent.iss'
        if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
        if (-not (Test-Path 'dist\installer\AI-Agent-Setup.exe')) { throw 'Installer output missing.' }
        Write-Host 'Installer: dist\installer\AI-Agent-Setup.exe'
    }
    Write-Host 'Windows application: dist\AI-Agent\AI-Agent.exe'
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $oldEnvironment
    Pop-Location
}
