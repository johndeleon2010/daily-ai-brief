$ErrorActionPreference = "Stop"
$taskName = "Daily AI Brief Browser"
$installDir = Join-Path $env:LOCALAPPDATA "DailyAIBrief"
$sourceScript = Join-Path $PSScriptRoot "Open-DailyAIBrief.ps1"
$targetScript = Join-Path $installDir "Open-DailyAIBrief.ps1"

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item -Path $sourceScript -Destination $targetScript -Force
Remove-Item -Path (Join-Path $env:TEMP "Open-DailyAIBrief-Debug.ps1") -Force -ErrorAction SilentlyContinue

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 1
}

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
if ($task.Principal.LogonType -notmatch "^Interactive") {
    throw "The scheduled task will not run in the signed in user session."
}
$registeredTime = ([datetime]$task.Triggers[0].StartBoundary).ToString("HH:mm")
if ($registeredTime -ne "07:30") {
    throw "The scheduled task start time is not 7:30 AM."
}

function Invoke-DeliveryCheck {
    param([string]$Arguments)
    $argumentText = "-NoProfile -ExecutionPolicy Bypass -File `"$targetScript`" $Arguments"
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $argumentText -Wait -PassThru -NoNewWindow
    return $process.ExitCode
}

$browserCheck = Invoke-DeliveryCheck "-CheckBrowser"
if ($browserCheck -ne 0) {
    throw "Microsoft Edge detection failed."
}

$dateCheck = Invoke-DeliveryCheck "-NoOpen -MaxMinutes 0 -PollSeconds 0"
if ($dateCheck -ne 0) {
    throw "Today's brief is not available for the browser launch test."
}

$deliveryLog = Join-Path $installDir "delivery.log"
Remove-Item -Path $deliveryLog -Force -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName

$browserConfirmed = $false
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Seconds 1
    if (Test-Path $deliveryLog) {
        $browserConfirmed = Select-String -Path $deliveryLog -SimpleMatch "Microsoft Edge started." -Quiet
        if ($browserConfirmed) {
            break
        }
    }
}
if (-not $browserConfirmed) {
    throw "The scheduled task started, but Microsoft Edge launch was not confirmed."
}

Write-Host "Browser delivery setup: PASS"
Write-Host "Browser launch test: PASS"
Write-Host "Task: $taskName"
Write-Host "User: $($task.Principal.UserId)"
Write-Host "Schedule: Monday through Friday at 7:30 AM"
Write-Host "The task waits for today's brief before opening Microsoft Edge."
