[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = [IO.Path]::GetFullPath($RepoRoot)
$venv = Join-Path $repo '.venv-audio-mcp'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath (Join-Path $repo 'pyproject.toml') -PathType Leaf)) {
    throw "RepoRoot is not a Chibi Audio checkout: $repo"
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Chibi Audio MCP virtualenv.' }
}

# Install the reviewed checkout into its dedicated environment. This script does
# not launch Ableton, contact the Live bridge, configure a tunnel, or enable writes.
& $venvPython -m pip install -e "$repo[analysis,mcp]"
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Chibi Audio MCP dependencies.' }

Write-Output "Chibi Audio MCP environment ready: $venvPython"
Write-Output 'Writes remain disabled unless run-chibi-audio-mcp.ps1 is explicitly called with -AllowWrites.'
