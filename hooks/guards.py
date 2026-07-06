#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Consolidated Kiro v3 PreToolUse guards. Replaces six shell hooks with one process.

Wire as two hook entries in .kiro/hooks/*.json:
  PreToolUse / execute_bash        -> this script
  PreToolUse / fs_read|fs_write    -> this script
Dispatch is on tool_name from the stdin payload.

Exit codes (Kiro v3 contract):
  0 = allow;  1 = allow with user-visible warning;  2 = block, stderr to model.
Stdlib only — runs identically under `uv run --script` or bare python3.
"""
import json, re, sys, os, datetime

# ---------- pattern registry ----------

DESTRUCTIVE_CMDS = [
    (r"rm\s+-rf\s+(/|~)", "rm -rf on root or home"),
    (r"git\s+push\b.*(\s--force\b|\s-f\b)", "force push"),
    (r"--no-verify\b", "hook bypass (--no-verify)"),
    (r"chmod\s+(-R\s+)?777\b", "chmod 777"),
    (r"\bmkfs\.", "filesystem format"),
    (r"\bdd\s+if=.*\bof=/dev/", "raw disk write"),
    (r"\b(curl|wget)\b[^|]*\|\s*(ba|z)?sh\b", "pipe-to-shell"),
    (r"\bsudo\b", "privilege escalation"),
    (r"\b(shutdown|reboot)\b", "system power command"),
]

SECRET_PATHS = re.compile(
    r"(^|/)\.env(\.|$)|\.pem$|\.key$|id_(rsa|ed25519|ecdsa)|\.aws/credentials"
    r"|\.ssh/|\.npmrc$|\.netrc$|secrets?\.(json|ya?ml)$|\.tfstate(\.backup)?$"
)

CREDENTIAL_CONTENT = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub PAT"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{60,}"), "GitHub fine-grained PAT"),
    (re.compile(r"xox[bpars]-[0-9A-Za-z-]{10,}"), "Slack token"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    (re.compile(r"aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]"), "AWS secret key"),
]

# Warn tier: real lookarounds now possible.
OWASP_WARN = [
    (re.compile(r"dangerouslySetInnerHTML"), "React XSS sink"),
    (re.compile(r"\.innerHTML\s*="), "innerHTML assignment"),
    (re.compile(r"document\.write\("), "document.write"),
    (re.compile(r"(?<![\w.])eval\("), "eval()"),
    (re.compile(r"new Function\("), "Function constructor"),
    (re.compile(r"pickle\.loads?\("), "pickle deserialization"),
    (re.compile(r"yaml\.load\((?![^)]*(SafeLoader|safe))"), "yaml.load without SafeLoader"),
    (re.compile(r"shell\s*=\s*True"), "subprocess shell=True"),
    (re.compile(r"os\.system\("), "os.system"),
    (re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
    (re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED"), "Node TLS check disabled"),
    (re.compile(r"(execute|cursor\.execute)\(\s*f?[\"'].*(%s|\{|\+)", re.S), "possible SQL string building"),
]

AUDIT_PATH = os.path.expanduser("~/.kiro/audit/tool-calls.jsonl")

# ---------- helpers ----------

def all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_strings(v)

def iam_wildcard_admin(text):
    """Structural check: parse any embedded JSON policy and walk Statements.
    Catches wildcards anywhere in Action/Resource arrays — the case regex misses."""
    if '"Statement"' not in text:
        return False
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        # Regex fallback for policy fragments inside HCL/templates
        return (re.search(r'"Effect"\s*:\s*"Allow"', text)
                and re.search(r'"Action"\s*:\s*(\[[^\]]*)?"\*"', text)
                and re.search(r'"Resource"\s*:\s*(\[[^\]]*)?"\*"', text))
    stmts = doc.get("Statement", [])
    if isinstance(stmts, dict):
        stmts = [stmts]
    for s in stmts:
        if not isinstance(s, dict) or s.get("Effect") != "Allow":
            continue
        act = s.get("Action", []); res = s.get("Resource", [])
        act = [act] if isinstance(act, str) else act
        res = [res] if isinstance(res, str) else res
        if "*" in act and "*" in res:
            return True
    return False

def audit(payload):
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        payload["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(AUDIT_PATH, "a") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass  # audit failure must never break the agent

# ---------- main ----------

def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0  # unparseable input: fail open, never wedge the agent

    # UserPromptSubmit: guard the user's own prompt against credential leakage
    # (a pasted live key otherwise lands in model context and session JSONL logs).
    prompt = payload.get("prompt")
    if prompt and not payload.get("tool_name"):
        audit({"event": "prompt_submit", "chars": len(prompt)})  # never log the prompt body
        hits = [why for rx, why in CREDENTIAL_CONTENT if rx.search(prompt)]
        if hits:
            print("Blocked by hook: your prompt appears to contain "
                  + ", ".join(hits)
                  + ". Rotate the credential if it's live, and resend the prompt "
                  + "with a placeholder or env-var reference.", file=sys.stderr)
            return 2
        return 0

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {})
    strings = list(all_strings(ti))
    blob = "\n".join(strings)
    blocks, warns = [], []

    audit(payload)

    if tool in ("execute_bash", "shell"):
        cmd = ti.get("command", "") if isinstance(ti, dict) else ""
        for pat, why in DESTRUCTIVE_CMDS:
            if re.search(pat, cmd):
                blocks.append(f"destructive command: {why}")

    if tool in ("fs_read", "fs_write", "read", "write"):
        for s in strings:
            if SECRET_PATHS.search(s):
                blocks.append(f"secrets-file path: {s}")
                break

    if tool in ("fs_write", "write"):
        for rx, why in CREDENTIAL_CONTENT:
            if rx.search(blob):
                blocks.append(f"credential material in content: {why}")
        if iam_wildcard_admin(blob):
            blocks.append("IAM policy grants Allow with Action:* and Resource:* (wildcard admin)")
        hits = sorted({why for rx, why in OWASP_WARN if rx.search(blob)})
        if hits:
            warns.append("risky patterns: " + "; ".join(hits))

    if blocks:
        print("Blocked by hook: " + " | ".join(blocks)
              + ". Explain intent and ask the user to proceed manually if genuinely needed.",
              file=sys.stderr)
        return 2
    if warns:
        print("Security guidance (warn only): " + " | ".join(warns)
              + ". Review before relying on this code.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
