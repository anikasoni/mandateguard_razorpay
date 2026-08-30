$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendCommand = "conda run -n mandate python -m uvicorn mandateguard.main:app --app-dir backend/src --host 127.0.0.1 --port 8000 --reload"
$developmentPorts = @(8000, 5173)
$backend = $null
$frontend = $null
$backendProcesses = @{}
$frontendProcesses = @{}

function Get-ProcessForIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,
        [Parameter(Mandatory = $true)]
        [datetime]$StartTimeUtc
    )

    try {
        $candidate = [System.Diagnostics.Process]::GetProcessById($ProcessId)
        $candidate.Refresh()
        if ($candidate.HasExited -or $candidate.StartTime.ToUniversalTime() -ne $StartTimeUtc) {
            return $null
        }
        return $candidate
    }
    catch [System.ArgumentException] {
        return $null
    }
    catch [System.InvalidOperationException] {
        return $null
    }
}

function Add-TrackedProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [hashtable]$TrackedProcesses
    )

    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $TrackedProcesses[$Process.Id] = $Process.StartTime.ToUniversalTime()
        }
    }
    catch [System.InvalidOperationException] {
        return
    }
}

function Update-TrackedProcessTree {
    param(
        [AllowNull()]
        [System.Diagnostics.Process]$RootProcess,
        [Parameter(Mandatory = $true)]
        [hashtable]$TrackedProcesses
    )

    if ($null -eq $RootProcess) {
        return
    }

    Add-TrackedProcessIdentity -Process $RootProcess -TrackedProcesses $TrackedProcesses
    $isWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    if (-not $isWindows -or -not $TrackedProcesses.ContainsKey($RootProcess.Id)) {
        return
    }

    try {
        $processSnapshot = @(Get-CimInstance `
            -ClassName Win32_Process `
            -Property ProcessId, ParentProcessId, CreationDate `
            -ErrorAction Stop)
        $pending = [System.Collections.Generic.Queue[int]]::new()
        $seen = [System.Collections.Generic.HashSet[int]]::new()
        $pending.Enqueue($RootProcess.Id)
        $seen.Add($RootProcess.Id) | Out-Null

        while ($pending.Count -gt 0) {
            $parentId = $pending.Dequeue()
            foreach ($processInfo in $processSnapshot) {
                if ([int]$processInfo.ParentProcessId -ne $parentId) {
                    continue
                }

                $childId = [int]$processInfo.ProcessId
                if (-not $seen.Add($childId)) {
                    continue
                }

                try {
                    $child = [System.Diagnostics.Process]::GetProcessById($childId)
                    $childStartTime = $child.StartTime.ToUniversalTime()
                    $snapshotStartTime = ([datetime]$processInfo.CreationDate).ToUniversalTime()
                    if (-not $child.HasExited -and $childStartTime -eq $snapshotStartTime) {
                        $TrackedProcesses[$childId] = $childStartTime
                        $pending.Enqueue($childId)
                    }
                }
                catch [System.ArgumentException] {
                    continue
                }
                catch [System.InvalidOperationException] {
                    continue
                }
            }
        }
    }
    catch {
        throw "Could not refresh descendant process identities for PID $($RootProcess.Id): $_"
    }
}

function Stop-VerifiedProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,
        [Parameter(Mandatory = $true)]
        [datetime]$StartTimeUtc
    )

    $process = Get-ProcessForIdentity -ProcessId $ProcessId -StartTimeUtc $StartTimeUtc
    if ($null -eq $process) {
        return
    }

    $killTreeMethod = $process.GetType().GetMethod("Kill", [type[]]@([bool]))
    if ($null -ne $killTreeMethod) {
        try {
            $killTreeMethod.Invoke($process, [object[]]@($true)) | Out-Null
            if ($process.WaitForExit(5000)) {
                return
            }
            Write-Warning ".NET process-tree termination timed out for PID ${ProcessId}."
        }
        catch {
            Write-Warning ".NET process-tree termination failed for PID ${ProcessId}: $_"
        }
    }

    $process = Get-ProcessForIdentity -ProcessId $ProcessId -StartTimeUtc $StartTimeUtc
    if ($null -eq $process) {
        return
    }

    $isWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    if ($isWindows) {
        $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
        & $taskkill /PID $ProcessId /T /F 2>$null | Out-Null
        $taskkillExitCode = $LASTEXITCODE
        if ($process.WaitForExit(5000)) {
            return
        }
        throw "Windows process-tree termination failed for PID ${ProcessId} (taskkill exit code ${taskkillExitCode})."
    }

    $process.Kill()
    if (-not $process.WaitForExit(5000)) {
        throw "Process termination timed out for PID ${ProcessId}."
    }
}

function Stop-ProcessTree {
    param(
        [AllowNull()]
        [System.Diagnostics.Process]$RootProcess,
        [Parameter(Mandatory = $true)]
        [hashtable]$TrackedProcesses
    )

    if ($null -eq $RootProcess) {
        return
    }

    $trackingFailure = $null
    try {
        Update-TrackedProcessTree `
            -RootProcess $RootProcess `
            -TrackedProcesses $TrackedProcesses
    }
    catch {
        $trackingFailure = $_
    }

    if ($TrackedProcesses.ContainsKey($RootProcess.Id)) {
        Stop-VerifiedProcessTree `
            -ProcessId $RootProcess.Id `
            -StartTimeUtc $TrackedProcesses[$RootProcess.Id]
    }

    foreach ($entry in @($TrackedProcesses.GetEnumerator())) {
        if ($entry.Key -eq $RootProcess.Id) {
            continue
        }
        Stop-VerifiedProcessTree -ProcessId $entry.Key -StartTimeUtc $entry.Value
    }

    $survivors = @(
        foreach ($entry in $TrackedProcesses.GetEnumerator()) {
            $survivor = Get-ProcessForIdentity `
                -ProcessId $entry.Key `
                -StartTimeUtc $entry.Value
            if ($null -ne $survivor) {
                "PID $($entry.Key) ($($survivor.ProcessName))"
            }
        }
    )
    if ($survivors.Count -gt 0) {
        throw "Tracked processes survived cleanup: $($survivors -join ', ')."
    }
    if ($null -ne $trackingFailure) {
        throw "Process-tree cleanup could not prove descendant coverage: $trackingFailure"
    }
}

function Assert-DevelopmentPortsClear {
    $deadline = [datetime]::UtcNow.AddSeconds(5)
    do {
        $listeners = @(
            Get-NetTCPConnection -State Listen -ErrorAction Stop |
                Where-Object { $_.LocalPort -in $developmentPorts }
        )
        if ($listeners.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([datetime]::UtcNow -lt $deadline)

    $listenerDetails = $listeners |
        ForEach-Object { "port $($_.LocalPort) (PID $($_.OwningProcess))" }
    throw "Development ports remained in use after cleanup: $($listenerDetails -join ', ')."
}

function Update-AllTrackedProcesses {
    Update-TrackedProcessTree `
        -RootProcess $backend `
        -TrackedProcesses $backendProcesses
    Update-TrackedProcessTree `
        -RootProcess $frontend `
        -TrackedProcesses $frontendProcesses
}

function Stop-AllDevelopmentProcesses {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($service in @(
            @{
                Name = "frontend"
                Process = $frontend
                TrackedProcesses = $frontendProcesses
            },
            @{
                Name = "backend"
                Process = $backend
                TrackedProcesses = $backendProcesses
            }
        )) {
        try {
            Stop-ProcessTree `
                -RootProcess $service.Process `
                -TrackedProcesses $service.TrackedProcesses
        }
        catch {
            $cleanupErrors.Add("$($service.Name): $_")
        }
    }

    try {
        Assert-DevelopmentPortsClear
    }
    catch {
        $cleanupErrors.Add("ports: $_")
    }

    if ($cleanupErrors.Count -gt 0) {
        throw "Development process cleanup failed:`n - $($cleanupErrors -join "`n - ")"
    }
}

Push-Location $repositoryRoot
try {
    $backend = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/c", $backendCommand `
        -WorkingDirectory $repositoryRoot `
        -WindowStyle Hidden `
        -PassThru
    $frontend = Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList "--prefix", "frontend", "run", "dev" `
        -WorkingDirectory $repositoryRoot `
        -WindowStyle Hidden `
        -PassThru

    Update-AllTrackedProcesses

    Write-Host "MandateGuard API: http://127.0.0.1:8000"
    Write-Host "MandateGuard UI:  http://127.0.0.1:5173"
    Write-Host "Press Ctrl+C to stop both processes."

    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
        $backend.Refresh()
        $frontend.Refresh()
        Update-AllTrackedProcesses
    }

    if ($backend.HasExited -and $backend.ExitCode -ne 0) {
        throw "Backend process exited with code $($backend.ExitCode)."
    }
    if ($frontend.HasExited -and $frontend.ExitCode -ne 0) {
        throw "Frontend process exited with code $($frontend.ExitCode)."
    }
}
finally {
    try {
        Stop-AllDevelopmentProcesses
    }
    finally {
        Pop-Location
    }
}
