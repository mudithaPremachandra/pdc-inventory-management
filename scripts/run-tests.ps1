Set-Location (Join-Path $PSScriptRoot "..")

try {
    docker compose --profile test build tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if ($args.Count -eq 0) {
        docker compose --profile test run --rm tests
    } else {
        docker compose --profile test run --rm tests pytest @args
    }
    $code = $LASTEXITCODE
}
finally {
    docker compose --profile test rm --stop --force postgres-test | Out-Null
}
exit $code
