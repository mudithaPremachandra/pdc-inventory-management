#!/usr/bin/env sh
# One-time setup (Git Bash, macOS, Linux): puts `inventory` on your PATH and starts the system.
cd "$(dirname "$0")" || exit 1

sh ./inventory.sh install || exit 1
sh ./inventory.sh start || exit 1
echo
echo "Installed. Open a new terminal and type: inventory"
