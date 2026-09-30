#!/usr/bin/env python3
"""Build the workshop walkthrough from its one source, walkthrough.md.

    python3 walkthrough/build.py            # write the notebook, the R Markdown file and walkthrough.json
    python3 walkthrough/build.py --check    # fail if any generated file is out of date with walkthrough.md
    python3 walkthrough/build.py --run py   # execute the Python notebook against the live API
    python3 walkthrough/build.py --run r    # render the R Markdown file against the live API
    python3 walkthrough/build.py --run py --skip-create   # steps 1 to 5 only, no project is created

walkthrough.md holds the prose and, for every step, a ```python block followed by an ```r block.
A block whose info string carries "install" (```r install) or whose language is bash is shown but
never executed. Outputs:

  python/heatready-walkthrough.ipynb   prose as markdown cells, python blocks as code cells
  r/heatready-walkthrough.Rmd          prose as text, r blocks as chunks
  walkthrough.json                     sections of prose and paired python/r code, for the web page

--run needs HEATREADY_USERNAME and HEATREADY_KEY. It reads the two data files from this checkout
rather than from GitHub, and deletes the project step 6 creates once the run finishes.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "walkthrough.md")
OUT_IPYNB = os.path.join(HERE, "python", "heatready-walkthrough.ipynb")
OUT_RMD = os.path.join(HERE, "r", "heatready-walkthrough.Rmd")
OUT_JSON = os.path.join(HERE, "walkthrough.json")
TRACTS_URL = "https://raw.githubusercontent.com/crisisready/heat-ready-clients/main/walkthrough/data/nyc-tracts.geojson"
TRACTS_LOCAL = os.path.join(HERE, "data", "nyc-tracts.geojson")
CENTERS_URL = "https://raw.githubusercontent.com/crisisready/heat-ready-clients/main/walkthrough/data/nyc-older-adult-centers.csv"
CENTERS_LOCAL = os.path.join(HERE, "data", "nyc-older-adult-centers.csv")
FENCE = re.compile(r"^```(\S*)(.*)$")


def parse(text):
    """Split the source into ('prose', text) and ('code', lang, run, text) pieces."""
    pieces, buf, code, lang, run = [], [], None, None, True
    for line in text.splitlines():
        m = FENCE.match(line)
        if code is None and m and m.group(1):
            if buf and "".join(buf).strip():
                pieces.append(("prose", "\n".join(buf).strip()))
            buf, code = [], []
            lang = m.group(1)
            run = lang in ("python", "r") and "install" not in m.group(2)
        elif code is not None and line.startswith("```"):
            pieces.append(("code", lang, run, "\n".join(code)))
            code = None
        elif code is not None:
            code.append(line)
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        pieces.append(("prose", "\n".join(buf).strip()))
    return pieces


def fenced(lang, body):
    return f"```{lang}\n{body}\n```"


def build_ipynb(pieces):
    cells = []

    def md(text):
        if cells and cells[-1]["cell_type"] == "markdown":
            cells[-1]["source"] += "\n\n" + text
        else:
            cells.append({"cell_type": "markdown", "metadata": {}, "source": text})

    for p in pieces:
        if p[0] == "prose":
            md(p[1])
        elif p[1] == "python" and p[2]:
            cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": p[3]})
        elif p[1] == "bash":
            md(fenced("bash", p[3]))
    for i, c in enumerate(cells):
        c["id"] = f"cell-{i:02d}"
        c["source"] = c["source"].splitlines(keepends=True)
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def build_rmd(pieces):
    title = next(p[1] for p in pieces if p[0] == "prose").splitlines()[0].lstrip("# ").strip()
    out = [f'---\ntitle: "{title}"\noutput: html_document\n---']
    for p in pieces:
        if p[0] == "prose":
            text = p[1]
            if text.startswith("# "):
                text = text.split("\n", 1)[1].strip() if "\n" in text else ""
            if text:
                out.append(text)
        elif p[1] == "r" and p[2]:
            out.append(fenced("{r}", p[3]))
        elif p[1] == "r":
            out.append(fenced("r", p[3]))
    return "\n\n".join(out) + "\n"


def build_json(pieces):
    """Sections split at '## ' headings; code blocks pair each python/bash block with the r block after it."""
    title, intro, sections = None, [], []
    blocks = intro
    pending = None
    for p in pieces:
        if p[0] == "prose":
            for para in re.split(r"\n\s*\n", p[1]):
                para = para.strip()
                if para.startswith("# "):
                    title = para[2:].strip()
                elif para.startswith("## "):
                    sections.append({"title": para[3:].strip(), "blocks": []})
                    blocks = sections[-1]["blocks"]
                elif para:
                    blocks.append({"type": "prose", "text": " ".join(para.split())})
        elif p[1] in ("python", "bash"):
            pending = {"type": "code", "python": p[3], "python_lang": p[1]}
            blocks.append(pending)
        elif p[1] == "r":
            if pending is None:
                sys.exit("walkthrough.md: an r block has no python block before it")
            pending["r"] = p[3]
            pending = None
    for s in [{"blocks": intro}] + sections:
        for b in s["blocks"]:
            if b["type"] == "code" and "r" not in b:
                sys.exit("walkthrough.md: a python block has no r block after it")
    return {"title": title, "intro": intro, "sections": sections}


def outputs():
    pieces = parse(open(SOURCE, encoding="utf-8").read())
    return {
        OUT_IPYNB: json.dumps(build_ipynb(pieces), indent=1, ensure_ascii=False) + "\n",
        OUT_RMD: build_rmd(pieces),
        OUT_JSON: json.dumps(build_json(pieces), indent=1, ensure_ascii=False) + "\n",
    }


def run(lang, skip_create=False):
    for var in ("HEATREADY_USERNAME", "HEATREADY_KEY"):
        if not os.environ.get(var):
            sys.exit(f"--run needs {var} set")
    src = OUT_IPYNB if lang == "py" else OUT_RMD
    text = open(src, encoding="utf-8").read().replace(TRACTS_URL, TRACTS_LOCAL).replace(CENTERS_URL, CENTERS_LOCAL)
    if skip_create:
        text = without_step_6(lang, text)
    elif project_exists():
        sys.exit("my-first-project already exists under this account; delete it or use --skip-create")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, os.path.basename(src))
        open(path, "w", encoding="utf-8").write(text)
        try:
            if lang == "py":
                cmd = [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
                       "--ExecutePreprocessor.timeout=1800", "--output", os.path.join(tmp, "executed.ipynb"), path]
            else:
                # knitr runs every chunk without needing pandoc; RStudio's own Knit button renders HTML.
                cmd = ["Rscript", "-e", f"knitr::knit('{path}', output = '{tmp}/executed.md', quiet = TRUE)"]
            print("running:", " ".join(cmd[:4]), "...", flush=True)
            result = subprocess.run(cmd, cwd=tmp)  # knitr writes figure/ into the working directory
            if lang == "py" and result.returncode == 0:
                executed = json.load(open(os.path.join(tmp, "executed.ipynb"), encoding="utf-8"))
                for cell in executed["cells"]:
                    for o in cell.get("outputs", []):
                        if o.get("output_type") == "stream":
                            sys.stdout.write("".join(o["text"]))
                        elif "text/plain" in o.get("data", {}) and "image/png" not in o["data"]:
                            sys.stdout.write("".join(o["data"]["text/plain"]) + "\n")
            elif lang == "r" and result.returncode == 0:
                executed = open(os.path.join(tmp, "executed.md"), encoding="utf-8").read()
                sys.stdout.write("\n".join(l[3:] for l in executed.splitlines() if l.startswith("## ")) + "\n")
                if any(l.startswith("## Error") for l in executed.splitlines()):
                    print("an R chunk reported an error")
                    return 1
            return result.returncode
        finally:
            if not skip_create:
                cleanup()


def without_step_6(lang, text):
    """Drop step 6 (the only step that writes to the API) from a generated file."""
    marker = "## 6."
    if lang == "r":
        return text[: text.index(marker)]
    nb = json.loads(text)
    for i, cell in enumerate(nb["cells"]):
        source = "".join(cell["source"])
        if cell["cell_type"] == "markdown" and marker in source:
            cell["source"] = source[: source.index(marker)].splitlines(keepends=True)
            nb["cells"] = nb["cells"][: i + 1]
            return json.dumps(nb)
    sys.exit("step 6 heading not found")


def _client():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python", "src"))
    from heatready import HeatReadyClient
    return HeatReadyClient(username=os.environ["HEATREADY_USERNAME"], key=os.environ["HEATREADY_KEY"])


def project_exists():
    from heatready import HeatReadyError
    client = _client()
    try:
        client.get_project_status("my-first-project")
        return True
    except HeatReadyError as e:
        if e.code == "project_not_found":
            return False
        raise


def cleanup():
    """Delete the project step 6 made. run() refuses to start when it already existed, so this
    never removes a project the run did not create."""
    from heatready import HeatReadyError
    client = _client()
    try:
        print("cleanup:", client.delete_project("my-first-project").get("message"))
    except HeatReadyError as e:
        print("cleanup: nothing to delete (", e, ")")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--run", choices=["py", "r"])
    ap.add_argument("--skip-create", action="store_true", help="with --run, stop before step 6")
    args = ap.parse_args()
    if args.run:
        sys.exit(run(args.run, args.skip_create))
    stale = []
    for path, text in outputs().items():
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if current != text:
            stale.append(os.path.relpath(path, HERE))
            if not args.check:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w", encoding="utf-8").write(text)
    if args.check and stale:
        sys.exit("out of date with walkthrough.md: " + ", ".join(stale) + " (run walkthrough/build.py)")
    print("up to date" if not stale else "wrote " + ", ".join(stale))


if __name__ == "__main__":
    main()
