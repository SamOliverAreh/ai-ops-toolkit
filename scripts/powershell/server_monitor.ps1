# =============================================================================
# server_monitor.ps1 — Windows Server Health Monitoring
#
# Checks CPU, memory, disk, services and sends alerts via Slack webhook.
# Usage: .\server_monitor.ps1 [-SlackWebhook "https://..."] [-DryRun]
# Task Scheduler: Run every 15 minutes
# =============================================================================

param(
    [string]$SlackWebhook   = $env:SLACK_WEBHOOK_URL,
    [string]$LogDir         = "C:\Logs\ai-ops",
    [int]$CpuThreshold      = 90,
    [int]$MemoryThreshold   = 90,
    [int]$DiskThreshold     = 85,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Setup ─────────────────────────────────────────────────────────────────────
$Timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$LogFile   = Join-Path $LogDir "server_monitor_$(Get-Date -Format 'yyyyMMdd').log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$Issues   = [System.Collections.Generic.List[string]]::new()
$Metrics  = [System.Collections.Generic.Dictionary[string,object]]::new()
$ExitCode = 0

function Write-Log {
    param([string]$Level, [string]$Message)
    $entry = "[$Timestamp] [$Level] $Message"
    Add-Content -Path $LogFile -Value $entry
    Write-Host $entry
}

function Send-SlackAlert {
    param([string]$Text, [string]$Color = "good")
    if ([string]::IsNullOrEmpty($SlackWebhook)) { return }
    if ($DryRun) { Write-Log "INFO" "[DRY-RUN] Would send Slack: $Text"; return }

    $Payload = @{
        attachments = @(@{
            color = $Color
            text  = $Text
            footer = "AI Ops — $env:COMPUTERNAME"
            ts    = [int](Get-Date -UFormat %s)
        })
    } | ConvertTo-Json -Depth 5

    try {
        Invoke-RestMethod -Uri $SlackWebhook -Method POST -Body $Payload `
            -ContentType "application/json" | Out-Null
    } catch {
        Write-Log "WARN" "Slack notification failed: $_"
    }
}

# ── 1. CPU ────────────────────────────────────────────────────────────────────
function Test-CPU {
    $cpu = (Get-CimInstance -ClassName Win32_Processor |
            Measure-Object -Property LoadPercentage -Average).Average
    $Metrics["cpu_pct"] = $cpu
    Write-Log "INFO" "CPU usage: $cpu%"

    if ($cpu -ge $CpuThreshold) {
        Write-Log "WARN" "CPU $cpu% exceeds threshold $CpuThreshold%"
        $Issues.Add("CPU: ${cpu}% (threshold: ${CpuThreshold}%)")
        $script:ExitCode = [Math]::Max($script:ExitCode, 1)
    }
}

# ── 2. Memory ─────────────────────────────────────────────────────────────────
function Test-Memory {
    $os     = Get-CimInstance -ClassName Win32_OperatingSystem
    $total  = $os.TotalVisibleMemorySize
    $free   = $os.FreePhysicalMemory
    $usedPct = [math]::Round((($total - $free) / $total) * 100, 1)
    $totalGB = [math]::Round($total / 1MB, 1)
    $freeGB  = [math]::Round($free  / 1MB, 1)

    $Metrics["memory_used_pct"] = $usedPct
    $Metrics["memory_free_gb"]  = $freeGB
    Write-Log "INFO" "Memory: $usedPct% used | ${freeGB}GB free of ${totalGB}GB"

    if ($usedPct -ge $MemoryThreshold) {
        Write-Log "WARN" "Memory $usedPct% exceeds threshold $MemoryThreshold%"
        $Issues.Add("Memory: ${usedPct}% used")
        $script:ExitCode = [Math]::Max($script:ExitCode, 1)
    }
}

# ── 3. Disk ───────────────────────────────────────────────────────────────────
function Test-Disk {
    Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -gt 0 } | ForEach-Object {
        $drive   = $_.Name
        $totalGB = [math]::Round(($_.Used + $_.Free) / 1GB, 1)
        $usedPct = [math]::Round($_.Used / ($_.Used + $_.Free) * 100, 1)

        $Metrics["disk_${drive}_pct"] = $usedPct
        Write-Log "INFO" "Disk ${drive}: $usedPct% used ($totalGB GB total)"

        if ($usedPct -ge $DiskThreshold) {
            Write-Log "WARN" "Disk ${drive} at $usedPct% exceeds threshold $DiskThreshold%"
            $Issues.Add("Disk ${drive}: ${usedPct}%")
            $script:ExitCode = [Math]::Max($script:ExitCode, 1)
        }
    }
}

# ── 4. Critical Services ──────────────────────────────────────────────────────
function Test-Services {
    $CriticalServices = @("wuauserv", "Dnscache", "EventLog", "W32Time")

    foreach ($svc in $CriticalServices) {
        try {
            $service = Get-Service -Name $svc -ErrorAction SilentlyContinue
            if ($null -eq $service) {
                Write-Log "INFO" "Service '$svc' not found (may not apply to this server)"
                continue
            }
            $status = $service.Status
            Write-Log "INFO" "Service '$svc': $status"
            if ($status -ne "Running") {
                Write-Log "WARN" "Service '$svc' is $status"
                $Issues.Add("Service '${svc}' is ${status}")
                $script:ExitCode = [Math]::Max($script:ExitCode, 1)
            }
        } catch {
            Write-Log "WARN" "Could not check service '$svc': $_"
        }
    }
}

# ── 5. Event Log Check ────────────────────────────────────────────────────────
function Test-EventLogs {
    $since  = (Get-Date).AddHours(-1)
    $errors = Get-EventLog -LogName System -EntryType Error -After $since `
              -ErrorAction SilentlyContinue | Select-Object -First 5

    $Metrics["system_errors_last_hour"] = ($errors | Measure-Object).Count

    if ($errors.Count -gt 0) {
        Write-Log "WARN" "$($errors.Count) System error(s) in last hour"
        $Issues.Add("$($errors.Count) System event log error(s) in last hour")
        $script:ExitCode = [Math]::Max($script:ExitCode, 1)
    } else {
        Write-Log "INFO" "No System errors in last hour"
    }
}

# ── 6. Scheduled Task Check ───────────────────────────────────────────────────
function Test-ScheduledTasks {
    $failed = Get-ScheduledTask | Where-Object {
        ($_ | Get-ScheduledTaskInfo).LastTaskResult -ne 0 -and
        ($_ | Get-ScheduledTaskInfo).LastTaskResult -ne 267011  # never ran
    } | Select-Object -First 5

    if ($failed.Count -gt 0) {
        Write-Log "WARN" "$($failed.Count) scheduled task(s) last failed"
        $Issues.Add("$($failed.Count) scheduled task failure(s)")
    } else {
        Write-Log "INFO" "All recently-run scheduled tasks OK"
    }
}

# ── Reporting ─────────────────────────────────────────────────────────────────
function Send-Report {
    if ($Issues.Count -eq 0) {
        Write-Log "INFO" "✅ All checks passed — server healthy"
        Send-SlackAlert -Text "✅ *$env:COMPUTERNAME* — All checks passed at $Timestamp" -Color "good"
    } else {
        $issueText = ($Issues | ForEach-Object { "• $_" }) -join "`n"
        $msg = "⚠️ *$env:COMPUTERNAME* — $($Issues.Count) issue(s) detected at ${Timestamp}:`n${issueText}"
        Write-Log "WARN" "Report: $($Issues.Count) issue(s) — $($Issues -join '; ')"
        Send-SlackAlert -Text $msg -Color "warning"
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────
Write-Log "INFO" "=== Server Monitor | $env:COMPUTERNAME | DryRun=$DryRun ==="

try {
    Test-CPU
    Test-Memory
    Test-Disk
    Test-Services
    Test-EventLogs
    Test-ScheduledTasks
    Send-Report
} catch {
    Write-Log "ERROR" "Monitor failed: $_"
    Send-SlackAlert -Text "🚨 *$env:COMPUTERNAME* Monitor script FAILED: $_" -Color "danger"
    exit 2
}

Write-Log "INFO" "=== Monitor complete | Exit: $ExitCode ==="
exit $ExitCode
