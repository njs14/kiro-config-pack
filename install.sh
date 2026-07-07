#!/usr/bin/env bash
# Idempotent installer for the Kiro v3 config pack.
# Copies (never symlinks) each file to its install path per the README table,
# backing up anything it would overwrite to ~/.kiro/backup-<timestamp>/ first.
# Never modifies the pack files in this repo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIRO_DIR="${HOME}/.kiro"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${KIRO_DIR}/backup-${TS}"

# src (repo-relative) -> dest (absolute)
FILES=(
  "hooks/anthropic-defaults.json|${KIRO_DIR}/hooks/anthropic-defaults.json"
  "hooks/guards.py|${KIRO_DIR}/hooks/guards.py"
  "hooks/memory.py|${KIRO_DIR}/hooks/memory.py"
  "settings/permissions.yaml|${KIRO_DIR}/settings/permissions.yaml"
  "settings/mcp.json|${KIRO_DIR}/settings/mcp.json"
  "steering/memory-steering.md|${KIRO_DIR}/steering/memory-steering.md"
  "skills/kiro-config-pack/SKILL.md|${KIRO_DIR}/skills/kiro-config-pack/SKILL.md"
  "skills/kiro-config-pack/scripts/selftest.py|${KIRO_DIR}/skills/kiro-config-pack/scripts/selftest.py"
  "agents/kiro.json|${KIRO_DIR}/agents/kiro.json"
  "agents/kiro.md|${KIRO_DIR}/agents/kiro.md"
)

EXECUTABLES=(
  "${KIRO_DIR}/hooks/guards.py"
  "${KIRO_DIR}/hooks/memory.py"
  "${KIRO_DIR}/skills/kiro-config-pack/scripts/selftest.py"
)

backed_up=()
copied=()
unchanged=()

echo "== Kiro config pack installer =="
echo "Source: ${REPO_DIR}"
echo "Target: ${KIRO_DIR}"
echo

for entry in "${FILES[@]}"; do
  src="${REPO_DIR}/${entry%%|*}"
  dest="${entry##*|}"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: missing source file: $src" >&2
    exit 1
  fi
  if [[ -e "$dest" ]]; then
    if cmp -s "$src" "$dest"; then
      unchanged+=("$dest")
      continue
    fi
    rel="${dest#"${KIRO_DIR}"/}"
    mkdir -p "${BACKUP_DIR}/$(dirname "$rel")"
    cp -p "$dest" "${BACKUP_DIR}/${rel}"
    backed_up+=("$dest -> ${BACKUP_DIR}/${rel}")
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  copied+=("$dest")
done

for f in "${EXECUTABLES[@]}"; do
  [[ -f "$f" ]] && chmod +x "$f"
done

echo "-- Report --"
if ((${#backed_up[@]})); then
  echo "Backed up (pre-existing, differing files):"
  printf '  %s\n' "${backed_up[@]}"
else
  echo "Backed up: nothing (no differing pre-existing files)"
fi
if ((${#copied[@]})); then
  echo "Installed/updated:"
  printf '  %s\n' "${copied[@]}"
else
  echo "Installed/updated: nothing"
fi
if ((${#unchanged[@]})); then
  echo "Unchanged (already identical):"
  printf '  %s\n' "${unchanged[@]}"
fi
echo
echo "Not installed automatically:"
echo "  legacy/kiro-v2-agent-hooks.json — merge manually into a v2 agent config if needed."
echo
echo "Hook activation on kiro-cli 2.11.0: hooks load via the agent config, so run"
echo "  kiro-cli chat --agent kiro        (per session), or"
echo "  kiro-cli agent set-default kiro   (make it the default)"
echo
echo "Done. Executables: guards.py, memory.py, selftest.py"
