set -u
cd "$(dirname "$0")/.."

cleanup() {
    docker compose --profile test rm --stop --force postgres-test >/dev/null 2>&1
}
trap cleanup EXIT

docker compose --profile test build tests || exit 1

if [ "$#" -eq 0 ]; then
    docker compose --profile test run --rm tests
else
    docker compose --profile test run --rm tests pytest "$@"
fi
