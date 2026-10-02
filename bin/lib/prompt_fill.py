"""Assemble one worker Task spec from a bundled prompt template without the template transiting the coordinator.

    prompt-fill list TEMPLATE            # blocks, their [PLACEHOLDERS] and sizes
    prompt-fill fill REQUEST_JSON        # write the assembled spec, print a receipt

Request: {"schema_version":1,"template":"implementer-prompt.md","block":"First-round prompt template"|<index>,
          "fields":{"REPORT_FILE":"/abs/..."},"replacements":{"<repo-root>":"/abs/repo"},
          "outcome_contract":false,"prepend":"","append":"","output":"/abs/new/spec.md"}
The spec is the mandatory worker boundary (orca-recipes.md section 1) + a blank line + the filled body
(+ the filled shared outcome contract when requested). Every [UPPER_SNAKE] placeholder of the chosen
body must be supplied; the receipt lists the remaining <angle> tokens, which belong to the worker.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SKILL = Path(__file__).resolve().parents[2] / "skills" / "orca-dev"
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_]*\]")


def fail(reason, code=1):
    print("INVALID" if code == 1 else "UNVERIFIABLE"); print(json.dumps({"reason": reason}, ensure_ascii=True)); sys.exit(code)


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def boundary():
    """The literal worker-boundary block from orca-recipes.md section 1."""
    text = read(SKILL / "orca-recipes.md")
    m = re.search(r"```text\n(.*?)\n```", text[text.index("## 1. Task creation"):], re.S)
    if not m: raise ValueError("mandatory boundary block not found in orca-recipes.md")
    return m.group(1).strip()


def blocks(text):
    """Fenced blocks of a template with the last heading seen outside any fence."""
    out = []; heading = None; fence = None; start = None
    lines = text.split("\n")
    for n, line in enumerate(lines):
        m = re.match(r"^(`{3,})", line)
        if fence is None:
            if line.startswith("#"): heading = line.lstrip("#").strip()
            if m: fence = m.group(1); start = n + 1
        elif line.startswith(fence):
            out.append(dict(heading=heading, body="\n".join(lines[start:n]))); fence = None
    if fence is not None: raise ValueError("unterminated fenced block")
    return out


def template_path(name):
    p = (SKILL / "prompts" / str(name)).resolve()
    if p.parent != (SKILL / "prompts").resolve() or not p.is_file(): raise ValueError("unknown template: " + str(name))
    return p


def body_of(name, selector=None):
    text = read(template_path(name)); found = blocks(text)
    if not found:  # an outcome body or the shared contract is the whole file below its title
        return text.split("\n", 1)[1].strip("\n") if text.startswith("#") else text
    if selector is None: return found[0]["body"]
    if isinstance(selector, int):
        if not 0 <= selector < len(found): raise ValueError("block index out of range: %d of %d" % (selector, len(found)))
        return found[selector]["body"]
    matches = [b for b in found if b["heading"] == selector or (b["heading"] or "").startswith(str(selector))]
    if len(matches) != 1: raise ValueError("block selector matches %d blocks: %s" % (len(matches), selector))
    return matches[0]["body"]


def fill(body, fields):
    for key, value in fields.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(value, str):
            raise ValueError("field must map an UPPER_SNAKE name to a string: " + str(key))
        body = body.replace("[" + key + "]", value)
    return body


def listing(args):
    if len(args) != 2: fail("usage: prompt-fill list TEMPLATE", 2)
    try: text = read(template_path(args[1])); found = blocks(text)
    except (OSError, ValueError) as e: fail(str(e), 2)
    rows = [dict(index=i, heading=b["heading"], bytes=len(b["body"].encode("utf-8")), placeholders=sorted(set(PLACEHOLDER.findall(b["body"]))))
            for i, b in enumerate(found)]
    if not rows: rows = [dict(index=0, heading=None, bytes=len(text.encode("utf-8")), placeholders=sorted(set(PLACEHOLDER.findall(text))), whole_file=True)]
    print("VALID"); print(json.dumps(dict(template=args[1], blocks=rows), ensure_ascii=True)); return 0


def assemble(args):
    if len(args) != 2: fail("usage: prompt-fill fill REQUEST_JSON", 2)
    try:
        req = json.loads(read(Path(args[1])))
        if req.get("schema_version") != 1: raise ValueError("unsupported request schema")
        out = Path(str(req["output"]))
        if not out.is_absolute() or out.exists() or not out.parent.is_dir(): raise ValueError("output must be a new absolute file in an existing directory")
        if any(p.is_symlink() for p in (out, *out.parents)): raise ValueError("linked output path")
        fields = req.get("fields") or {}
        if not isinstance(fields, dict): raise ValueError("fields must be an object")
        bodies = [body_of(req["template"], req.get("block"))]
        for old, new in (req.get("replacements") or {}).items():
            if not isinstance(old, str) or not isinstance(new, str) or not old: raise ValueError("replacements map literal text to text")
            if old not in bodies[0]: raise ValueError("replacement text not in template: " + old)
            bodies[0] = bodies[0].replace(old, new)
        if req.get("outcome_contract"): bodies.append(body_of("outcome-worker-contract.md"))
        for key, value in fields.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(key)) or not isinstance(value, str):
                raise ValueError("field must map an UPPER_SNAKE name to a string: " + str(key))
        declared = set(PLACEHOLDER.findall("\n".join(bodies)))
        unknown = sorted(k for k in fields if "[" + k + "]" not in declared)
        if unknown: raise ValueError("fields not used by the template: " + ", ".join(unknown))
        filled = [fill(b, fields) for b in bodies]
        unfilled = sorted(set(PLACEHOLDER.findall("\n".join(filled))))
        if unfilled: raise ValueError("unfilled placeholders: " + ", ".join(unfilled))
        pieces = [boundary(), str(req.get("prepend") or "").strip("\n"), *filled, str(req.get("append") or "").strip("\n")]
        text = "\n\n".join(x for x in pieces if x)
    except KeyError as e: fail("missing request key: " + str(e), 2)
    except (OSError, ValueError) as e: fail(str(e), 1)
    data = (text + "\n").encode("utf-8")
    with out.open("xb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
    angle = sorted(set(re.findall(r"<[a-z][^<>\n]{0,80}>", text)))
    print("VALID"); print(json.dumps(dict(path=str(out), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), worker_tokens=angle), ensure_ascii=True))
    return 0


def main(args):
    if args and args[0] == "list": return listing(args)
    if args and args[0] == "fill": return assemble(args)
    fail("usage: prompt-fill list TEMPLATE | fill REQUEST_JSON", 2)


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
