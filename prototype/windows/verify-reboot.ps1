param([Parameter(Mandatory)][string]$ProbeConfig)

$ErrorActionPreference = 'Stop'
$test = Get-Content -LiteralPath $ProbeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = Split-Path -Parent $ProbeConfig
$gh = $test.githubCli

function Read-GitHub($Endpoint) {
    $json = & $gh api $Endpoint
    if ($LASTEXITCODE -ne 0) { throw "GitHub request failed: $Endpoint" }
    $json | ConvertFrom-Json
}

try {
    $boot = [DateTimeOffset](Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $oldBoot = [DateTimeOffset]::Parse($test.previousBoot)
    $armed = [DateTimeOffset]::Parse($test.armedAt)
    if ($boot -le $oldBoot -or $boot -lt $armed) { throw 'Windows did not reboot.' }
    $event = Get-WinEvent -FilterHashtable @{
        LogName = 'System'
        ProviderName = 'Microsoft-Windows-Kernel-General'
        Id = 13
        StartTime = $armed.LocalDateTime
        EndTime = $boot.LocalDateTime
    } -ErrorAction SilentlyContinue | Select-Object -First 1

    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(7)
    do {
        $state = Get-Content -LiteralPath (Join-Path $runtime 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $reportPath = Join-Path $runtime ('reports/{0}.json' -f $state.policyCommit)
        if ($state.done -and $state.policyCommit -ne $test.previousPolicyCommit -and (Test-Path -LiteralPath $reportPath)) { break }
        if ([DateTimeOffset]::UtcNow -gt $deadline) { throw 'No new rule processed after Windows restarted.' }
        Start-Sleep -Seconds 4
    } while ($true)

    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $commit = Read-GitHub "repos/$($report.policyRepo)/commits/$($report.policyCommit)"
    $published = [DateTimeOffset]::Parse($commit.commit.committer.date)
    $task = Get-ScheduledTask -TaskName 'OpenGuildKit Jenkins'
    $taskRun = [DateTimeOffset](Get-ScheduledTaskInfo -TaskName $task.TaskName).LastRunTime
    $javaPath = Join-Path $runtime 'java/bin/java.exe'
    $java = Get-CimInstance Win32_Process -Filter "Name='java.exe'" |
        Where-Object { $_.ExecutablePath -eq $javaPath -and $_.CommandLine -like '*--httpPort=52278*' } |
        Select-Object -First 1
    if (-not $java -or $task.State -ne 'Running' -or $taskRun -lt $boot) { throw 'The Jenkins startup task did not run after reboot.' }
    $started = [DateTimeOffset]$java.CreationDate
    $job = Join-Path $runtime "home/jobs/poll-central-rule/builds/$($report.jenkinsBuild)/build.xml"
    $buildXml = Get-Content -LiteralPath $job -Raw
    if ($buildXml -notmatch 'TimerTriggerCause') { throw 'Jenkins did not start from its timer.' }
    if ($report.targets.Count -ne $test.targets.Count) { throw 'Unexpected pull-request count.' }
    foreach ($target in $report.targets) {
        $before = $test.targets | Where-Object repo -eq $target.repo
        $pr = Read-GitHub "repos/$($target.repo)/pulls/$($target.number)"
        if ($pr.state -ne 'open' -or $pr.head.sha -ne $before.commit -or $target.commit -ne $before.commit -or
            $target.result.policyCommit -ne $report.policyCommit -or $target.result.version -ne $test.expectedVersion -or
            $target.result.state -ne $before.result.state -or $target.result.maxMinutes -ne 30) {
            throw "Unexpected PR result in $($target.repo)."
        }
        $statuses = Read-GitHub "repos/$($target.repo)/commits/$($target.commit)/statuses?per_page=100"
        foreach ($context in @('openguildkit/jenkins', 'openguildkit/export-link-expiry')) {
            $status = $statuses | Where-Object context -eq $context | Select-Object -First 1
            if (-not $status -or $status.description -notlike "*$($report.policyCommit)*" -or $status.state -ne $target.result.state) {
                throw "Wrong status in $($target.repo) for $context."
            }
        }
    }

    $duringRestart = $published -ge $armed -and $published -lt $boot
    $afterShutdown = if ($event) { $published -ge [DateTimeOffset]$event.TimeCreated } else { $null }
    @{
        previousBoot = $oldBoot.ToUniversalTime().ToString('o')
        armedAt = $armed.ToUniversalTime().ToString('o')
        windowsShutdown = $(if ($event) { ([DateTimeOffset]$event.TimeCreated).ToUniversalTime().ToString('o') })
        windowsBoot = $boot.ToUniversalTime().ToString('o')
        rulePublishedAt = $published.ToUniversalTime().ToString('o')
        publishedBeforeWindowsBoot = $duringRestart
        publishedAfterWindowsShutdownEvent = $afterShutdown
        publishedBeforeJenkinsStarted = $published -lt $started
        scheduledTaskStartedAt = $taskRun.ToUniversalTime().ToString('o')
        jenkinsStartedAt = $started.ToUniversalTime().ToString('o')
        jenkinsTrigger = 'TimerTrigger'
        publisherRun = $test.publisherRun
        report = $report
    } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $test.output -Encoding utf8

    $statusState = if ($duringRestart -and $afterShutdown -eq $true) { 'success' } else { 'error' }
    $argsForStatus = @('api', "repos/$($report.policyRepo)/statuses/$($test.controlCommit)", '-f', 'context=openguildkit/reboot-verified',
        '-f', "state=$statusState", '-f', "description=Windows reboot; rule $($report.policyCommit)")
    & $gh @argsForStatus
    if ($LASTEXITCODE -ne 0) { throw 'Could not publish the reboot witness status.' }
    Unregister-ScheduledTask -TaskName 'OpenGuildKit Verify Windows Reboot' -Confirm:$false
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $runtime 'reboot-verification-error.txt') -Encoding utf8
    exit 1
}
