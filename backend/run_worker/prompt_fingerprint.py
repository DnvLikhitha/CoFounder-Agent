"""Fingerprint the repository source and declared inputs to a prompt renderer."""
import ast
from hashlib import sha256
from importlib.util import resolve_name
import json
from pathlib import Path

from backend.llm.messages import chat_messages
from backend.run_worker.workflow import LIVE_STEPS

ROOT = Path(__file__).resolve().parents[2]
# Research credentials are runtime inputs. Workflow dependencies are captured below as data,
# separately from the scheduler and other workflow versions declared in workflow.py.
BOUNDARIES = {"backend.config", "backend.run_worker.workflow"}


def imported_modules(tree, package):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package)
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)


def source_dependencies(roots):
    pending = set(roots)
    sources = {}
    while pending:
        name = pending.pop()
        if (name in sources or name in BOUNDARIES or name.split(".")[0] != "backend"):
            continue
        path = ROOT.joinpath(*name.split("."))
        package_file = path / "__init__.py"
        is_package = package_file.is_file()
        source_file = package_file if is_package else path.with_suffix(".py")
        if not source_file.is_file():
            continue  # An imported name can be a symbol rather than a module.
        source = source_file.read_text(encoding="utf-8-sig")
        sources[name] = source
        package = name if is_package else name.rpartition(".")[0]
        pending.update(imported_modules(ast.parse(source), package))
    return sources


def startup_v1_fingerprint(system_prompt, renderer):
    steps = {
        step_id: {
            "agent": f"{spec.agent.__module__}.{spec.agent.__qualname__}",
            "required": spec.required,
            "optional": spec.optional,
        }
        for step_id, spec in LIVE_STEPS.items()
    }
    roots = {renderer.__module__, chat_messages.__module__, *(spec.agent.__module__ for spec in LIVE_STEPS.values())}
    definition = {
        "renderer": f"{renderer.__module__}.{renderer.__qualname__}",
        "system_prompt": system_prompt,
        "steps": steps,
        "sources": source_dependencies(roots),
    }
    return sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
