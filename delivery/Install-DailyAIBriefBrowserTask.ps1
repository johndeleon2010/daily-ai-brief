$ErrorActionPreference = "Stop"
$taskName = "Daily AI Brief Browser"
$installDir = Join-Path $env:LOCALAPPDATA "DailyAIBrief"
$sourceScript = Join-Path $PSScriptRoot "Open-DailyAIBrief.ps1"
$targetScript = Join-Path $installDir "Open-DailyAIBrief.ps1"

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item -Path $sourceScript -Destination $targetScript -Force

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$targetScript`""
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "07:30"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Open the Daily AI Brief after today's brief is published." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
if ($task.State -eq $null) {
    throw "The scheduled task was not created."
}
if (-not $task.Settings.StartWhenAvailable) {
    throw "The scheduled task will not run after a missed start."
}
if ($task.Actions[0].Arguments -notlike "*Open-DailyAIBrief.ps1*") {
    throw "The scheduled task does not run the browser delivery script."
}
if ($task.Principal.UserId -ne $userId) {
    throw "The scheduled task is assigned to the wrong user."
}
$registeredTime = ([datetime]$task.Triggers[0].StartBoundary).ToString("HH:mm")
if ($registeredTime -ne "07:30") {
    throw "The scheduled task start time is not 7:30 AM."
}

Write-Host "Browser delivery setup: PASS"
Write-Host "Task: $taskName"
Write-Host "Schedule: Monday through Friday at 7:30 AM"
Write-Host "The task waits for today's brief before opening Microsoft Edge."
