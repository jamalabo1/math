#!/usr/bin/env python3
"""Generate a static, browser-viewable catalog from every PDF in a repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape


SITE_DIR = Path(__file__).resolve().parent
IGNORED_PARTS = {".git", ".github", ".venv", "dist", "site"}


@dataclass(frozen=True)
class PdfEntry:
    title: str
    description: str
    section_key: str
    section: str
    source: Path
    asset_url: str
    viewer_url: str
    size: str


def display_name(value: str) -> str:
    """Turn a filename or directory name into a readable heading."""
    return value.replace("_", " ").replace("-", " ").strip().title()


def format_size(byte_count: int) -> str:
    size = float(byte_count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def url_path(*parts: str) -> str:
    """Join and URL-encode path components while preserving slash boundaries."""
    normalized = [part.strip("/") for part in parts if part.strip("/")]
    return "/" + "/".join(
        quote(component, safe="")
        for part in normalized
        for component in part.split("/")
    )


def find_pdfs(source: Path, output: Path) -> list[Path]:
    output = output.resolve()
    results: list[Path] = []

    for path in source.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        if output == path.resolve() or output in path.resolve().parents:
            continue
        if any(part in IGNORED_PARTS for part in path.relative_to(source).parts):
            continue
        results.append(path)

    return sorted(results, key=lambda path: path.relative_to(source).as_posix().lower())


def load_config() -> dict[str, object]:
    config = json.loads((SITE_DIR / "config.json").read_text(encoding="utf-8"))
    topic_order = config.get("topic_order", [])
    if not isinstance(topic_order, list) or any(
        not isinstance(topic, str) for topic in topic_order
    ):
        raise ValueError("config.json topic_order must be a list of directory names")

    pdf_order = config.get("pdf_order", {})
    if not isinstance(pdf_order, dict) or any(
        not isinstance(topic, str)
        or not isinstance(paths, list)
        or any(not isinstance(path, str) for path in paths)
        for topic, paths in pdf_order.items()
    ):
        raise ValueError(
            "config.json pdf_order must map topic names to lists of PDF paths"
        )
    return config


def topic_sort_key(topic: str, topic_order: list[str]) -> tuple[int, object]:
    try:
        return (0, topic_order.index(topic))
    except ValueError:
        return (1, topic.lower())


def pdf_sort_key(entry: PdfEntry, pdf_order: list[str]) -> tuple[int, object]:
    source = entry.source.as_posix()
    try:
        return (0, pdf_order.index(source))
    except ValueError:
        return (1, entry.title.lower())


def load_pdf_metadata(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    metadata = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"{path} must contain a JSON object")

    for pdf_path, values in metadata.items():
        if not isinstance(values, dict):
            raise ValueError(f"Metadata for {pdf_path!r} must be a JSON object")
        unsupported = set(values) - {"title", "description"}
        if unsupported:
            raise ValueError(
                f"Unsupported metadata for {pdf_path!r}: {', '.join(sorted(unsupported))}"
            )
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError(f"Metadata values for {pdf_path!r} must be strings")

    return metadata


def build_site(
    source: Path,
    output: Path,
    base_url: str,
    analytics_id: str,
    metadata_path: Optional[Path] = None,
) -> int:
    source = source.resolve()
    output = output.resolve()
    base_url = "/" + base_url.strip("/") if base_url.strip("/") else ""

    if output == source or output in source.parents:
        raise ValueError("Output directory cannot be the source directory or its parent")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    environment = Environment(
        loader=FileSystemLoader(SITE_DIR / "templates"),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    config = load_config()
    metadata = load_pdf_metadata(metadata_path or SITE_DIR / "pdf_metadata.json")
    entries: list[PdfEntry] = []

    for pdf in find_pdfs(source, output):
        relative = pdf.relative_to(source)
        overrides = metadata.get(relative.as_posix(), {})
        asset_relative = Path("assets") / "pdfs" / relative
        destination = output / asset_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, destination)

        viewer_id = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16]
        entry = PdfEntry(
            title=overrides.get("title") or display_name(relative.stem),
            description=overrides.get("description", ""),
            section_key=relative.parent.as_posix(),
            section=display_name(relative.parent.as_posix()) if relative.parent != Path(".") else "General",
            source=relative,
            asset_url=url_path(base_url, asset_relative.as_posix()),
            viewer_url=url_path(base_url, "view", f"{viewer_id}.html"),
            size=format_size(pdf.stat().st_size),
        )
        entries.append(entry)

        viewer_path = output / "view" / f"{viewer_id}.html"
        viewer_path.parent.mkdir(parents=True, exist_ok=True)
        viewer_path.write_text(
            environment.get_template("viewer.html").render(
                site=config,
                entry=entry,
                base_url=base_url,
                analytics_id=analytics_id,
            ),
            encoding="utf-8",
        )

    grouped_by_key: dict[str, list[PdfEntry]] = {}
    for entry in entries:
        grouped_by_key.setdefault(entry.section_key, []).append(entry)

    topic_order = config.get("topic_order", [])
    pdf_order = config.get("pdf_order", {})
    grouped_entries: dict[str, list[PdfEntry]] = {}
    for section_key in sorted(
        grouped_by_key,
        key=lambda topic: topic_sort_key(topic, topic_order),
    ):
        section_entries = sorted(
            grouped_by_key[section_key],
            key=lambda entry: pdf_sort_key(entry, pdf_order.get(section_key, [])),
        )
        grouped_entries[section_entries[0].section] = section_entries

    (output / "index.html").write_text(
        environment.get_template("index.html").render(
            site=config,
            groups=grouped_entries,
            pdf_count=len(entries),
            base_url=base_url,
            analytics_id=analytics_id,
        ),
        encoding="utf-8",
    )
    shutil.copytree(SITE_DIR / "static", output / "assets", dirs_exist_ok=True)
    (output / ".nojekyll").touch()
    return len(entries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--base-url", default="")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=SITE_DIR / "pdf_metadata.json",
        help="JSON file containing per-PDF title and description overrides",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    count = build_site(
        source=arguments.source,
        output=arguments.output,
        base_url=arguments.base_url,
        analytics_id=os.environ.get("GOOGLE_ANALYTICS_ID", "").strip(),
        metadata_path=arguments.metadata,
    )
    print(f"Generated {count} PDF entries in {arguments.output}")
