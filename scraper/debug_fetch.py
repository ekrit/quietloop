"""One-off diagnostic, NOT part of the daily pipeline.

Fetches a single olx.ba URL and reports what's actually there. The site is
Nuxt.js SSR: real listing data (price, images, etc.) is embedded in a
`window.__NUXT__=(function(a,b,c,...){...})(...)` payload — a minified,
deduplicated JS state dump, not plain JSON and not safely regex-scrapable
(values are variable references, not literals).

This extracts that script and evaluates it with Node to get the real
deserialized object. The fetched JS is untrusted third-party content, so
it is run inside a bare `vm.createContext({})` sandbox with no access to
`require`/`fs`/`process`/network — it can only compute a plain data value,
nothing else. Only our own runner script (trusted, written here) touches
the filesystem.

Run via the "Debug fetch" GitHub Actions workflow (manual dispatch only)
or locally: `python -m scraper.debug_fetch [url]` (requires `node` on PATH
for the __NUXT__ dump; the plain-HTML report works without it).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import BASE_URL
from .http_client import PoliteSession

_NUXT_SCRIPT_RE = re.compile(
    r"window\.__NUXT__\s*=\s*(\(function\(.*?\)\s*\{.*?\}\)\(.*?\))\s*;?\s*</script>", re.DOTALL
)

# Trusted runner: has normal Node access (fs, process) to read the payload
# file and print the result. The *payload itself* is only ever evaluated
# inside vm.createContext({}) below — a bare sandbox with no require/fs/
# process/network — so the untrusted fetched JS can only compute a plain
# value, nothing else.
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


def dump_nuxt_payload(html: str) -> None:
    match = _NUXT_SCRIPT_RE.search(html)
    if not match:
        print("Could not locate a window.__NUXT__=(function(...){...})(...) script block.")
        return

    js_expr = match.group(1)
    print(f"nuxt_payload_script_length={len(js_expr)}")

    with tempfile.NamedTemporaryFile("w", suffix=".payload.js", delete=False) as f:
        f.write(js_expr)
        payload_path = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".runner.js", delete=False) as f:
        f.write(_SANDBOX_RUNNER_JS)
        runner_path = f.name

    try:
        result = subprocess.run(
            ["node", runner_path, payload_path], capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        print("node not found on PATH — cannot evaluate the payload here.")
        return
    finally:
        Path(runner_path).unlink(missing_ok=True)
        Path(payload_path).unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"sandboxed node evaluation failed (exit {result.returncode}):")
        print(result.stderr[:3000])
        return

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"node ran but output wasn't valid JSON: {exc}")
        print(result.stdout[:2000])
        return

    print("Successfully deserialized the __NUXT__ payload (sandboxed).")
    print(f"top_level_type={type(data).__name__}")
    if isinstance(data, dict):
        print(f"top_level_keys={list(data.keys())}")

        def walk(obj, path="", depth=0):
            if depth > 5:
                return
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                sample_keys = list(obj[0].keys())
                print(f"  candidate list at {path or '<root>'}: len={len(obj)}, item_keys={sample_keys}")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{path}.{k}" if path else k, depth + 1)

        walk(data)

    out_path = Path("/tmp/nuxt_payload.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2)[:200000])
    print(f"wrote (possibly truncated) payload to {out_path}")


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else f"{BASE_URL}/pretraga?category_id=18"
    session = PoliteSession()
    response = session.get(url)
    text = response.text

    print(f"status_code={response.status_code}")
    print(f"final_url={response.url}")
    print(f"content_length={len(text)}")

    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    print(f"title={title_match.group(1).strip() if title_match else None}")

    print("--- NUXT payload ---")
    dump_nuxt_payload(text)


if __name__ == "__main__":
    main()
