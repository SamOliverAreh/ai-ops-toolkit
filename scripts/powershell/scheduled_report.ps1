# =============================================================================
# scheduled_report.ps1 — Automated Windows ops reporting
# Collects system stats and emails/Slacks a formatted HTML report.
# Usage: .\scheduled_report.ps1 [-EmailTo "ops@company.com"]
# =============================================================================

param(
    [string]$EmailTo       = $env:ALERT_EMAIL_TO,
    [string]$EmailFrom     = $env:ALERT_EMAIL_FROM,
    [string]$SmtpServer    = $env:SMTP_SERVER,
    [int]$SmtpPort         = 587,
    [string]$SmtpUser      = $env:SMTP_USER,
    [string]$SmtpPassword  = $env:SMTP_PASSWORD,
    [string]$SlackWebhook  = $env:SLACK_WEBHOOK_URL,
    [string]$OutputDir     = "C:\Reports\ai-ops",
    [switch]$DryRun
)

$Timestamp  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$ReportDate = Get-Date -Format "MMMM d, yyyy"
$SafeDate   = Get-Date -Format "yyyyMMdd_HHmmss"

if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }

# ── Collect stats ─────────────────────────────────────────────────────────────
$os      = Get-CimInstance Win32_OperatingSystem
$cpu     = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
$memPct  = [math]::Round((($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize) * 100, 1)
$uptime  = (Get-Date) - $os.LastBootUpTime
$disks   = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -gt 0 } | ForEach-Object {
    [PSCustomObject]@{
        Drive   = $_.Name
        UsedPct = [math]::Round($_.Used / ($_.Used + $_.Free) * 100, 1)
        FreeGB  = [math]::Round($_.Free / 1GB, 1)
    }
}
$topProcs = Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 |
    Select-Object Name, @{N="CPU_s";E={[math]::Round($_.CPU,1)}}, @{N="MemMB";E={[math]::Round($_.WorkingSet/1MB,1)}}

# ── Build HTML ────────────────────────────────────────────────────────────────
$diskRows = ($disks | ForEach-Object {
    $color = if ($_.UsedPct -ge 85) {"#ef4444"} elseif ($_.UsedPct -ge 70) {"#f59e0b"} else {"#22c55e"}
    "<tr><td>$($_.Drive):</td><td style='color:$color'>$($_.UsedPct)%</td><td>$($_.FreeGB) GB free</td></tr>"
}) -join ""

$procRows = ($topProcs | ForEach-Object {
    "<tr><td>$($_.Name)</td><td>$($_.CPU_s)s</td><td>$($_.MemMB) MB</td></tr>"
}) -join ""

$html = @"
<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>
  body{font-family:Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
  h1{color:#fff;font-size:22px} h2{color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.1em}
  .box{background:#1e293b;border-radius:8px;padding:16px;margin-bottom:12px}
  .metric{display:inline-block;margin:0 20px 0 0}
  .val{font-size:28px;font-weight:700;color:#38bdf8}
  .lbl{font-size:11px;color:#64748b;text-transform:uppercase}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{padding:8px 10px;border-bottom:1px solid #334155;text-align:left}
  th{color:#94a3b8;font-size:11px;text-transform:uppercase}
  footer{color:#475569;font-size:11px;margin-top:20px;text-align:center}
</style></head><body>
<h1>🖥 Windows Server Report — $ReportDate</h1>
<p style='color:#64748b'>$env:COMPUTERNAME &nbsp;·&nbsp; $Timestamp</p>

<div class='box'>
  <h2>System Overview</h2>
  <div class='metric'><div class='val'>$cpu%</div><div class='lbl'>CPU</div></div>
  <div class='metric'><div class='val'>$memPct%</div><div class='lbl'>Memory</div></div>
  <div class='metric'><div class='val'>$([math]::Floor($uptime.TotalHours))h</div><div class='lbl'>Uptime</div></div>
</div>

<div class='box'>
  <h2>Disk Usage</h2>
  <table><tr><th>Drive</th><th>Used</th><th>Free</th></tr>$diskRows</table>
</div>

<div class='box'>
  <h2>Top Processes (CPU)</h2>
  <table><tr><th>Process</th><th>CPU Time</th><th>Memory</th></tr>$procRows</table>
</div>

<footer>AI Ops Automation Toolkit · Automated report</footer>
</body></html>
"@

$outFile = Join-Path $OutputDir "report_$SafeDate.html"
$html | Out-File -FilePath $outFile -Encoding UTF8
Write-Host "Report saved: $outFile"

# ── Email ─────────────────────────────────────────────────────────────────────
if (-not $DryRun -and $EmailTo -and $SmtpServer) {
    $cred = New-Object PSCredential($SmtpUser, (ConvertTo-SecureString $SmtpPassword -AsPlainText -Force))
    Send-MailMessage `
        -From $EmailFrom -To $EmailTo `
        -Subject "Windows Ops Report — $ReportDate" `
        -Body $html -BodyAsHtml `
        -SmtpServer $SmtpServer -Port $SmtpPort -UseSsl -Credential $cred
    Write-Host "Report emailed to $EmailTo"
} elseif ($DryRun) {
    Write-Host "[DRY-RUN] Would email to: $EmailTo"
}

# ── Slack summary ─────────────────────────────────────────────────────────────
if ($SlackWebhook) {
    $color = if ($cpu -ge 90 -or $memPct -ge 90) {"danger"} elseif ($cpu -ge 75 -or $memPct -ge 75) {"warning"} else {"good"}
    $body  = "{""attachments"":[{""color"":""$color"",""title"":""🖥 $env:COMPUTERNAME Report — $ReportDate"",""text"":""CPU: $cpu% | Memory: $memPct% | Uptime: $([math]::Floor($uptime.TotalHours))h""}]}"
    if (-not $DryRun) {
        Invoke-RestMethod -Uri $SlackWebhook -Method POST -Body $body -ContentType "application/json" | Out-Null
    }
}

Write-Host "Done."
