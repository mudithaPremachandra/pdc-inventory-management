#!/usr/bin/env sh
# The `inventory` launcher (Git Bash, macOS, Linux). scripts/setup.sh puts bin/ on your PATH (once),
# then use `inventory` from any terminal. `inventory --help` lists the commands.
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 1

show_help() {
    cat <<'EOF'
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
EOF
}

cmd="${1:-}"
[ "$#" -gt 0 ] && shift

case "$cmd" in
    "") exec docker compose run --rm cli ;;
    start)
        docker compose up -d --build --wait "$@" && echo "Ready. Type 'inventory' to open the CLI." ;;
    stop) exec docker compose down ;;
    restart) exec docker compose restart "$@" ;;
    ps) exec docker compose ps ;;
    logs) exec docker compose logs -f --tail 100 "$@" ;;
    test) exec sh scripts/run-tests.sh "$@" ;;
    --version|-v) echo "inventory $(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | tr -d '\r')" ;;
    --help|-h) show_help ;;
    install)
        line="export PATH=\"$root/bin:\$PATH\""
        rc="$HOME/.bashrc"
        [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "${SHELL:-}")" = "zsh" ] && rc="$HOME/.zshrc"
        if grep -qsF "$line" "$rc"; then
            echo "Already in $rc"
        else
            echo "$line" >> "$rc"
            echo "Added $root/bin to your PATH in $rc. Open a new terminal, then try: inventory --help"
        fi ;;
    *) exec docker compose run --rm cli inventory "$cmd" "$@" ;;
esac
