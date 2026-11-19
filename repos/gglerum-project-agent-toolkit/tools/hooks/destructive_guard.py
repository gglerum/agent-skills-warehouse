#!/usr/bin/env python3
"""PreToolUse guard for Bash: block commands that destroy work or escape the sandbox (exit 2 = block, stderr goes to Claude).

Looks at the arguments of each command (shell tokens), not at free text, so a commit message or PR body
that mentions `git reset --hard` passes. The developer can still run a blocked command with `! <command>`.

Blocked: sudo, `git reset --hard`, `git clean` with force, `rm` with recursive+force on /, ., .., ~, $HOME or *,
`docker --privileged` and the Docker socket.
"""
import json
import re
import shlex
import sys

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.DOTALL)
OPERATORS = set("&|;()")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DANGEROUS_RM_TARGETS = {"/", "/*", ".", "./", "..", "../", "~", "~/", "$HOME", "${HOME}", "$HOME/", "${HOME}/", "*", "./*"}
MESSAGE = "Blocked destructive command ({why}). Ask the developer to run it with `! <command>` if it is really needed."


def unquoted_newlines_to_semicolons(cmd: str) -> str:
    out, quote = [], ""
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
    return "".join(out)


def segments(cmd: str) -> list:
    """Split a command line into simple commands (token lists) at unquoted ; & | ( )."""
    cmd = unquoted_newlines_to_semicolons(HEREDOC.sub("\n", cmd))
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = cmd.split()
    result, current = [], []
    for token in tokens:
        if token and set(token) <= OPERATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def strip_prefix(seg: list) -> list:
    """Drop leading VAR=value assignments and `env`/`command`/`nohup`/`time` wrappers."""
    while seg and (ASSIGNMENT.match(seg[0]) or seg[0] in ("env", "command", "nohup", "time", "exec")):
        seg = seg[1:]
    return seg


def short_flags(args: list) -> str:
    return "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))


def check_git(args: list):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    if sub == "reset" and "--hard" in rest:
        return "git reset --hard"
    if sub == "clean":
        flags = short_flags(rest)
        dry = "n" in flags or "--dry-run" in rest
        if ("f" in flags or "--force" in rest) and not dry:
            return "git clean with force"
    return None


def check_rm(args: list):
    flags = short_flags(args)
    recursive = "r" in flags or "R" in flags or "--recursive" in args
    force = "f" in flags or "--force" in args
    targets = [a for a in args if not a.startswith("-")]
    if recursive and force and any(t in DANGEROUS_RM_TARGETS for t in targets):
        return "rm -rf on root, current directory, home or *"
    return None


def check(seg: list):
    seg = strip_prefix(seg)
    if not seg:
        return None
    name, args = seg[0].rsplit("/", 1)[-1], seg[1:]
    if name == "sudo":
        return "sudo"
    if name == "git":
        return check_git(args)
    if name == "rm":
        return check_rm(args)
    if name in ("docker", "podman", "docker-compose"):
        if "--privileged" in args or any("docker.sock" in a for a in args):
            return "privileged container or Docker socket"
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        print("Guard could not parse the tool call; blocked (fail closed).", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict) or not isinstance(data.get("tool_name"), str) or not data["tool_name"]:
        print("Guard received an invalid tool call; blocked (fail closed).", file=sys.stderr)
        sys.exit(2)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        print("Guard received invalid Bash input; blocked (fail closed).", file=sys.stderr)
        sys.exit(2)
    for seg in segments(tool_input["command"]):
        why = check(seg)
        if why:
            print(MESSAGE.format(why=why), file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
