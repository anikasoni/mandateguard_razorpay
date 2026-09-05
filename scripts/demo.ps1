$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    conda run -n mandate python -m alembic -c backend/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }

    conda run -n mandate python -m mandateguard.demo.seed
    if ($LASTEXITCODE -ne 0) { throw "Demo seed failed." }

    & (Join-Path $PSScriptRoot "dev.ps1")
}
finally {
    Pop-Location
}
