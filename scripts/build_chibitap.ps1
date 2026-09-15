param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $repo "native\ChibiTap"
$build = Join-Path $repo ".local\build\chibitap"
$localJuce = Join-Path $repo ".local\deps\JUCE"

$cmakeCommand = Get-Command cmake.exe -ErrorAction SilentlyContinue
if ($cmakeCommand) {
    $cmake = $cmakeCommand.Source
} else {
    $cmake = "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
    if (-not (Test-Path -LiteralPath $cmake)) {
        throw "CMake was not found on PATH or at the Visual Studio 2022 bundled location."
    }
}

New-Item -ItemType Directory -Force -Path $build | Out-Null
$configure = @("-S", $source, "-B", $build, "-G", "Visual Studio 17 2022", "-A", "x64")
if (Test-Path -LiteralPath (Join-Path $localJuce "CMakeLists.txt")) {
    $configure += "-DCHIBITAP_JUCE_DIR:PATH=$localJuce"
}

& $cmake @configure
if ($LASTEXITCODE -ne 0) { throw "ChibiTap configure failed with exit code $LASTEXITCODE" }

$targets = @("ChibiTap_VST3", "ChibiTapCoreTests", "ChibiTapVst3SmokeTest")
& $cmake --build $build --config $Configuration --target @targets -- /m:1
if ($LASTEXITCODE -ne 0) { throw "ChibiTap build failed with exit code $LASTEXITCODE" }

$artefacts = Join-Path $build "ChibiTap_artefacts\$Configuration"
$bundle = Join-Path $artefacts "VST3\ChibiTap.vst3"
if (-not (Test-Path -LiteralPath $bundle)) { throw "Built ChibiTap bundle is missing: $bundle" }

if (-not $SkipTests) {
    $core = Join-Path $build "ChibiTapCoreTests_artefacts\$Configuration\ChibiTapCoreTests.exe"
    $smoke = Join-Path $build "ChibiTapVst3SmokeTest_artefacts\$Configuration\ChibiTapVst3SmokeTest.exe"
    & $core
    if ($LASTEXITCODE -ne 0) { throw "ChibiTapCoreTests failed with exit code $LASTEXITCODE" }
    & $smoke $bundle
    if ($LASTEXITCODE -ne 0) { throw "ChibiTapVst3SmokeTest failed with exit code $LASTEXITCODE" }
}

Write-Output "ChibiTap bundle: $bundle"
