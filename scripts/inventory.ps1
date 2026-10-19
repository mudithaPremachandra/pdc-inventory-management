# The `inventory` launcher (Windows). scripts\setup.cmd puts bin\ on your PATH (once),
# then use `inventory` from any terminal. `inventory --help` lists the commands.
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Show-Help {
    @"
Usage: inventory [command]

  inventory                 open the CLI (starts the system if it isn't running)
  inventory start           build and start everything in the background
  inventory stop            stop everything (data is kept)
  inventory restart         restart the running containers
  inventory ps              show the containers and their health
  inventory logs [service]  follow the logs, e.g. inventory logs projector
  inventory test [args]     run the test suite in Docker
  inventory install         put the inventory command on your PATH
  inventory --version       show the version
  inventory <cli command>   run one CLI command, e.g. inventory products
"@
}

$all = $args
$cmd = if ($args.Count -gt 0) { $args[0] } else { "" }
$rest = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

switch ($cmd) {
    "" { docker compose run --rm cli; break }
    "start" {
        docker compose up -d --build --wait @rest
        if ($LASTEXITCODE -eq 0) { "Ready. Type 'inventory' to open the CLI." }
        break
    }
    "stop" { docker compose down; break }
    "restart" { docker compose restart @rest; break }
    "ps" { docker compose ps; break }
    "logs" { docker compose logs -f --tail 100 @rest; break }
    "test" { & (Join-Path $PSScriptRoot "run-tests.ps1") @rest; break }
    { $_ -in "--version", "-v" } {
        $version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
        "inventory $version"
        break
    }
    { $_ -in "--help", "-h" } { Show-Help; break }
    "install" {
        $bin = Join-Path $root "bin"
        $path = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($path -and ($path -split ";") -contains $bin) {
            "Already on your PATH: $bin"
        } else {
            $newPath = if ($path) { $path.TrimEnd(";") + ";" + $bin } else { $bin }
            [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
            "Added $bin to your PATH. Open a new terminal, then try: inventory --help"
        }
        break
    }
    default { docker compose run --rm cli inventory @all }
}
exit $LASTEXITCODE
