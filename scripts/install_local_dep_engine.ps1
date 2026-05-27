$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } else { "python" }

Write-Host "Installing local-repo-dependency-index from $Root"
Invoke-Expression "$Python -m pip install -e `"$Root`""

$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$SkillTargetRoot = Join-Path $CodexHome "skills"
$SkillSource = Join-Path $Root "skills\local-dependency-index"
$SkillTarget = Join-Path $SkillTargetRoot "local-dependency-index"

New-Item -ItemType Directory -Force -Path $SkillTargetRoot | Out-Null
if (Test-Path $SkillTarget) {
    Remove-Item -Recurse -Force -LiteralPath $SkillTarget
}
Copy-Item -Recurse -Force -LiteralPath $SkillSource -Destination $SkillTarget

Write-Host "Installed package and skill:"
Write-Host "  Package: local-repo-dependency-index"
Write-Host "  Skill: $SkillTarget"
Write-Host ""
Write-Host "Next:"
Write-Host "  repo-index init"
Write-Host "  repo-index index"
