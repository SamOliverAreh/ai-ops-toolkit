# =============================================================================
# file_automation.ps1 — Automated file management and archival
# Usage: .\file_automation.ps1 -SourceDir "C:\data" -ArchiveDir "D:\archive"
# =============================================================================

param(
    [string]$SourceDir      = $env:FILE_SOURCE_DIR,
    [string]$ArchiveDir     = $env:FILE_ARCHIVE_DIR,
    [int]$ArchiveAfterDays  = 30,
    [int]$DeleteAfterDays   = 90,
    [string[]]$Extensions   = @(".csv", ".log", ".json", ".parquet"),
    [string]$SlackWebhook   = $env:SLACK_WEBHOOK_URL,
    [switch]$DryRun
)

$Timestamp   = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$Archived    = 0
$Deleted     = 0
$BytesMoved  = 0

function Write-Log {
    param([string]$Level, [string]$Message)
    Write-Host "[$Timestamp] [$Level] $Message"
}

function Invoke-SlackNotify {
    param([string]$Text)
    if (-not $SlackWebhook -or $DryRun) { return }
    $body = "{""text"":""$Text""}"
    try { Invoke-RestMethod -Uri $SlackWebhook -Method POST -Body $body -ContentType "application/json" | Out-Null }
    catch { Write-Log "WARN" "Slack failed: $_" }
}

if (-not $SourceDir -or -not (Test-Path $SourceDir)) {
    Write-Log "ERROR" "SourceDir '$SourceDir' not found. Set FILE_SOURCE_DIR env var."
    exit 1
}

if (-not (Test-Path $ArchiveDir)) {
    if (-not $DryRun) { New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null }
    Write-Log "INFO" "Created archive dir: $ArchiveDir"
}

Write-Log "INFO" "=== File Automation | Source=$SourceDir | Archive=$ArchiveDir | DryRun=$DryRun ==="

$cutoffArchive = (Get-Date).AddDays(-$ArchiveAfterDays)
$cutoffDelete  = (Get-Date).AddDays(-$DeleteAfterDays)

Get-ChildItem -Path $SourceDir -Recurse -File |
    Where-Object { $_.Extension -in $Extensions } |
    ForEach-Object {
        $file = $_
        if ($file.LastWriteTime -lt $cutoffDelete) {
            Write-Log "INFO" "DELETE: $($file.FullName)"
            if (-not $DryRun) { Remove-Item $file.FullName -Force }
            $Deleted++
        } elseif ($file.LastWriteTime -lt $cutoffArchive) {
            $dest = Join-Path $ArchiveDir $file.Name
            Write-Log "INFO" "ARCHIVE: $($file.FullName) → $dest"
            if (-not $DryRun) { Move-Item $file.FullName $dest -Force }
            $Archived++
            $BytesMoved += $file.Length
        }
    }

$MBMoved = [math]::Round($BytesMoved / 1MB, 1)
Write-Log "INFO" "Done — Archived: $Archived files (${MBMoved}MB) | Deleted: $Deleted files"
Invoke-SlackNotify "📁 File automation: $Archived archived (${MBMoved}MB), $Deleted deleted"
