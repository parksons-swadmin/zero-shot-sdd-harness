#Requires -Version 5.1
<#
.SYNOPSIS
  Register (or remove) the "AR-Daily-Report" Windows Scheduled Task.

.DESCRIPTION
  Registers a daily task that runs scripts\run-daily-report.cmd, which renders the
  AR aging dashboard to a PDF and emails it (or, when SMTP is not configured, saves it
  under frontend\scripts\output\ in dry-run mode).

  The task runs only while the current user is logged on (no stored password), so the
  laptop must be ON and the user logged in at the scheduled time. -StartWhenAvailable
  means a run missed while the laptop was asleep/off fires at the next opportunity.

.PARAMETER Time
  Daily run time in 24-hour "HH:mm" form. Default 12:00 (noon).

.PARAMETER Unregister
  Remove the task instead of creating it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1
  # Registers the task at the default 12:00 PM.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1 -Time 09:30

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1 -Unregister
  # Removes the task. (You can also remove it from Task Scheduler > Task Scheduler Library.)
#>
param(
  [string]$Time = "12:00",
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$TaskName  = "AR-Daily-Report"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$CmdPath   = Join-Path $ScriptDir "run-daily-report.cmd"

# ---- Unregister path -------------------------------------------------------
if ($Unregister) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
  } else {
    Write-Host "No scheduled task named '$TaskName' found — nothing to remove."
  }
  return
}

# ---- Register path ---------------------------------------------------------
if (-not (Test-Path $CmdPath)) {
  throw "Wrapper not found: $CmdPath"
}

# Only the time-of-day is used by a -Daily trigger; the date part is ignored.
$parsedTime = [DateTime]::ParseExact($Time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$CmdPath`"" -WorkingDirectory $RepoRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At $parsedTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                         -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
                                         -MultipleInstances IgnoreNew

# Replace any prior definition so re-running this script is idempotent.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
                       -Action $action `
                       -Trigger $trigger `
                       -Settings $settings `
                       -Description "Daily AR aging dashboard PDF report (renders locally, emails the PDF)." | Out-Null

Write-Host "Registered scheduled task '$TaskName' — runs daily at $Time (current user, only while logged on)."
Write-Host ""
Write-Host "Test the job now (dry-run, no email — saves a PDF under frontend\scripts\output\):"
Write-Host "    node frontend\scripts\daily-report.mjs --dry-run"
Write-Host ""
Write-Host "Run the scheduled task on demand:"
Write-Host "    Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Inspect the log:"
Write-Host "    Get-Content scripts\daily-report.log -Tail 40"
Write-Host ""
Write-Host "Remove the task:"
Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\register-daily-report-task.ps1 -Unregister"
Write-Host ""
Write-Host "NOTE: the task runs only while you are logged on — the laptop must be ON at $Time."
