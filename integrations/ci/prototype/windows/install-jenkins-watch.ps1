param(
    [Parameter(Mandatory)]
    [string]$JavaDirectory,
    [Parameter(Mandatory)]
    [string]$JenkinsWar,
    [Parameter(Mandatory)]
    [string]$WatchConfig,
    [string]$PreviousState,
    [int]$Port = 52278
)

$ErrorActionPreference = 'Stop'
$taskName = 'OpenGuildKit Jenkins'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "The scheduled task already exists: $taskName"
}

$java = (Resolve-Path -LiteralPath $JavaDirectory).Path
$war = (Resolve-Path -LiteralPath $JenkinsWar).Path
$config = (Resolve-Path -LiteralPath $WatchConfig).Path
$node = (Get-Command node.exe -CommandType Application | Select-Object -First 1).Source
$gh = (Get-Command gh.exe -CommandType Application | Select-Object -First 1).Source
if (-not (Test-Path -LiteralPath (Join-Path $java 'bin/java.exe') -PathType Leaf)) {
    throw "Java runtime missing from $java"
}

$runtime = Join-Path $env:LOCALAPPDATA 'OpenGuildKit/Jenkins'
$homeDirectory = Join-Path $runtime 'home'
$jobDirectory = Join-Path $homeDirectory 'jobs/poll-central-rule'
$initDirectory = Join-Path $homeDirectory 'init.groovy.d'
$appDirectory = Join-Path $runtime 'app'
$checkerDirectory = Join-Path $appDirectory 'demo'
New-Item -ItemType Directory -Path $jobDirectory,$initDirectory,$checkerDirectory -Force | Out-Null

$javaDestination = Join-Path $runtime 'java'
if (-not (Test-Path -LiteralPath (Join-Path $javaDestination 'bin/java.exe') -PathType Leaf)) {
    New-Item -ItemType Directory -Path $javaDestination -Force | Out-Null
    Get-ChildItem -LiteralPath $java -Force | Copy-Item -Destination $javaDestination -Recurse -Force
}
Copy-Item -LiteralPath $war -Destination (Join-Path $runtime 'jenkins.war')
Copy-Item -LiteralPath $config -Destination (Join-Path $runtime 'watch.json')
$statePath = Join-Path $runtime 'state.json'
if ($PreviousState -and -not (Test-Path -LiteralPath $statePath)) {
    Copy-Item -LiteralPath $PreviousState -Destination $statePath
}

$launcher = Join-Path $runtime 'start-jenkins.ps1'
$watcher = Join-Path $appDirectory 'watch-rule.mjs'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start-jenkins.ps1') -Destination $launcher
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../watch-rule.mjs') -Destination $watcher
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../demo/check.mjs') -Destination (Join-Path $checkerDirectory 'check.mjs')

$adminSecret = Join-Path $runtime 'jenkins-admin.dpapi'
if (-not (Test-Path -LiteralPath $adminSecret)) {
    $password = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    ConvertTo-SecureString -String $password -AsPlainText -Force |
        ConvertFrom-SecureString | Set-Content -LiteralPath $adminSecret -Encoding utf8
}
@'
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import jenkins.model.Jenkins

def instance = Jenkins.get()
def marker = new File(instance.rootDir, 'openguildkit-bootstrap-complete')
if (!marker.exists()) {
    def realm = new HudsonPrivateSecurityRealm(false)
    realm.createAccount('openguildkit', System.getenv('OGK_JENKINS_PASSWORD'))
    instance.setSecurityRealm(realm)
    def auth = new FullControlOnceLoggedInAuthorizationStrategy()
    auth.setAllowAnonymousRead(false)
    instance.setAuthorizationStrategy(auth)
    instance.save()
    marker.createNewFile()
}
'@ | Set-Content -LiteralPath (Join-Path $initDirectory 'access.groovy') -Encoding utf8

$command = @(
    ('set "PATH={0};%PATH%"' -f (Split-Path -Parent $gh)),
    ('"{0}" "{1}" "{2}" "{3}"' -f $node,$watcher,(Join-Path $runtime 'watch.json'),$statePath)
) -join [Environment]::NewLine
$escaped = [Security.SecurityElement]::Escape($command)
@"
<project>
  <description>Check the central OpenGuildKit rule every minute.</description>
  <logRotator class="hudson.tasks.LogRotator">
    <daysToKeep>-1</daysToKeep><numToKeep>40</numToKeep>
    <artifactDaysToKeep>-1</artifactDaysToKeep><artifactNumToKeep>-1</artifactNumToKeep>
  </logRotator>
  <scm class="hudson.scm.NullSCM"/>
  <canRoam>true</canRoam>
  <disabled>false</disabled>
  <triggers><hudson.triggers.TimerTrigger><spec>* * * * *</spec></hudson.triggers.TimerTrigger></triggers>
  <concurrentBuild>false</concurrentBuild>
  <builders><hudson.tasks.BatchFile><command>$escaped</command></hudson.tasks.BatchFile></builders>
  <publishers><hudson.tasks.ArtifactArchiver><artifacts>result.json</artifacts><allowEmptyArchive>true</allowEmptyArchive><onlyIfSuccessful>false</onlyIfSuccessful></hudson.tasks.ArtifactArchiver></publishers>
</project>
"@ | Set-Content -LiteralPath (Join-Path $jobDirectory 'config.xml') -Encoding utf8

$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -RuntimeDirectory "{1}" -Port {2}' -f $launcher,$runtime,$Port
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $runtime
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings
