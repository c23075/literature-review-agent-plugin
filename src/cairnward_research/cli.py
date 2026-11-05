"""`cairnward-research`: libraries, questions, reviews and references.

Commands run inside the plugin's sandbox: this program starts itself again through
`cairnward plugin run research`, so PDF parsing and model calls get the plugin contract's limits
when you run them by hand too. Only what the sandbox can't do stays out here: installing engines,
mirroring Drive through rclone, and moving downloaded PDFs into a library folder you own.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cairnward_research import EmbeddingDenied, LibraryError, Research, __version__
from cairnward_research.gateway import ServiceError
from cairnward_research.llm import ModelDenied
from cairnward_research.runtime import ENV_KEY, Runtime, load

PLUGIN = "research"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cairnward-research",
                                     description=__doc__.split("\n")[0])  # fmt: skip
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--standalone", action="store_true",
                        help="no Cairnward: none of the contract's protections apply")  # fmt: skip
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    sub.add_parser("serve", help="the MCP server (Cairnward starts this)")
    inst = sub.add_parser("install-plugin", help="write the manifest and add this to Cairnward")
    inst.add_argument("--yes", action="store_true", help="don't ask")
    imp = sub.add_parser("import", help="copy libraries and jobs from before the split, once")
    imp.add_argument("--from", dest="source", type=Path, help="the old Cairnward data folder")
    rs = sub.add_parser("research", help="research jobs")
    rs_sub = rs.add_subparsers(dest="research_command", metavar="ACTION", required=True)
    rv = rs_sub.add_parser("review", help="notes per paper + comparison table + references")
    rv.add_argument("library")
    rv.add_argument("--question", required=True, help="the review question")
    rv.add_argument("--style", choices=["apa", "ieee"], default="apa")
    rv.add_argument("--at", help="start later: HH:MM (local time) or an ISO date-time")
    rv.add_argument(
        "--files",
        nargs="+",
        metavar="PDF",
        help="review only these PDFs (in the library folder; indexed when the job starts)",
    )
    rv.add_argument("--files-from", type=Path, metavar="LIST",
                    help="like --files, read from a file with one path per line")  # fmt: skip
    rv.add_argument("--criteria", help="inclusion/exclusion criteria for screening, or @file")
    rv.add_argument("--no-screen", action="store_true",
                    help="read every paper in full (no title/abstract screening)")  # fmt: skip
    rw = rs_sub.add_parser("workflow", help="run a YAML workflow over a library")
    rw.add_argument("library")
    rw.add_argument("file", type=Path, help="the workflow (see examples/workflows/)")
    rw.add_argument("--question", help="filled in for {{question}}")
    rw.add_argument("--at", help="start later: HH:MM (local time) or an ISO date-time")
    eng = rs_sub.add_parser("engine", help="optional engines (PaperQA2, citeproc-js, pandoc)")
    eng.add_argument("action", choices=["install", "status", "export-lock"],
                     help="export-lock: copy the lock recorded on this machine into the "
                     "repository (to review and commit)")  # fmt: skip
    eng.add_argument("name", choices=["paperqa", "citeproc-js", "pandoc", "docling"])
    rsearch = rs_sub.add_parser("search", help="search OpenAlex, Semantic Scholar, arXiv, "
                                "Crossref, PubMed (opt-in per environment)")  # fmt: skip
    rsearch.add_argument("query")
    rsearch.add_argument("--env", help="environment (default: the library's, or litreview-online)")
    rsearch.add_argument("--library", help="use this library's environment")
    rsearch.add_argument("--source", action="append", dest="sources", metavar="NAME",
                         help="only this source (repeatable)")  # fmt: skip
    rsearch.add_argument("--limit", type=int, default=10, help="results per source (max 50)")
    rsearch.add_argument("--json", action="store_true")
    radd = rs_sub.add_parser("add", help="download open-access PDFs into a library and index them")
    radd.add_argument("library")
    radd.add_argument("ids", nargs="+", metavar="ID", help="doi:10.x/y, arxiv:2401.01234 or a DOI")
    rb = rs_sub.add_parser("ask", help="answer every question in a file (one per line)")
    rb.add_argument("library")
    rb.add_argument("file", type=Path)
    rb.add_argument("--at", help="start later: HH:MM (local time) or an ISO date-time")
    rb.add_argument(
        "--engine",
        choices=["lean", "paperqa"],
        default="lean",
        help="paperqa: the optional deep engine (slower; good for overnight)",
    )
    rb.add_argument("--evidence-k", type=int, default=10, help="paperqa: passages to weigh")
    rb.add_argument("--skip-summary", action="store_true", help="paperqa: no summaries")

    jb = sub.add_parser("jobs", help="research jobs: list, progress, results")
    jb_sub = jb.add_subparsers(dest="jobs_command", metavar="ACTION")
    jb_sub.add_parser("list", help="all jobs (default)")
    for name, text in (("show", "progress of one job"), ("cancel", "stop a job")):
        jb_sub.add_parser(name, help=text).add_argument("id")
    jres = jb_sub.add_parser("result", help="print a finished job's result")
    jres.add_argument("id")
    jres.add_argument("--bib", action="store_true", help="print the review's BibTeX instead")

    cite = sub.add_parser("cite", help="format references (APA 7, IEEE, or a .csl style)")
    cite.add_argument("file", type=Path, help="CSL-JSON (e.g. exported from Zotero)")
    cite.add_argument("--style", default="apa", help="apa (default), ieee, or a .csl file")
    cite.add_argument("--plain", action="store_true", help="no Markdown italics")
    cite.add_argument("--engine", choices=["auto", "builtin", "citeproc-js", "pandoc"],
                      help="CSL engine (default: citation_engine in research.toml)")  # fmt: skip

    lib = sub.add_parser("library", help="literature libraries: folders of PDFs, indexed")
    lib_sub = lib.add_subparsers(dest="library_command", metavar="ACTION", required=True)
    lc = lib_sub.add_parser("create", help="register a folder of PDFs as a library")
    lc.add_argument("name")
    lc.add_argument("folder", type=Path)
    lc.add_argument("--env", default="litreview-offline", help="environment (privacy, models)")
    lset = lib_sub.add_parser("set", help="parsing options: --parser docling, --metadata grobid")
    lset.add_argument("name")
    lset.add_argument(
        "--parser",
        choices=["basic", "docling"],
        help="text extraction (docling: layout, tables, OCR; optional engine)",
    )
    lset.add_argument(
        "--metadata",
        choices=["pdf", "grobid"],
        help="metadata and reference lists (grobid: your GROBID service)",
    )
    ldr = lib_sub.add_parser("drive", help="mirror PDFs from Google Drive (or any rclone remote), "
                             "read-only, then index")  # fmt: skip
    ldr.add_argument("name")
    ldr.add_argument("--remote", required=True, help="rclone remote and folder, e.g. gdrive:Papers")
    ldr.add_argument("--preview", action="store_true", help="only show what would be copied")
    ldr.add_argument(
        "--prune",
        action="store_true",
        help="delete local copies of PDFs no longer on the remote (drive/ only)",
    )
    ldr.add_argument("--no-index", action="store_true")
    lz = lib_sub.add_parser("zotero", help="copy PDFs and metadata from Zotero (read-only, "
                            "local API), then index")  # fmt: skip
    lz.add_argument("name", help="the library to fill")
    lz.add_argument("--collection", help="a Zotero collection (e.g. Thesis or Thesis/Chapter 2); "
                    "default: the whole Zotero library")  # fmt: skip
    lz.add_argument("--url", default="http://127.0.0.1:23119/api", help="Zotero's local API")
    lz.add_argument(
        "--storage", type=Path, help="Zotero's storage folder (default ~/Zotero/storage)"
    )
    lz.add_argument("--no-index", action="store_true", help="only copy; index later")
    lz.add_argument("--list-collections", action="store_true", help="show Zotero's collections")
    li = lib_sub.add_parser("index", help="parse, chunk and embed new or changed PDFs")
    li.add_argument("name")
    li.add_argument("--prune", action="store_true", help="forget PDFs no longer in the folder")
    li.add_argument("--rebuild", action="store_true", help="re-index everything from scratch")
    lib_sub.add_parser("list", help="libraries and their size")
    ls_ = lib_sub.add_parser("show", help="documents in a library")
    ls_.add_argument("name")
    lq = lib_sub.add_parser("search", help="find passages (vector + keyword search)")
    lq.add_argument("name")
    lq.add_argument("query")
    lq.add_argument("-k", type=int, default=5, help="number of passages (default 5)")
    lq.add_argument("--json", action="store_true")
    la = lib_sub.add_parser("ask", help="answer a question from the library, citing pages")
    la.add_argument("name")
    la.add_argument("question")
    la.add_argument("-k", type=int, default=8, help="passages to give the model (default 8)")
    la.add_argument("--effort", help="effort level (default: the environment's)")
    la.add_argument("--json", action="store_true")
    la.add_argument("--engine", choices=["lean", "paperqa"], default="lean",
                    help="lean (default) or paperqa (optional deep engine; slower)")  # fmt: skip
    la.add_argument("--evidence-k", type=int, default=10, help="paperqa: passages to weigh")
    la.add_argument("--skip-summary", action="store_true",
                    help="paperqa: no per-passage summaries (faster)")  # fmt: skip
    lrf = lib_sub.add_parser("refs", help="CSL-JSON of the library's papers (from PDF metadata)")
    lrf.add_argument("name")
    lk = lib_sub.add_parser("check", help="check a draft's quotations and references")
    lk.add_argument("name")
    lk.add_argument("draft", type=Path, help="a Markdown or text file")
    lk.add_argument("--json", action="store_true")
    lr = lib_sub.add_parser("remove", help="delete a library's index (the PDFs stay)")
    lr.add_argument("name")
    for action, text in (
        ("lock", "encrypt a library's index with a passphrase (the PDFs stay)"),
        ("unlock", "remove that lock and restore the index"),
        ("recover", "forgotten passphrase: set a new one with the recovery key"),
    ):
        lib_sub.add_parser(action, help=text).add_argument("name")  # fmt: skip

    jb_run = jb_sub.add_parser("run", help="run queued jobs here until they're done")
    jb_run.add_argument("--forever", action="store_true", help="keep waiting for new jobs")
    return parser


def _log(msg: str) -> None:
    print(f"cairnward-research: {msg}", file=sys.stderr)


# ------------------------------------------------------------------ outside the sandbox


def _library_environment(rt: Runtime, name: str) -> str | None:
    try:
        with Research.open(rt.paths) as research:
            return research.find(name).environment
    except (LibraryError, ValueError):
        return None


def _environment_for(rt: Runtime, args: argparse.Namespace) -> str | None:
    if getattr(args, "env", None):
        return str(args.env)
    for attr in ("library", "name"):
        value = getattr(args, attr, None)
        if value and (env := _library_environment(rt, str(value))):
            return env
    if args.command == "jobs" and getattr(args, "id", None):
        return _job_environment(rt, args.id)
    return None


def _job_environment(rt: Runtime, job_id: str) -> str | None:
    from cairnward_research.jobs import JobStore

    try:
        library = JobStore(rt.paths.data_dir).load(job_id).params.get("library")
    except (OSError, ValueError, KeyError):
        return None
    return _library_environment(rt, str(library)) if library else None


def _copy_in(rt: Runtime, argv: list[str], args: argparse.Namespace) -> list[str]:
    """Files you name on the command line may be outside what the plugin can read: they go in
    through its data folder."""
    inbox = rt.paths.data_dir / "incoming" / "args"
    out = list(argv)
    named: list[tuple[str, Path]] = []
    for attr in ("file", "draft", "files_from"):
        value = getattr(args, attr, None)
        if value:
            named.append((str(value), Path(value)))
    criteria = getattr(args, "criteria", None)
    if criteria and criteria.startswith("@"):
        named.append((criteria, Path(criteria[1:])))
    for raw, path in named:
        inbox.mkdir(parents=True, exist_ok=True)
        dest = inbox / path.name
        shutil.copyfile(path, dest)
        replacement = f"@{dest}" if raw.startswith("@") else str(dest)
        out = [replacement if a == raw else a for a in out]
    return out


def _program() -> Path:
    return Path(sys.prefix) / "bin" / "cairnward-research"


def _in_sandbox(environment: str | None, argv: list[str]) -> int:
    exe = shutil.which("cairnward")
    if exe is None:
        _log(
            "Cairnward isn't on PATH: run `uv tool install .` in its folder, or use --standalone "
            "(no protections)"
        )
        return 2
    program = [str(_program())]
    command = [exe, "plugin", "run", *(["--env", environment] if environment else []), PLUGIN]
    return subprocess.run([*command, "--", *program, *argv], check=False).returncode  # noqa: S603


def _move_incoming(rt: Runtime, library: str) -> int:
    """The sandbox can't write to your library folder: downloads wait in the data folder."""
    inbox = rt.paths.data_dir / "incoming" / library
    if not inbox.is_dir():
        return 0
    with Research.open(rt.paths) as research:
        folder = research.get(library).folder
    moved = 0
    for path in sorted(p for p in inbox.rglob("*") if p.is_file()):
        dest = folder / path.relative_to(inbox)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, dest)
        moved += 1
    shutil.rmtree(inbox, ignore_errors=True)
    return moved


def _allow_folder(folder: Path) -> int:
    exe = shutil.which("cairnward")
    if exe is None:
        return 0
    command = [exe, "plugin", "allow-read", PLUGIN, str(folder.expanduser().resolve())]
    return subprocess.run(command, check=False).returncode  # noqa: S603


def _outside(rt: Runtime, args: argparse.Namespace, argv: list[str]) -> int:
    """Run in the sandbox, then do what only this side can."""
    env = _environment_for(rt, args)
    if args.command == "library" and args.library_command == "create":
        if (code := _allow_folder(args.folder)) != 0:
            return code
        argv = [str(a) if a != str(args.folder) else str(args.folder.expanduser().resolve())
                for a in argv]  # fmt: skip
    code = _in_sandbox(env, _copy_in(rt, argv, args))
    downloads = ((args.command == "research" and args.research_command == "add")
                 or (args.command == "library" and args.library_command == "zotero"))  # fmt: skip
    if code == 0 and downloads:
        library = args.library if args.command == "research" else args.name
        if _move_incoming(rt, library) and not getattr(args, "no_index", False):
            print("indexing ...")
            return _in_sandbox(env, ["library", "index", library])
    return code


def _engine(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research import csl
    from cairnward_research.engines import docling, locks, paperqa

    if args.name == "citeproc-js":
        if args.action == "install":
            try:
                lib = csl.install_citeproc_js(rt.paths)
            except (csl.CslError, subprocess.CalledProcessError) as exc:
                _log(str(exc))
                return 1
            print(f"citeproc-js installed ({lib}); with citation_engine = \"auto\" it now formats "
                  "references")  # fmt: skip
            return 0
        found = csl.citeproc_js(rt.paths)
        print(f"citeproc-js: {'installed (' + str(found) + ')' if found else 'not installed'}")
        return 0 if found else 1
    if args.action == "export-lock":
        if args.name != "docling":
            _log("only Docling's lock is recorded on install")
            return 2
        try:
            dest = locks.export("docling", docling.engine_dir(rt.paths) / "requirements.lock.txt")
        except OSError as exc:
            _log(str(exc))
            return 1
        print(f"wrote {dest}\nReview it, then commit it: installs on {locks.platform_tag()} will "
              "use it instead of resolving")  # fmt: skip
        return 0
    if args.name == "docling":
        if args.action == "install":
            print("Installing Docling with CPU-only PyTorch and its models (about 3 GB).")
            try:
                record = docling.install(rt.paths)
            except (docling.DoclingError, subprocess.CalledProcessError) as exc:
                _log(str(exc))
                return 1
            print(f"Docling installed from the {record['lock_source']} lock (sha256 "
                  f"{record['lock_sha256'][:16]}...), models sha256 "
                  f"{record['models_sha256'][:16]}...")  # fmt: skip
            return 0
        exe = docling.python(rt.paths)
        problems = docling.verify(rt.paths) if exe else []
        print(f"docling: {'installed' if exe else 'not installed'}"
              + "".join(f"; {p}" for p in problems))  # fmt: skip
        return 0 if exe and not problems else 1
    if args.name == "pandoc":
        found_pandoc = csl.pandoc()
        if args.action == "install":
            print("pandoc isn't installed by this package: use your package manager (e.g. sudo "
                  "apt install pandoc); version 2.11 or newer")  # fmt: skip
        print(f"pandoc: {'found (' + found_pandoc + ')' if found_pandoc else 'not found'}")
        return 0 if found_pandoc else 1
    if args.action == "install":
        print("Installing PaperQA2 (about 250 MB, hash-checked) in its own environment...")
        paperqa.install(rt.paths)
        return 0
    exe = paperqa.python(rt.paths)
    print(f"paperqa: {'installed (' + str(exe) + ')' if exe else 'not installed'}")
    return 0 if exe else 1


def _drive(rt: Runtime, args: argparse.Namespace) -> int:
    """rclone can't go through the fetch service. Cairnward runs it outside the sandbox, with
    its traffic through egress in the library's environment, so that policy applies."""
    from cairnward_research import drive

    with Research.open(rt.paths) as research:
        lib = research.get(args.name)
    exe = shutil.which("cairnward")
    if exe is None and not args.standalone:
        _log("Cairnward isn't on PATH: run `uv tool install .` in its folder")
        return 2
    prefix = None if args.standalone else [exe or "", "plugin", "helper", "--env",
                                           lib.environment, PLUGIN, "--"]  # fmt: skip
    run = drive.make_runner(None, prefix=prefix)
    try:
        for warning in drive.check_remote(args.remote, run):
            print(f"note: {warning}")
        local = lib.folder / "drive"
        if args.preview:
            todo = drive.plan(drive.listing(args.remote, run), local)
        else:
            todo = drive.mirror(args.remote, local, prune=args.prune, run=run)
    except drive.DriveError as exc:
        _log(str(exc))
        return 1
    counts = {k: len(v) for k, v in todo.items()}
    verb = "would copy" if args.preview else "copied"
    print(f"Drive: {verb} {counts['new']} new and {counts['changed']} changed PDF(s); "
          f"{counts['unchanged']} unchanged; {counts['gone']} no longer on the remote"
          + (" (deleted here)" if args.prune and not args.preview else ""))  # fmt: skip
    for rel in (todo["new"] + todo["changed"])[:20]:
        print(f"  {rel}")
    if args.preview or args.no_index or not (counts["new"] or counts["changed"]):
        return 0
    return main_inner(["library", "index", args.name], standalone=args.standalone)


MANIFEST_HOSTS = ["api.openalex.org", "api.semanticscholar.org", "export.arxiv.org", "arxiv.org",
                  "api.crossref.org", "eutils.ncbi.nlm.nih.gov", "doi.org",
                  "www.ncbi.nlm.nih.gov", "europepmc.org"]  # fmt: skip


# Cairnward doesn't ship these: the plugin brings the environments it runs in. Yours are kept.
ENVIRONMENTS = {
    "litreview-offline": """\
description = "Literature review with no network"
effort_default = "high"

[privacy]
network = "off"
hosted_backends = "deny"
""",
    "litreview-online": """\
description = "Literature review with academic APIs (approval per new host)"
effort_default = "high"

[privacy]
network = "ask"
network_allow_hosts = [
    "export.arxiv.org",
    "api.semanticscholar.org",
    "api.openalex.org",
    "eutils.ncbi.nlm.nih.gov",
    "api.crossref.org",
]
""",
}


def _write_environments(config_dir: Path) -> list[str]:
    """Add the plugin's environments to Cairnward's configuration, returning those written."""
    folder = config_dir / "environments"
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in ENVIRONMENTS.items():
        path = folder / f"{name}.toml"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            written.append(name)
    return written


def _install_plugin(rt: Runtime, args: argparse.Namespace) -> int:
    import cairnward_research

    exe = shutil.which("cairnward")
    if exe is None:
        _log("Cairnward isn't on PATH: run `uv tool install .` in its folder")
        return 2
    paths = subprocess.run([exe, "config", "paths"], capture_output=True,  # noqa: S603
                           text=True, check=True).stdout  # fmt: skip
    config_dir = next(Path(line.split(None, 1)[1]) for line in paths.splitlines()
                      if line.startswith("config"))  # fmt: skip
    for name in _write_environments(config_dir):
        print(f"added environment {name} to {config_dir / 'environments'}")
    code_dir = Path(cairnward_research.__file__).resolve().parents[1]
    program = _program()
    lines = [
        'name = "research"',
        f'version = "{__version__}"',
        'description = "Literature libraries and reviews"',
        f"command = {json.dumps([str(program), 'serve'])}",
        f'pin_dir = "{code_dir}"',
        f"fetch_hosts = {json.dumps(MANIFEST_HOSTS)}",
        'environments = ["litreview-offline", "litreview-online"]',
        "idle_stop_minutes = 0",
        "call_timeout_s = 3600",
        'default_tool = "allow"',
        "",
        "[permissions]",
        "read = []",
    ]
    if rt.settings.grobid_url or rt.settings.zotero_url:
        from urllib.parse import urlsplit

        hosts = [f"{u.hostname}:{u.port}" for u in map(urlsplit, filter(None, (
            rt.settings.grobid_url, rt.settings.zotero_url)))]  # fmt: skip
        lines.append(f"network = {json.dumps(hosts)}")
    manifest = rt.paths.data_dir / "plugin.toml"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [exe, "plugin", "add", str(manifest)] + (["--yes"] if args.yes else [])
    code = subprocess.run(command, check=False).returncode  # noqa: S603
    settings = rt.paths.data_dir / "research.toml"
    if code == 0 and not settings.exists():
        from cairnward_research.sources import SOURCES

        sources = ", ".join(json.dumps(s) for s in SOURCES)
        settings.write_text(f"[sources]\nlitreview-online = [{sources}]\n", encoding="utf-8")
    return code


def _import(rt: Runtime, args: argparse.Namespace) -> int:
    """research.db, jobs, library options and locked libraries' files. A locked library's key
    stays with the conversations' keys, so it opens with the same passphrase."""
    source = args.source
    if source is None:
        base = os.environ.get("CAIRNWARD_DATA_DIR") or os.environ.get("XDG_DATA_HOME") or (
            str(Path.home() / ".local" / "share"))  # fmt: skip
        source = Path(base) if os.environ.get("CAIRNWARD_DATA_DIR") else Path(base) / "cairnward"
    data = rt.paths.data_dir
    if (data / "research.db").exists():
        _log(f"{data} already has a library database: nothing copied")
        return 1
    if not (source / "research.db").exists():
        _log(f"no research.db in {source}")
        return 1
    from cairnward_research.db import make_engine

    copied = []
    old = make_engine(source / "research.db", vectors=True)
    with old.connect() as conn:  # a consistent copy, even with the old file in WAL mode
        conn.exec_driver_sql("VACUUM INTO ?", (str(data / "research.db"),))
    old.dispose()
    copied.append("research.db")
    for name in ("jobs", "library-locks", "grobid", "research_cache"):
        if (source / name).is_dir():
            shutil.copytree(source / name, data / name, dirs_exist_ok=True)
            copied.append(name)
    if (source / "library-options.json").exists():
        shutil.copy2(source / "library-options.json", data / "library-options.json")
        copied.append("library-options.json")
    print(f"copied {', '.join(copied)} to {data}. The originals are still in {source}.")
    with Research.open(rt.paths) as research:
        for lib, _docs, _chunks in research.list_libraries():
            code = _allow_folder(lib.folder)
            if code:
                return code
    print("Next: restart `cairnward serve`, then check with: cairnward-research library list")
    return 0


# ------------------------------------------------------------------ inside the sandbox


def _research_search(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.online import Online, OnlineError

    environment = rt.environment or args.env or "litreview-online"
    try:
        out = asyncio.run(Online(rt).search(environment, args.query, sources=args.sources,
                                            limit=args.limit))  # fmt: skip
    except OnlineError as exc:
        _log(str(exc))
        return 1
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    for name, rep in out["sources"].items():
        if "error" in rep:
            print(f"  {name}: {rep['error']}", file=sys.stderr)
    for n, r in enumerate(out["records"], 1):
        who = ", ".join(r["authors"][:3]) + (" et al." if len(r["authors"]) > 3 else "")
        ident = (f"doi:{r['doi']}" if r["doi"] else f"arxiv:{r['arxiv']}" if r["arxiv"]
                 else f"{r['source']}:{r['id']}")  # fmt: skip
        extra = " · ".join(x for x in (
            "open-access PDF" if r["pdf_url"] else "", f"cited {r['cited_by']}"
            if r["cited_by"] is not None else "", r["source"]) if x)  # fmt: skip
        print(f"{n:2}. {who} ({r['year'] or 'n.d.'}). {r['title']}"
              + (f". {r['venue']}" if r["venue"] else ""))  # fmt: skip
        print(f"    {ident}  [{extra}]")
    if not out["records"]:
        print("no results")
    print(f"(environment {environment}; add papers with: cairnward-research research add "
          "<library> <id> ...)", file=sys.stderr)  # fmt: skip
    return 0


def _research_add(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.online import Online, OnlineError

    with Research.open(rt.paths) as research:
        environment = research.get(args.library).environment
    try:
        items = asyncio.run(Online(rt).fetch(environment, args.ids))
    except OnlineError as exc:
        _log(str(exc))
        return 1
    target = rt.paths.data_dir / "incoming" / args.library / "online"
    saved = 0
    for item in items:
        if "error" in item:
            print(f"  {item['id']}: {item['error']}", file=sys.stderr)
            continue
        target.mkdir(parents=True, exist_ok=True)
        pdf = target / Path(item["filename"]).name
        pdf.write_bytes(base64.b64decode(item["pdf_b64"]))
        pdf.with_name(pdf.name + ".csl.json").write_text(json.dumps(item["csl"], indent=1),
                                                         encoding="utf-8")  # fmt: skip
        print(f"  got {pdf.name}: {item['title'][:70]}")
        saved += 1
    return 0 if saved else 1


def parse_at(value: str, now: Any = None) -> str:
    from datetime import datetime, timedelta

    now = now or datetime.now().astimezone()
    if ":" in value and "T" not in value and len(value) <= 5:
        hour, minute = value.split(":")
        when = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        return str(when.isoformat())
    return str(datetime.fromisoformat(value).astimezone().isoformat())


def _job_line(j: dict[str, Any]) -> str:
    eta = f", about {j['eta_s'] // 60} min left" if j.get("eta_s") else ""
    when = f", starts {j['not_before']}" if j.get("not_before") and j["status"] == "queued" else ""
    engine = " (paperqa)" if j.get("engine") == "paperqa" else ""
    return (f"{j['id']}  {j['kind']:6} {j['status']:9} {j['done']}/{j['total']}  "
            f"{j['library']}{engine}{when}{eta}")  # fmt: skip


def _run_jobs(rt: Runtime, forever: bool = False) -> int:
    from cairnward_research import service

    async def go() -> None:
        job_runner = service.runner(rt, log=print)
        if forever:
            await job_runner.run_forever()
        while (job := await asyncio.to_thread(job_runner._next)) is not None:
            await job_runner.run(job)

    with service.runner_lock(rt.paths.data_dir, rt.environment) as ours:
        if not ours:
            print("the plugin's server is already running jobs here; it will do this one")
            return 0
        asyncio.run(go())
    return 0


def _submit(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.jobs import ask_job, library_files, review_job, workflow_job
    from cairnward_research.service import runner
    from cairnward_research.workflow import WorkflowError, parse_workflow

    start = parse_at(args.at) if args.at else None
    with Research.open(rt.paths) as research:
        lib = research.get(args.library)
    not_found: list[str] = []
    if args.research_command == "workflow":
        try:
            spec = parse_workflow(args.file.read_text(encoding="utf-8"))
        except WorkflowError as exc:
            _log(str(exc))
            return 1
        job = workflow_job(args.library, spec.model_dump(), args.question, not_before=start)
    elif args.research_command == "review":
        criteria = args.criteria
        if criteria and criteria.startswith("@"):
            criteria = Path(criteria[1:]).read_text(encoding="utf-8").strip()
        files = list(args.files or [])
        if args.files_from:
            files += [x.strip() for x in args.files_from.read_text(
                encoding="utf-8").splitlines() if x.strip()]  # fmt: skip
        chosen = None
        if files:
            chosen = library_files(lib.folder, files)
            not_found = [f for f in chosen if not (lib.folder / f).is_file()]
        job = review_job(args.library, args.question, args.style, files=chosen, criteria=criteria,
                         screen=not args.no_screen, not_before=start)  # fmt: skip
    else:
        questions = args.file.read_text(encoding="utf-8").splitlines()
        job = ask_job(args.library, questions, engine=args.engine, evidence_k=args.evidence_k,
                      skip_summary=args.skip_summary, not_before=start)  # fmt: skip
    runner(rt).submit(job)
    print(f"queued: {_job_line(job.summary())}")
    if not_found:
        print("not in the library folder yet (reviewed only if there when the job starts): "
              + ", ".join(not_found))  # fmt: skip
    if start:
        print("it runs while the plugin's server is up (a client has used its tools), or with: "
              "cairnward-research jobs run --forever")  # fmt: skip
        return 0
    return _run_jobs(rt)


def _jobs(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.jobs import JobStore

    store = JobStore(rt.paths.data_dir)
    action = args.jobs_command or "list"
    if action == "run":
        return _run_jobs(rt, args.forever)
    if action == "list":
        jobs = store.all()
        if not jobs:
            print("no research jobs")
        for j in jobs:
            print(_job_line(j.summary()))
        return 0
    try:
        job = store.load(args.id)
    except (OSError, ValueError, KeyError):
        _log(f"no job {args.id}")
        return 1
    if action == "cancel":
        from cairnward_research.service import runner

        print("cancelled" if runner(rt).cancel(args.id) else "already finished")
        return 0
    if action == "result":
        path = store.result_path(job.id)
        if not path.exists():
            print(f"not finished yet: {_job_line(job.summary())}", file=sys.stderr)
            return 1
        if args.bib:
            path = path.with_name("references.bib")
            if not path.exists():
                print("this job has no BibTeX (only reviews do)", file=sys.stderr)
                return 1
        sys.stdout.write(path.read_text(encoding="utf-8"))
        return 0
    print(_job_line(job.summary()))
    for st in job.steps:
        mark = {"done": "ok ", "failed": "BAD", "pending": "   "}[st.status]
        took = f" ({st.seconds:.0f}s)" if st.seconds else ""
        err = f"  {st.error}" if st.error else ""
        label = st.params.get("title") or st.params.get("question") or ""
        print(f"  [{mark}] {st.name}: {label[:70]}{took}{err}")
    if job.status in ("done", "failed"):
        print(f"result: {store.result_path(job.id)}")
    return 0


def _ask_passphrase(prompt: str) -> str:
    import getpass

    return getpass.getpass(prompt)


def _library_lock(rt: Runtime, research: Research, args: argparse.Namespace, action: str) -> int:
    from cairnward_research.crypto import DecryptionError
    from cairnward_research.gateway import KeyService
    from cairnward_research.lock import item_id, lock_library, unlock_library

    name, data, keys = args.name, rt.paths.data_dir, KeyService(rt)
    lib = research.find(name)
    try:
        if action == "unlock":
            unlock_library(keys, research, data, name, _ask_passphrase("Passphrase: "))
            print(f"removed the lock from library '{name}'")
            return 0
        identity = _ask_passphrase("Recovery key (AGE-SECRET-KEY-1...): ") if (
            action == "recover") else None  # fmt: skip
        first = _ask_passphrase("New passphrase: ")
        if _ask_passphrase("Again: ") != first:
            print("the passphrases differ: nothing changed", file=sys.stderr)
            return 1
        if identity is not None:
            keys.recover(item_id(name), identity, first)
            print(f"library '{name}' has a new passphrase (still locked)")
        else:
            lock_library(keys, research, data, name, first)
            print(f"locked library '{name}': only the passphrase opens it.")
            print(f"Your PDFs in {lib.folder} aren't encrypted, and older backups still hold "
                  "the index.")  # fmt: skip
    except (ServiceError, DecryptionError) as exc:
        _log(str(exc))
        return 1
    return 0


def _library_ask(rt: Runtime, research: Research, args: argparse.Namespace) -> int:
    from cairnward_research.ask import run_ask

    research.get(args.name)  # fail early on a wrong name
    if args.engine == "paperqa":
        from cairnward_research.engines import paperqa

        print("Asking with PaperQA2 (slow on a CPU: several model calls per question)...",
              file=sys.stderr)  # fmt: skip
        try:
            answer = paperqa.ask(rt, args.name, args.question, effort=args.effort,
                                 evidence_k=args.evidence_k,
                                 skip_summary=args.skip_summary)  # fmt: skip
        except paperqa.EngineError as exc:
            _log(str(exc))
            return 1
    else:
        print("Asking (this can take a few minutes on a CPU)...", file=sys.stderr)
        answer = asyncio.run(run_ask(rt, args.name, args.question, k=args.k, effort=args.effort))
    if args.json:
        print(json.dumps(answer.as_dict(), indent=2))
    else:
        sys.stdout.write(answer.render())
    return 0


def _library_zotero(rt: Runtime, research: Research, args: argparse.Namespace) -> int:
    from cairnward_research.zotero import DEFAULT_URL, Zotero, ZoteroError, import_items

    try:
        zotero = Zotero(args.url or rt.settings.zotero_url or DEFAULT_URL, storage=args.storage)
    except ZoteroError as exc:
        _log(str(exc))
        return 1
    try:
        if args.list_collections:
            for c in sorted(zotero.collections(), key=lambda c: c["name"].lower()):
                print(c["name"])
            return 0
        research.get(args.name)
        report = import_items(zotero, rt.paths.data_dir / "incoming" / args.name, args.collection)
    except ZoteroError as exc:
        _log(str(exc))
        return 1
    finally:
        zotero.close()
    print(f"Zotero: {report['items']} items, {report['copied']} PDFs copied, "
          f"{report['unchanged']} unchanged, {len(report['no_pdf'])} without a PDF")  # fmt: skip
    for title in report["no_pdf"][:10]:
        print(f"  no PDF: {title}")
    return 0


def _library(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.embedder import GatewayEmbedder

    cmd = args.library_command
    with Research.open(rt.paths) as research:
        if cmd == "create":
            lib = research.create(args.name, args.folder, args.env)
            print(f"Created library '{lib.name}' for {lib.folder} "
                  f"(environment '{lib.environment}').")  # fmt: skip
            print(f"Next: cairnward-research library index {lib.name}")
            return 0
        if cmd == "list":
            for lib, n_docs, n_chunks in research.list_libraries():
                if lib.locked:
                    print(f"{lib.name:20} locked  [{lib.environment}]  {lib.folder}")
                    continue
                model = lib.embedding_model or "not indexed"
                print(f"{lib.name:20} {n_docs:5} docs {n_chunks:7} chunks  [{lib.environment}] "
                      f"{model}  {lib.folder}")  # fmt: skip
            return 0
        if cmd == "show":
            for d in research.documents(args.name):
                title = (d.title or "")[:60]
                print(f"{d.status:8} {d.pages or 0:4}p {d.chunks:4}c  {d.path}  {title}")
                if d.error and d.status != "indexed":
                    print(f"{'':20}{d.error}")
            return 0
        if cmd == "remove":
            research.remove(args.name)
            if rt.under_contract:
                from cairnward_research.gateway import KeyService
                from cairnward_research.lock import item_id

                KeyService(rt).remove_item(item_id(args.name))
            print(f"Removed the index of '{args.name}' (your PDFs are untouched).")
            return 0
        if cmd in ("lock", "unlock", "recover"):
            return _library_lock(rt, research, args, cmd)
        if cmd == "ask":
            return _library_ask(rt, research, args)
        if cmd == "zotero":
            return _library_zotero(rt, research, args)
        if cmd == "set":
            from cairnward_research.parsing import set_options

            research.get(args.name)
            opts = set_options(rt.paths.data_dir, args.name, parser=args.parser,
                               metadata=args.metadata)  # fmt: skip
            print(f"{args.name}: parser {opts['parser']}, metadata {opts['metadata']}")
            if opts["metadata"] == "grobid" and not rt.settings.grobid_url:
                print('note: set grobid_url = "http://127.0.0.1:8070" in research.toml')
            print(f"Re-read the PDFs with: cairnward-research library index {args.name} --rebuild")
            return 0
        if cmd == "refs":
            from cairnward_research import grobid
            from cairnward_research.cite import from_documents

            docs = [d for d in research.documents(args.name) if d.status == "indexed"]
            refs = from_documents(docs, research.get(args.name).folder,
                                  lambda rel: grobid.load(rt.paths.data_dir, args.name,
                                                          rel)[0])  # fmt: skip
            print(json.dumps(refs, indent=2, ensure_ascii=False))
            return 0
        if cmd == "check":
            from cairnward_research.check import check_draft

            report = check_draft(research, args.name, args.draft.read_text(encoding="utf-8"))
            if args.json:
                print(json.dumps(report.as_dict(), indent=2))
                return 1 if report.problems else 0
            for q in report.quotes:
                mark = "ok " if q.ok else "BAD"
                print(f'[{mark}] quote "{q.quote[:70]}" '
                      + (f"-> {q.where}" if q.where else "not found in the library"))  # fmt: skip
            for r in report.references:
                mark = {"in_library": "ok ", "doi_unverified": "doi", "not_found": "BAD"}[r.status]
                print(f"[{mark}] reference {r.entry[:70]}" + (f" -> {r.match}" if r.match else ""))
            if not report.quotes and not report.references:
                print("no quotations or References section found")
            print(f"{report.problems} problem(s)")
            return 1 if report.problems else 0
        lib = research.get(args.name)
        embedder = GatewayEmbedder(rt, environment=lib.environment)
        if cmd == "index":
            from cairnward_research.parsing import hooks

            parse_many, enrich = hooks(rt, args.name, lib.environment)
            result = asyncio.run(research.index(args.name, embedder, prune=args.prune,
                                                rebuild=args.rebuild, progress=print,
                                                parse_many=parse_many, enrich=enrich))  # fmt: skip
            print(f"\nIndexed '{args.name}': {result.added} added, {result.updated} updated, "
                  f"{result.unchanged} unchanged, {result.no_text} without text, "
                  f"{result.failed} failed, {result.missing} missing; "
                  f"{result.chunks} chunks in {result.seconds:.0f}s.")  # fmt: skip
            return 1 if result.failed else 0
        hits = asyncio.run(research.search(args.name, args.query, embedder, k=args.k))
    if args.json:
        from dataclasses import asdict

        print(json.dumps([asdict(h) for h in hits], indent=2))
        return 0
    for i, h in enumerate(hits, 1):
        print(f"{i}. {h.title or h.path} ({h.pages})  score {h.score}")
        print(f"   {h.text[:300]}{'…' if len(h.text) > 300 else ''}\n")
    return 0


def _cite(rt: Runtime, args: argparse.Namespace) -> int:
    from cairnward_research.cite import CiteError, format_references, load_items

    engine = args.engine or rt.settings.citation_engine
    try:
        entries, used = format_references(load_items(args.file), args.style, md=not args.plain,
                                          engine=engine, paths=rt.paths)  # fmt: skip
    except (CiteError, ValueError, OSError) as exc:
        _log(str(exc))
        return 1
    print("\n\n".join(entries))
    print(f"(formatted with {used})", file=sys.stderr)
    return 0


def _inside(rt: Runtime, args: argparse.Namespace) -> int:
    if args.command == "library":
        return _library(rt, args)
    if args.command == "jobs":
        return _jobs(rt, args)
    if args.command == "cite":
        return _cite(rt, args)
    if args.research_command == "search":
        return _research_search(rt, args)
    if args.research_command == "add":
        return _research_add(rt, args)
    return _submit(rt, args)


def main_inner(argv: list[str], *, standalone: bool = False) -> int:
    args = build_parser().parse_args(argv)
    args.standalone = standalone or args.standalone
    rt = load()
    if args.command == "serve":
        from cairnward_research.server import main as serve

        serve()
        return 0
    if args.command == "install-plugin":
        return _install_plugin(rt, args)
    if args.command == "import":
        return _import(rt, args)
    if args.command == "research" and args.research_command == "engine":
        return _engine(rt, args)
    if args.command == "library" and args.library_command == "drive":
        return _drive(rt, args)
    if not args.standalone and not os.environ.get(ENV_KEY):
        return _outside(rt, args, [a for a in argv if a != "--standalone"])
    try:
        return _inside(rt, args)
    except (LibraryError, EmbeddingDenied, ModelDenied, ServiceError, ValueError) as exc:
        _log(str(exc))
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return main_inner(list(sys.argv[1:] if argv is None else argv))
