[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ChibiAudio\tunnel-client')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Reviewed OpenAI release at implementation time. Update the version + digest
# together after reviewing a newer upstream release.
$version = 'v0.0.14'
$archiveName = "tunnel-client-$version-windows-amd64.zip"
$expectedSha256 = '784ab8da7b5a88f0109f1fd8aaf0a1c86067430b896dddf307ef7e3cc49fa1a5'
$url = "https://github.com/openai/tunnel-client/releases/download/$version/$archiveName"
$destination = Join-Path ([IO.Path]::GetFullPath($InstallRoot)) $version
$target = Join-Path $destination 'tunnel-client.exe'

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("chibi-audio-tunnel-" + [guid]::NewGuid().ToString('N'))
$archive = Join-Path $tempRoot $archiveName
$expanded = Join-Path $tempRoot 'expanded'

try {
    New-Item -ItemType Directory -Force -Path $tempRoot, $expanded | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
    $observedSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($observedSha256 -ne $expectedSha256) {
        throw "OpenAI tunnel-client archive SHA-256 mismatch: $observedSha256"
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $binary = Get-ChildItem -LiteralPath $expanded -Recurse -File -Filter 'tunnel-client.exe' | Select-Object -First 1
    if ($null -eq $binary) {
        throw 'Verified tunnel-client archive did not contain tunnel-client.exe.'
    }

    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -LiteralPath $binary.FullName -Destination $target -Force

    Write-Output "Verified OpenAI tunnel-client installed: $target"
    Write-Output 'No tunnel profile, workspace association, runtime API key, service, or auto-start was configured.'
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
