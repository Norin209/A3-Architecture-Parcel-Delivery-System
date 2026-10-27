#!/bin/zsh
cd -- "${0:A:h}" || exit 1
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3 /opt/anaconda3/bin/python3.12; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    exec "$candidate" run_ui.py "$@"
  fi
done
printf '%s\n' 'Python 3.10 or newer is required. Install it and reopen this launcher.'
read '?Press Return to close.'
