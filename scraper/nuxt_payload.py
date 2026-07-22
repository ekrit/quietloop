"""Extracts and safely evaluates a page's embedded Nuxt SSR state payload.

olx.ba is Nuxt.js SSR: real listing data isn't in plain HTML <a>/<div>
tags at all — it's serialized into a `window.__NUXT__=(function(a,b,c,
...){...})(...)` call, a minified, deduplicated JS state dump. That's not
safely regex-scrapable (values are variable references, not literals), but
it *is* valid JS, so this evaluates it directly instead of guessing at
regexes against HTML. Confirmed against the real site: `state.search.
results` is a clean array of listing objects (see parser.py).

The fetched JS is untrusted third-party content, so it only ever runs
inside a bare `vm.createContext({})` sandbox with no access to `require`/
`fs`/`process`/network — it can only compute a plain data value, nothing
else. Only the trusted runner script (written here) touches the
filesystem.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class NuxtPayloadError(RuntimeError):
    """Raised when the __NUXT__ payload can't be found, extracted, or
    evaluated. Callers should treat this as a hard failure (the site's
    structure likely changed) rather than silently returning no data."""


def _extract_balanced_expr(text: str, start: int) -> Optional[str]:
    """From index `start` (must be an opening bracket), scan forward
    tracking bracket depth and string state to find the matched end of the
    expression. A single regex can't safely do this for a 300KB+ minified
    payload with nested braces/strings.

    An IIFE like `(function(...){...})(args)` closes its *wrapping* parens
    before the call's own `(args)` even starts, so a naive "stop at the
    first balanced group" scan would capture the function reference
    uncalled (which `JSON.stringify` silently turns into `undefined`).
    This keeps extending through any immediately-following call/bracket
    group(s) instead of stopping early.
    """
    n = len(text)
    if start >= n or text[start] not in "([{":
        return None

    def scan_one_group(pos: int) -> Optional[int]:
        depth = 0
        in_string: Optional[str] = None
        j = pos
        while j < n:
            c = text[j]
            if in_string:
                if c == "\\":
                    j += 2
                    continue
                if c == in_string:
                    in_string = None
                j += 1
                continue
            if c in "\"'`":
                in_string = c
                j += 1
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    end = scan_one_group(start)
    if end is None:
        return None

    while True:
        k = end
        while k < n and text[k] in " \t\r\n":
            k += 1
        if k < n and text[k] in "([":
            next_end = scan_one_group(k)
            if next_end is None:
                break
            end = next_end
            continue
        break

    return text[start:end]


# Trusted runner: has normal Node access (fs, process) to read the payload
# file and print the result. The *payload itself* is only ever evaluated
# inside vm.createContext({}) — a bare sandbox with no require/fs/process/
# network — so the untrusted fetched JS can only compute a plain value.
_SANDBOX_RUNNER_JS = """
const vm = require('vm');
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const sandbox = Object.create(null);
vm.createContext(sandbox);
let result;
try {
  result = vm.runInContext(src, sandbox, { timeout: 5000 });
} catch (e) {
  console.error('EVAL_ERROR: ' + e.message);
  process.exit(1);
}
process.stdout.write(JSON.stringify(result));
"""


def extract_nuxt_state(html: str) -> dict:
    """Finds `window.__NUXT__=...` in `html`, evaluates it in a sandboxed
    Node vm context, and returns the resulting plain object.

    Raises NuxtPayloadError on any failure (not found, unbalanced, node
    missing, evaluation error, non-JSON-serializable result).
    """
    idx = html.find("__NUXT__")
    if idx == -1:
        raise NuxtPayloadError("no '__NUXT__' found in page")

    eq_idx = html.find("=", idx)
    if eq_idx == -1:
        raise NuxtPayloadError("found '__NUXT__' but no following '=' assignment")

    j = eq_idx + 1
    while j < len(html) and html[j] in " \t\r\n":
        j += 1

    js_expr = _extract_balanced_expr(html, j)
    if js_expr is None:
        raise NuxtPayloadError(f"found '__NUXT__=' at offset {eq_idx} but couldn't extract a balanced expression")

    with tempfile.NamedTemporaryFile("w", suffix=".payload.js", delete=False) as f:
        f.write(js_expr)
        payload_path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".runner.js", delete=False) as f:
        f.write(_SANDBOX_RUNNER_JS)
        runner_path = f.name

    try:
        result = subprocess.run(["node", runner_path, payload_path], capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        raise NuxtPayloadError("node not found on PATH") from exc
    finally:
        Path(runner_path).unlink(missing_ok=True)
        Path(payload_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise NuxtPayloadError(f"sandboxed node evaluation failed: {result.stderr[:1000]}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise NuxtPayloadError(f"node output wasn't valid JSON: {exc}") from exc
