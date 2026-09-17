#!/usr/bin/env bash
set -euo pipefail

# Shared setup for the P6 landed-route replay scripts. This file is sourceable
# and executable; it never selects the user's default safe-delete root.

P6_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CHECKOUT="${CHECKOUT:-$(cd -- "$P6_SCRIPT_DIR/../../.." && pwd -P)}"
CHECKOUT="$(cd -- "$CHECKOUT" && pwd -P)"
export CHECKOUT

if [[ ! -x "$CHECKOUT/safe-delete" ]]; then
    printf 'expected landed CLI at %s/safe-delete\n' "$CHECKOUT" >&2
    exit 1
fi

if [[ -z "${TESTROOT:-}" ]]; then
    TESTROOT="$(mktemp -d "${TMPDIR:-/tmp}/safe-delete-p6.XXXXXX")"
else
    mkdir -p -- "$TESTROOT"
    TESTROOT="$(cd -- "$TESTROOT" && pwd -P)"
fi
export TESTROOT

SAFE_DELETE_ROOT="${SAFE_DELETE_ROOT:-$TESTROOT/safe-delete-root}"
P6_WORKSPACE="${P6_WORKSPACE:-$TESTROOT/workspace}"
P6_HOME="${P6_HOME:-$TESTROOT/home}"
P6_XDG_DATA_HOME="${P6_XDG_DATA_HOME:-$TESTROOT/xdg-data}"
P6_XDG_CONFIG_HOME="${P6_XDG_CONFIG_HOME:-$TESTROOT/xdg-config}"
mkdir -p -- "$P6_WORKSPACE"
mkdir -p -- "$P6_HOME" "$P6_XDG_DATA_HOME" "$P6_XDG_CONFIG_HOME"
export SAFE_DELETE_ROOT P6_WORKSPACE P6_HOME P6_XDG_DATA_HOME P6_XDG_CONFIG_HOME
export HOME="$P6_HOME" XDG_DATA_HOME="$P6_XDG_DATA_HOME" XDG_CONFIG_HOME="$P6_XDG_CONFIG_HOME"

export P6_EVIDENCE_SHA="$(git -C "$CHECKOUT" rev-parse HEAD)"
export P6_PRODUCT_SHA="${P6_PRODUCT_SHA:-$(git -C "$CHECKOUT" merge-base HEAD origin/main 2>/dev/null || git -C "$CHECKOUT" rev-parse HEAD)}"
export P6_SHA="$P6_PRODUCT_SHA"
export P6_UTC_START="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

p6_enter_checkout() {
    cd -- "$CHECKOUT"
}

p6_require_clean() {
    local dirty
    dirty="$(git -C "$CHECKOUT" status --porcelain --untracked-files=all)"
    if [[ -n "$dirty" ]]; then
        printf 'P6 replay requires a clean checkout; refusing dirty state:\n%s\n' "$dirty" >&2
        return 1
    fi
}

p6_record_env() {
    local status
    status="$(git -C "$CHECKOUT" status --porcelain --untracked-files=all)"
    printf '%s\n' \
        'replay_status=CAPTURED' \
        "checkout=\$CHECKOUT ($CHECKOUT)" \
        "testroot=\$TESTROOT ($TESTROOT)" \
        "safe_delete_root=\$SAFE_DELETE_ROOT ($SAFE_DELETE_ROOT)" \
        "workspace=\$P6_WORKSPACE ($P6_WORKSPACE)" \
        "home=\$P6_HOME ($P6_HOME)" \
        "xdg_data_home=\$P6_XDG_DATA_HOME ($P6_XDG_DATA_HOME)" \
        "xdg_config_home=\$P6_XDG_CONFIG_HOME ($P6_XDG_CONFIG_HOME)" \
        "product_sha=$P6_PRODUCT_SHA" \
        "evidence_sha=$P6_EVIDENCE_SHA" \
        "cwd=$(pwd -P)" \
        "utc_start=$P6_UTC_START" \
        "python=$(python3 --version 2>&1)" \
        "os=$(uname -srm)" \
        "git_status=$([[ -z "$status" ]] && printf clean || printf dirty)"
}

p6_finish_replay() {
    export P6_UTC_END="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'utc_end=%s\n' "$P6_UTC_END"
    printf 'replay_marker=CAPTURED\n'
}

p6_write_instrumented_cli() {
    local wrapper="$1"
    local calls="$2"
    python3 - "$wrapper" "$calls" "$CHECKOUT/safe-delete" <<'PY'
import shlex
import sys
from pathlib import Path

wrapper, calls, cli = sys.argv[1:]
Path(wrapper).write_text(
    "#!/bin/sh\n"
    f"printf '%s\\n' \"$*\" >> {shlex.quote(calls)}\n"
    f"exec {shlex.quote(cli)} \"$@\"\n",
    encoding="utf-8",
)
Path(wrapper).chmod(0o700)
PY
}

p6_write_raw_sentinels() {
    local directory="$1"
    local marker="$2"
    python3 - "$directory" "$marker" <<'PY'
import shlex
import sys
from pathlib import Path

directory, marker = sys.argv[1:]
root = Path(directory)
root.mkdir(parents=True, exist_ok=True)
for command in ("rm", "unlink", "rmdir"):
    path = root / command
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' {command} >> {shlex.quote(marker)}\n"
        "exit 97\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
PY
}

p6_cli() {
    "$CHECKOUT/safe-delete" --root "$SAFE_DELETE_ROOT" --json "$@"
}

p6_cli_at() {
    local cwd="$1"
    shift
    (
        cd -- "$cwd"
        "$CHECKOUT/safe-delete" --root "$SAFE_DELETE_ROOT" --json "$@"
    )
}

p6_assert_ok() {
    local payload="$1"
    P6_JSON="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["P6_JSON"])
if payload.get("ok") is not True:
    raise SystemExit(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

p6_assert_error() {
    local payload="$1"
    local expected="$2"
    P6_JSON="$payload" P6_EXPECTED="$expected" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["P6_JSON"])
codes = [item.get("code") for item in payload.get("errors", [])]
if payload.get("ok") is not False or os.environ["P6_EXPECTED"] not in codes:
    raise SystemExit(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

p6_result_field() {
    local payload="$1"
    local index="$2"
    local field="$3"
    P6_JSON="$payload" python3 - "$index" "$field" <<'PY'
import json
import os
import sys

value = json.loads(os.environ["P6_JSON"])["results"][int(sys.argv[1])][sys.argv[2]]
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
elif value is None:
    print("null")
else:
    print(value)
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    p6_record_env
fi
