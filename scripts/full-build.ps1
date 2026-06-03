#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot

try
{
    # Merge latest changes from master so our build is always up to date
    Write-Host "Fetching latest changes from origin/master..."
    & git fetch origin
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed (exit $LASTEXITCODE)" }
    & git merge origin/master
    if ($LASTEXITCODE -ne 0) { throw "git merge failed — resolve conflicts then re-run (exit $LASTEXITCODE)" }

    # Fetch the current official plugin hub version so our build is compatible
    Write-Host "Fetching current plugin hub version..."
    $version = (Invoke-WebRequest "https://static.runelite.net/bootstrap.json" -UseBasicParsing |
        ConvertFrom-Json).version
    Write-Host "Plugin hub version: $version"

    # Stamp the version into gradle.properties (the settings script reads the file directly)
    $propsFile = "$repoRoot\gradle.properties"
    (Get-Content $propsFile) -replace "^project\.build\.version=.*", "project.build.version=$version" |
        Set-Content $propsFile -Encoding utf8

    # Build
    Write-Host "Building shaded jar..."
    & ".\gradlew.bat" ":client:shadowJar"
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed (exit $LASTEXITCODE)" }

    # Compile the thin launcher-entry-point wrapper against the shaded jar.
    # The Jagex Launcher's config.json specifies mainClass=net.runelite.launcher.Launcher,
    # which is not present in the RuneLite client jar, so we inject it.
    $shadedJar  = "$repoRoot\runelite-client\build\libs\client-$version-shaded.jar"
    $classesDir = "$env:TEMP\runelite-launcher-wrapper-classes"
    New-Item -ItemType Directory -Force $classesDir | Out-Null

    Write-Host "Compiling launcher wrapper..."
    & javac -cp $shadedJar -d $classesDir "$PSScriptRoot\Launcher.java"
    if ($LASTEXITCODE -ne 0) { throw "javac failed (exit $LASTEXITCODE)" }

    # Copy the shaded jar and inject the wrapper class
    $deployJar = "$env:TEMP\RuneLite-deploy.jar"
    Copy-Item $shadedJar $deployJar -Force
    Push-Location $classesDir
    & jar uf $deployJar net/runelite/launcher/Launcher.class
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "jar injection failed (exit $LASTEXITCODE)" }

    # Deploy over the Jagex Launcher's RuneLite.jar
    $dest = "$env:LOCALAPPDATA\RuneLite\RuneLite.jar"
    Copy-Item $deployJar $dest -Force

    $sizeMB = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Done. Deployed RuneLite $version ($sizeMB MB) to $dest"
}
finally
{
    Pop-Location
}
