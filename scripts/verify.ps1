$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "`n==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repositoryRoot
try {
    Invoke-Checked "Install backend and development dependencies" {
        conda run -n mandate python -m pip install -e ".[dev]"
    }
    Invoke-Checked "Lint backend" {
        conda run -n mandate python -m ruff check backend
    }
    Invoke-Checked "Check backend formatting" {
        conda run -n mandate python -m ruff format --check backend
    }
    Invoke-Checked "Type-check backend" {
        conda run -n mandate python -m mypy backend/src
    }
    Invoke-Checked "Test backend" {
        conda run -n mandate python -m pytest backend/tests --cov=mandateguard --cov-report=term-missing
    }
    Invoke-Checked "Check Alembic heads" {
        conda run -n mandate python -m alembic -c backend/alembic.ini heads
    }
    Invoke-Checked "Apply Alembic migrations" {
        conda run -n mandate python -m alembic -c backend/alembic.ini upgrade head
    }
    Invoke-Checked "Install locked frontend dependencies" {
        npm.cmd --prefix frontend ci
    }
    Invoke-Checked "Lint frontend" {
        npm.cmd --prefix frontend run lint
    }
    Invoke-Checked "Type-check frontend" {
        npm.cmd --prefix frontend run typecheck
    }
    Invoke-Checked "Test frontend" {
        npm.cmd --prefix frontend run test -- --run
    }
    Invoke-Checked "Build frontend" {
        npm.cmd --prefix frontend run build
    }
}
finally {
    Pop-Location
}
