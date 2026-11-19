"""Per-repo settings for the shared scripts, read from .claude/workflow.conf in the repo root.

The file is plain shell variables (it is also sourced by new_session.sh): KEY=value, # comments.
Keys used here: BASE_BRANCH, GITHUB_REPO, STAGING_HOST, SCRIPTS_DIR, SONAR_PROPERTIES_FILE,
DEFECTDOJO_URL, DEFECTDOJO_PRODUCT, ASANA_PROJECT_ID (see the source toolchain README).
"""
import os
import re
import subprocess

CONFIG_PATH = os.path.join('.agent-toolkit', 'workflow.conf')
ASSIGNMENT = re.compile(r'^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$')


def repo_root(timeout=None):
    """Root of the repo the script is run in (not of the vendored toolchain below it)."""
    try:
        return subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True, timeout=timeout, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.getcwd()


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    return value.split(' #', 1)[0].strip()


def load(timeout=None):
    path = os.environ.get("TOOLKIT_CONFIG") or os.path.join(repo_root(timeout=timeout), CONFIG_PATH)
    if not os.path.isfile(path):
        return {}
    values = {}
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            match = ASSIGNMENT.match(line.strip())
            if match:
                values[match.group(1)] = _unquote(match.group(2))
    return values


def get(key, default=None, *, timeout=None):
    """get('DEFECTDOJO_PRODUCT') -> value or default."""
    return os.environ.get(key, load(timeout=timeout).get(key, default))
