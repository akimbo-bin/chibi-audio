[CmdletBinding()]
param(
    [switch]$AllowWrites,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$ArtifactRoot = (Join-Path $env:USERPROFILE '.chibi-audio'),
    [ValidateRange(1, 65535)]
    [int]$LivePort = 18765
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = [IO.Path]::GetFullPath($RepoRoot)
$artifacts = [IO.Path]::GetFullPath($ArtifactRoot)
$python = Join-Path $repo '.venv-audio-mcp\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Chibi Audio MCP virtualenv is missing: $python. Run deploy/windows/bootstrap-chibi-audio-mcp.ps1 first."
}

New-Item -ItemType Directory -Force -Path $artifacts | Out-Null

# Fail closed even if the parent process inherited a permissive environment.
$env:CHIBI_AUDIO_MCP_ALLOW_WRITES = if ($AllowWrites) { '1' } else { '0' }
$env:CHIBI_AUDIO_LIVE_PORT = [string]$LivePort
$env:CHIBI_AUDIO_ARTIFACT_ROOT = $artifacts

# The Secure MCP Tunnel launches this process over stdio. Do not expose the
# Ableton Remote Script port or a public MCP HTTP listener.
& $python -m chibi_audio.mcp_server_sections --transport stdio
exit $LASTEXITCODE
