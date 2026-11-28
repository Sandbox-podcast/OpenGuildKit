# Install the OpenGuildKit command from a GitHub release, in one line of PowerShell:
#
#   irm https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.ps1))) -Version 0.18.0
#
# Its own downloads use https addresses only and TLS 1.2 (what install.sh asks of curl with
# --proto '=https' --tlsv1.2). It does not check the scheme of a redirect that PowerShell follows.
#
# It downloads SHA256SUMS.txt and the wheel of the release, checks the wheel's SHA-256 against that file and
# only then installs it with pipx, or with uv when pipx is missing. Without a version it takes the latest release,
# which GitHub never sets to a pre-release; a pre-release is installed only when named with -Version.
# docs/install.md describes it, and the manual installation it replaces.
#
# OPENGUILDKIT_RELEASES_URL replaces https://github.com/Sandbox-podcast/OpenGuildKit/releases. It is reserved
# for the tests, which serve a fake release from a local folder: do not set it otherwise.
param([string]$Version = "")

$ErrorActionPreference = "Stop"

# A terminating error rather than exit: under "irm ... | iex", exit would close the person's PowerShell window.
# Run as a file, the error ends the script with exit code 1.
function Stop-Install([string]$Message) {
    throw "openguildkit install: $Message"
}

# A file:// address, which the tests give, is copied from disk. Any other address must be https, fetched with
# TLS 1.2 for this download only: the setting of the person's session comes back after it.
function Save-Url([string]$Url, [string]$OutFile) {
    if ($Url.StartsWith("file://")) {
        Copy-Item -LiteralPath ([System.Uri]$Url).LocalPath -Destination $OutFile -ErrorAction Stop
    } elseif ($Url.StartsWith("https://")) {
        $Saved = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
        } finally {
            [Net.ServicePointManager]::SecurityProtocol = $Saved
        }
    } else {
        throw "$Url is not an https address."
    }
}

$Releases = if ($env:OPENGUILDKIT_RELEASES_URL) { $env:OPENGUILDKIT_RELEASES_URL } else { "https://github.com/Sandbox-podcast/OpenGuildKit/releases" }
$Version = $Version.TrimStart("v")
if ($Version -and ($Version -notmatch '^[0-9A-Za-z+-][0-9A-Za-z.+-]*$' -or $Version.Contains(".."))) {
    Stop-Install "'$Version' is not a version: give it as on the releases page, for example -Version 0.18.0."
}

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    $Installer = "pipx"
} elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    $Installer = "uv"
} else {
    [Console]::Error.WriteLine("Install pipx or uv, then run this again:")
    [Console]::Error.WriteLine("  pipx: py -m pip install --user pipx, then .\pipx.exe ensurepath   (https://pipx.pypa.io/stable/how-to/install-pipx.html)")
    [Console]::Error.WriteLine('  uv:   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   (https://docs.astral.sh/uv/getting-started/installation/)')
    Stop-Install "neither pipx nor uv is installed: install one of them with a command above."
}

$Work = Join-Path ([IO.Path]::GetTempPath()) ("openguildkit-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Work | Out-Null
try {
    if ($Version) {
        $SumsUrl = "$Releases/download/v$Version/SHA256SUMS.txt"
        $Where = "release v$Version"
    } else {
        $SumsUrl = "$Releases/latest/download/SHA256SUMS.txt"
        $Where = "latest release"
    }
    $Sums = Join-Path $Work "SHA256SUMS.txt"
    try {
        Save-Url $SumsUrl $Sums
    } catch {
        Stop-Install "could not download SHA256SUMS.txt of the $Where ($SumsUrl). Check the version on $Releases."
    }

    # The wheel's line names the version: the latest release says which one it is.
    $Line = Get-Content $Sums | Where-Object { $_ -match '^([0-9a-fA-F]{64})  ?\*?(openguildkit-([0-9A-Za-z.+]+)-py3-none-any\.whl)$' } | Select-Object -First 1
    if (-not $Line) { Stop-Install "SHA256SUMS.txt of the $Where lists no OpenGuildKit wheel: nothing was installed." }
    $null = $Line -match '^([0-9a-fA-F]{64})  ?\*?(openguildkit-([0-9A-Za-z.+]+)-py3-none-any\.whl)$'
    $Expected, $Wheel, $Found = $Matches[1].ToLower(), $Matches[2], $Matches[3]
    if ($Version -and $Found -ne $Version) {
        Stop-Install "SHA256SUMS.txt of release v$Version lists $Wheel, not version ${Version}: nothing was installed."
    }
    $Version = $Found

    $WheelUrl = "$Releases/download/v$Version/$Wheel"
    $WheelPath = Join-Path $Work $Wheel
    try {
        Save-Url $WheelUrl $WheelPath
    } catch {
        Stop-Install "could not download $Wheel of release v$Version ($WheelUrl)."
    }
    "Downloaded OpenGuildKit $Version from $Releases/tag/v$Version"

    $Actual = (Get-FileHash -Path $WheelPath -Algorithm SHA256).Hash.ToLower()
    if ($Actual -ne $Expected) {
        Stop-Install "the SHA-256 of $Wheel ($Actual) differs from SHA256SUMS.txt of release v$Version ($Expected): nothing was installed. Download it again; if it still differs, report it to the maintainers (SECURITY.md)."
    }
    "Checked its SHA-256 against SHA256SUMS.txt of release v$Version"

    # --force replaces an installed version, so the same line upgrades.
    $Log = Join-Path $Work "install.log"
    if ($Installer -eq "pipx") {
        & pipx install --force $WheelPath *> $Log
    } else {
        & uv tool install --force $WheelPath *> $Log
    }
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine((Get-Content $Log -Raw))
        Stop-Install "$Installer could not install ${Wheel}: the output above says why."
    }
    "Installed with $Installer"
    "Next: openguildkit --version, then openguildkit init in your repository"
} finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
