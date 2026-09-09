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

VERIFY_TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/lumenplot-verify.XXXXXX")
MPLCONFIGDIR="$VERIFY_TMPDIR/mplconfig"
VERIFY_VENV="$VERIFY_TMPDIR/venv"
PYTHON=python3
export MPLCONFIGDIR

cleanup() {
    status=$?
    trap - 0 HUP INT TERM
    if ! rm -rf "$VERIFY_TMPDIR"; then
        printf 'error: failed to remove temporary verification directory: %s\n' "$VERIFY_TMPDIR" >&2
        status=1
    fi
    exit "$status"
}

trap cleanup 0
trap 'exit 1' HUP INT TERM

if ! mkdir -p "$MPLCONFIGDIR"; then
    printf 'error: failed to create MPLCONFIGDIR: %s\n' "$MPLCONFIGDIR" >&2
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
    run_gate python3 -m venv "$VERIFY_VENV"
    PYTHON="$VERIFY_VENV/bin/python"
    run_gate "$PYTHON" -m pip install --editable .
else
    printf '%s\n' 'Skipping local package installation (--skip-install).'
fi

run_gate cargo fmt --all -- --check
run_gate cargo metadata --locked --no-deps --format-version 1
run_gate cargo check --locked --workspace --all-targets --all-features
run_gate cargo test --locked --workspace --all-features
run_gate cargo clippy --locked --workspace --all-targets --all-features -- -D warnings

run_gate "$PYTHON" scripts/check_workspace_architecture.py
run_gate "$PYTHON" scripts/check_phase2b_dependencies.py
run_gate "$PYTHON" scripts/check_requirements_traceability.py
run_gate "$PYTHON" -m unittest scripts.test_check_requirements_traceability
run_gate "$PYTHON" scripts/check_docs.py
# Keep the scripts suite explicit: the obsolete adoption-note verifier checks
# removed historical notes and is intentionally not a verification gate.
run_gate "$PYTHON" -m unittest \
    scripts.test_bench_analysis \
    scripts.test_bench_ci \
    scripts.test_check_docs \
    scripts.test_check_phase2b_dependencies \
    scripts.test_check_workspace_architecture \
    scripts.test_phase3a2_manifest \
    scripts.test_phase3a2_sbom \
    scripts.test_phase3b_runtime \
    scripts.test_phase3b_wheel_evidence \
    scripts.test_verify
run_gate "$PYTHON" -m unittest discover -s tests/python

if [ "$skip_nix" -eq 0 ]; then
    run_gate nix flake check --all-systems --no-build --no-update-lock-file
else
    printf '%s\n' 'Skipping Nix flake check (--skip-nix).'
fi

run_gate git diff --check
printf '%s\n' 'Verification completed successfully.'
