param(
    [Parameter(Mandatory)]
    [string]$RuntimeDirectory,
    [int]$Port = 52278
)

$ErrorActionPreference = 'Stop'
$env:JENKINS_HOME = Join-Path $RuntimeDirectory 'home'
$java = Join-Path $RuntimeDirectory 'java/bin/java.exe'
$war = Join-Path $RuntimeDirectory 'jenkins.war'
$bootstrapComplete = Join-Path $env:JENKINS_HOME 'openguildkit-bootstrap-complete'
$bootstrapSecret = Join-Path $env:JENKINS_HOME 'openguildkit-bootstrap.secret'

# Jenkins builds inherit its environment, so the first password goes through a file that access.groovy deletes.
if (-not (Test-Path -LiteralPath $bootstrapComplete)) {
    $secret = Get-Content -LiteralPath (Join-Path $RuntimeDirectory 'jenkins-admin.dpapi') | ConvertTo-SecureString
    $password = [System.Net.NetworkCredential]::new('', $secret).Password
    [System.IO.File]::WriteAllText($bootstrapSecret, $password, (New-Object System.Text.UTF8Encoding($false)))
}

$launch = @{
    FilePath = $java
    ArgumentList = @(
        '-Djenkins.install.runSetupWizard=false', '-jar', ('"' + $war + '"'),
        "--httpPort=$Port", '--httpListenAddress=127.0.0.1'
    )
    WorkingDirectory = $RuntimeDirectory
    WindowStyle = 'Hidden'
    PassThru = $true
    Wait = $true
    RedirectStandardOutput = Join-Path $RuntimeDirectory 'jenkins.out'
    RedirectStandardError = Join-Path $RuntimeDirectory 'jenkins.err'
}
try {
    $process = Start-Process @launch
} finally {
    Remove-Item -LiteralPath $bootstrapSecret -Force -ErrorAction SilentlyContinue
}
exit $process.ExitCode
