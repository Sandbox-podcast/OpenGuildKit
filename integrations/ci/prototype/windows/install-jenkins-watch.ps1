param(
    [Parameter(Mandatory)]
    [string]$JavaDirectory,
    [Parameter(Mandatory)]
    [string]$JenkinsWar,
    [Parameter(Mandatory)]
    [string]$WatchConfig,
    [Parameter(Mandatory)]
    [string]$KitManifest,
    [string]$StateDirectory,
    [switch]$Publish,
    [int]$Port = 52278
)

$ErrorActionPreference = 'Stop'
$taskName = 'OpenGuildKit Jenkins'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "The scheduled task already exists: $taskName"
}

# Windows PowerShell 5.1 writes a byte order mark with -Encoding utf8. Jenkins then rejects the Groovy and XML files.
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-Utf8File([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText($Path, $Content, $utf8)
}

$java = (Resolve-Path -LiteralPath $JavaDirectory).Path
$war = (Resolve-Path -LiteralPath $JenkinsWar).Path
# The coordinator resolves the paths of its configuration from the file's folder, so both files stay in place.
$config = (Resolve-Path -LiteralPath $WatchConfig).Path
$kit = (Resolve-Path -LiteralPath $KitManifest).Path
$node = (Get-Command node.exe -CommandType Application | Select-Object -First 1).Source
$gh = (Get-Command gh.exe -CommandType Application | Select-Object -First 1).Source
$git = (Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
if (-not (Test-Path -LiteralPath (Join-Path $java 'bin/java.exe') -PathType Leaf)) {
    throw "Java runtime missing from $java"
}

$runtime = Join-Path $env:LOCALAPPDATA 'OpenGuildKit/Jenkins'
if (-not $StateDirectory) {
    $StateDirectory = Join-Path $runtime 'state'
}
$homeDirectory = Join-Path $runtime 'home'
$jobDirectory = Join-Path $homeDirectory 'jobs/poll-central-rule'
$initDirectory = Join-Path $homeDirectory 'init.groovy.d'
$appDirectory = Join-Path $runtime 'app'
New-Item -ItemType Directory -Path $jobDirectory,$initDirectory,$StateDirectory -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appDirectory 'pilot'),(Join-Path $appDirectory 'lib') -Force | Out-Null
$state = (Resolve-Path -LiteralPath $StateDirectory).Path

$javaDestination = Join-Path $runtime 'java'
if (-not (Test-Path -LiteralPath (Join-Path $javaDestination 'bin/java.exe') -PathType Leaf)) {
    New-Item -ItemType Directory -Path $javaDestination -Force | Out-Null
    Get-ChildItem -LiteralPath $java -Force | Copy-Item -Destination $javaDestination -Recurse -Force
}
Copy-Item -LiteralPath $war -Destination (Join-Path $runtime 'jenkins.war')

# The Jenkins launcher installs the pinned kit, checks the state directory and runs openguildkit-ci watch.
$launcher = Join-Path $runtime 'start-jenkins.ps1'
$watcher = Join-Path $appDirectory 'pilot/run-watch-jenkins.mjs'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start-jenkins.ps1') -Destination $launcher
foreach ($file in 'pilot/run-watch-jenkins.mjs', 'pilot/install-kit.mjs', 'lib/state-directory.mjs') {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "../../$file") -Destination (Join-Path $appDirectory $file) -Force
}

$adminSecret = Join-Path $runtime 'jenkins-admin.dpapi'
if (-not (Test-Path -LiteralPath $adminSecret)) {
    $password = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    Write-Utf8File $adminSecret (ConvertTo-SecureString -String $password -AsPlainText -Force | ConvertFrom-SecureString)
}
Write-Utf8File (Join-Path $initDirectory 'access.groovy') @'
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import jenkins.model.Jenkins

def instance = Jenkins.get()
def marker = new File(instance.rootDir, 'openguildkit-bootstrap-complete')
def secret = new File(instance.rootDir, 'openguildkit-bootstrap.secret')
try {
    if (!marker.exists()) {
        def realm = new HudsonPrivateSecurityRealm(false)
        realm.createAccount('openguildkit', secret.getText('UTF-8').trim())
        instance.setSecurityRealm(realm)
        def auth = new FullControlOnceLoggedInAuthorizationStrategy()
        auth.setAllowAnonymousRead(false)
        instance.setAuthorizationStrategy(auth)
        instance.save()
        marker.createNewFile()
    }
} catch (Throwable error) {
    // Without its account, Jenkins would keep running without security.
    error.printStackTrace()
    System.exit(1)
} finally {
    secret.delete()
}
'@

$watchArguments = @('--kit', $kit, '--config', $config, '--state', $state)
if ($Publish) {
    $watchArguments += '--publish'
}
$command = @(
    ('set "PATH={0};{1};%PATH%"' -f (Split-Path -Parent $gh),(Split-Path -Parent $git)),
    ((@($node, $watcher) + $watchArguments | ForEach-Object { '"{0}"' -f $_ }) -join ' ')
) -join [Environment]::NewLine
$escaped = [Security.SecurityElement]::Escape($command)
Write-Utf8File (Join-Path $jobDirectory 'config.xml') @"
<project>
  <description>Run the OpenGuildKit CI watcher every minute.</description>
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
"@

$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -RuntimeDirectory "{1}" -Port {2}' -f $launcher,$runtime,$Port
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $runtime
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings
