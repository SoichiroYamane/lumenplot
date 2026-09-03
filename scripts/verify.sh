#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
Usage: scripts/verify.sh [--help] [--skip-install] [--skip-nix]

Run the contributor verification gates from the repository root.

Options:
  --help          show this help and exit
  --skip-install  skip installing the local package
  --skip-nix      skip the Nix flake check
EOF
}

help_requested=0
skip_install=0
skip_nix=0

for arg in "$@"; do
    case "$arg" in
        --help)
            help_requested=1
            ;;
        --skip-install)
            skip_install=1
            ;;
        --skip-nix)
            skip_nix=1
            ;;
        *)
            printf 'error: unknown option: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$help_requested" -eq 1 ]; then
    usage
    exit 0
fi

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

MPLCONFIGDIR=$(mktemp -d "${TMPDIR:-/tmp}/lumenplot-mplconfig.XXXXXX")
export MPLCONFIGDIR

cleanup() {
    status=$?
    trap - 0 HUP INT TERM
    if ! rm -rf "$MPLCONFIGDIR"; then
        printf 'error: failed to remove temporary MPLCONFIGDIR: %s\n' "$MPLCONFIGDIR" >&2
        status=1
    fi
    exit "$status"
}

trap cleanup 0
trap 'exit 1' HUP INT TERM

if [ ! -d "$MPLCONFIGDIR" ]; then
    printf 'error: mktemp did not create MPLCONFIGDIR: %s\n' "$MPLCONFIGDIR" >&2
    exit 1
fi
if [ ! -w "$MPLCONFIGDIR" ]; then
    printf 'error: MPLCONFIGDIR is not writable: %s\n' "$MPLCONFIGDIR" >&2
    exit 1
fi

run_gate() {
    printf '+'
    for arg in "$@"; do
        printf ' %s' "$arg"
    done
    printf '\n'
    "$@"
}

if [ "$skip_install" -eq 0 ]; then
    run_gate python3 -m pip install --editable .
else
    printf '%s\n' 'Skipping local package installation (--skip-install).'
fi

run_gate cargo fmt --all -- --check
run_gate cargo metadata --locked --no-deps --format-version 1
run_gate cargo check --locked --workspace --all-targets --all-features
run_gate cargo test --locked --workspace --all-features
run_gate cargo clippy --locked --workspace --all-targets --all-features -- -D warnings

run_gate python3 scripts/check_workspace_architecture.py
run_gate python3 scripts/check_phase2b_dependencies.py
run_gate python3 scripts/verify_traceability_coverage.py
run_gate python3 -m unittest discover -s scripts
run_gate python3 -m unittest discover -s tests/python

if [ "$skip_nix" -eq 0 ]; then
    run_gate nix flake check --all-systems --no-build --no-update-lock-file
else
    printf '%s\n' 'Skipping Nix flake check (--skip-nix).'
fi

run_gate git diff --check
printf '%s\n' 'Verification completed successfully.'
