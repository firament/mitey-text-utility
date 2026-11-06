#!/usr/bin/env python3
"""
mitey Text Utility offline bundler.

Fetches CDN resources referenced in the mitey Text Utility HTML head section
and inlines them as <style> and <script> blocks so the page works fully offline
from a single self-contained HTML file.

Requirements:
    - Python 3.8+
    - Network access to fetch CDN assets

Usage:
    python make-mtu-offline.py 1.0.2
    python make-mtu-offline.py 1.0.2 --input dist/mitey-text-utility-102.html
    python make-mtu-offline.py 1.0.2 --output dist/mitey-text-utility-102-offline.html
    python make-mtu-offline.py 1.0.2 --timeout 60 --retries 5

The version is required and must be the first argument. Dots are removed
to build the dist file name. Version 1.0.2 copies:
    mitey-text-utility.html -> dist/mitey-text-utility-102.html
Then that copy is the default input. The default output appends -offline
to the input file name:
    dist/mitey-text-utility-102-offline.html
--input and --output replace those defaults only when you pass them.

Tags already inlined (with a data-source attribute) are left unchanged. To
refresh specific resources, replace an inlined block with its original CDN
<link> or <script src="..."> tag and rerun.

Stylesheet id and disabled attributes are copied onto the inlined <style>
so theme toggling in the viewer still works after bundling.

Exit codes:
    0 - Success
    1 - Usage or validation error
    2 - Fetch failure
    3 - Write failure
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

SOURCE_HTML = "mitey-text-utility.html"
DIST_DIR = Path("dist")
OUTPUT_STEM = "mitey-text-utility"
VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
DATA_SOURCE_ATTR = "data-source="
INDENT = "        "
USER_AGENT = "make-mtu-offline/1.0 (mitey Text Utility offline bundler)"

# Comments that bound the CDN resource block in the HTML head.
# Keep these markers in mitey-text-utility.html. They do not depend on
# the names of the library sections inside the block.
BUNDLE_START = "<!-- BUNDLE-START"
BUNDLE_END = "<!-- BUNDLE-END"

LINK_PATTERN = re.compile(
    r'<link(?![^>]*\bdata-source=)[^>]*\brel="stylesheet"[^>]*\bhref="(https://[^"]+)"[^>]*/?>',
    re.IGNORECASE,
)
SCRIPT_PATTERN = re.compile(
    r'<script(?![^>]*\bdata-source=)[^>]*\bsrc="(https://[^"]+)"[^>]*>\s*</script>',
    re.IGNORECASE,
)
LINK_ID_PATTERN = re.compile(r'\bid="([^"]+)"', re.IGNORECASE)
LINK_DISABLED_PATTERN = re.compile(r"(?<![\w-])disabled(?![\w-])", re.IGNORECASE)


@dataclass(frozen=True)
class CdnTag:
    """A CDN resource tag found in the source HTML."""

    kind: str  # "link" or "script"
    url: str
    start: int
    end: int
    original: str


class OfflineBundlerError(Exception):
    """Base exception for bundler failures."""

    exit_code: int = 1


class ValidationError(OfflineBundlerError):
    """Input/output validation failed."""

    exit_code = 1


class FetchError(OfflineBundlerError):
    """One or more CDN resources could not be fetched."""

    exit_code = 2


class WriteError(OfflineBundlerError):
    """Output file could not be written."""

    exit_code = 3


def extract_cdn_section(html: str) -> str:
    """
    Return the HTML substring containing the CDN resource tags.

    Raises:
        ValidationError: If section markers are missing.
    """
    start = html.find(BUNDLE_START)
    if start == -1:
        raise ValidationError(f"Could not find section marker: {BUNDLE_START!r}")

    end = html.find(BUNDLE_END, start)
    if end == -1:
        raise ValidationError(f"Could not find section marker: {BUNDLE_END!r}")

    return html[start:end]


def find_cdn_tags(html: str) -> List[CdnTag]:
    """
    Find external stylesheet and script tags in the CDN head section.

    Tags that already have a data-source attribute (inlined from a prior run)
    are ignored. This supports partial re-bundling: remove data-source and the
    inlined content from selected tags, restore the original CDN link/script
    tag, and rerun the script to refresh only those resources.

    Returns:
        List of CdnTag objects in document order.
    """
    section = extract_cdn_section(html)
    section_offset = html.find(section)

    tags: List[CdnTag] = []
    for pattern, kind in ((LINK_PATTERN, "link"), (SCRIPT_PATTERN, "script")):
        for match in pattern.finditer(section):
            original = match.group(0)
            if DATA_SOURCE_ATTR in original:
                continue
            tags.append(
                CdnTag(
                    kind=kind,
                    url=match.group(1),
                    start=section_offset + match.start(),
                    end=section_offset + match.end(),
                    original=original,
                )
            )

    tags.sort(key=lambda tag: tag.start)
    return tags


def looks_binary(content: str) -> bool:
    """Return True if decoded content appears to contain binary data."""
    if "\x00" in content:
        return True
    # Reject if a large fraction of characters are non-printable.
    sample = content[:4096]
    if not sample:
        return False
    non_printable = sum(1 for ch in sample if ch < " " and ch not in "\t\n\r")
    return non_printable / len(sample) > 0.05


def fetch_url(
    url: str,
    *,
    timeout: int,
    retries: int,
    cache: Dict[str, str],
) -> str:
    """
    Fetch a URL and return its decoded text content.

    Uses an in-memory cache, retries with exponential backoff, and validates
    the response is non-empty UTF-8 text.

    Args:
        url: Absolute URL to fetch.
        timeout: Per-request timeout in seconds.
        retries: Number of attempts before giving up.
        cache: Mutable cache mapping URL to fetched content.

    Returns:
        Decoded response body.

    Raises:
        FetchError: If all retry attempts fail or content is invalid.
    """
    if url in cache:
        return cache[url]

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                if status != 200:
                    raise urllib.error.HTTPError(
                        url, status, f"Unexpected HTTP status {status}", response.headers, None
                    )
                raw = response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                delay = 2 ** (attempt - 1)
                print(
                    f"  Retry {attempt}/{retries} for {url} after {delay}s ({exc})",
                    file=sys.stderr,
                )
                time.sleep(delay)
            continue

        if not raw:
            raise FetchError(f"Empty response body from {url}")

        content = raw.decode("utf-8", errors="replace")
        if looks_binary(content):
            raise FetchError(f"Response from {url} appears to be binary, not text")

        cache[url] = content
        return content

    raise FetchError(f"Failed to fetch {url} after {retries} attempt(s): {last_error}")


def stylesheet_preserved_attrs(original: str) -> str:
    """
    Return id and disabled attributes to copy from a <link> onto <style>.

    Args:
        original: Original <link> tag text.

    Returns:
        Leading-space attribute string, or empty if neither is present.
    """
    parts: List[str] = []
    id_match = LINK_ID_PATTERN.search(original)
    if id_match:
        parts.append(f'id="{id_match.group(1)}"')
    if LINK_DISABLED_PATTERN.search(original):
        parts.append("disabled")
    return (" " + " ".join(parts)) if parts else ""


def inline_stylesheet(url: str, css: str, indent: str = "", extra_attrs: str = "") -> str:
    """
    Build an inline <style> block for a fetched stylesheet.

    Args:
        url: Original CDN URL (stored in data-source for traceability).
        css: Stylesheet content.
        indent: Leading whitespace to match the replaced tag.
        extra_attrs: Optional attributes preserved from the <link> (id, disabled).

    Returns:
        Indented inline <style> element.
    """
    return (
        f'{indent}<style{extra_attrs} data-source="{url}">\n'
        f"{css.rstrip()}\n"
        f"{indent}</style>"
    )


def inline_script(url: str, js: str, indent: str = "") -> str:
    """
    Build an inline <script> block for a fetched JavaScript file.

    Escapes </script> sequences inside the JS to avoid breaking the HTML.

    Args:
        url: Original CDN URL (stored in data-source for traceability).
        js: JavaScript content.
        indent: Leading whitespace to match the replaced tag.

    Returns:
        Indented inline <script> element.
    """
    safe_js = js.replace("</script>", r"<\/script>")
    return (
        f'{indent}<script data-source="{url}">\n'
        f"{safe_js.rstrip()}\n"
        f"{indent}</script>"
    )


def build_offline_html(
    html: str,
    *,
    timeout: int,
    retries: int,
) -> Tuple[str, int]:
    """
    Replace CDN link/script tags with inlined style/script blocks.

    Args:
        html: Source HTML content.
        timeout: Per-request fetch timeout in seconds.
        retries: Number of fetch retries per URL.

    Returns:
        Tuple of (transformed HTML, number of unique URLs fetched).

    Raises:
        FetchError: If any resource cannot be fetched.
    """
    tags = find_cdn_tags(html)
    cache: Dict[str, str] = {}
    replacements: List[Tuple[int, int, str]] = []

    if not tags:
        print("No CDN link/script tags to fetch (all resources already inlined).")
        return html, 0

    print(f"Fetching {len(tags)} CDN resource(s)...")

    for index, tag in enumerate(tags, start=1):
        print(f"  [{index}/{len(tags)}] {tag.url}")
        content = fetch_url(
            tag.url,
            timeout=timeout,
            retries=retries,
            cache=cache,
        )
        indent_match = re.match(r"^(\s*)", tag.original)
        indent = indent_match.group(1) if indent_match else INDENT
        if tag.kind == "link":
            extra_attrs = stylesheet_preserved_attrs(tag.original)
            replacement = inline_stylesheet(tag.url, content, indent, extra_attrs)
        else:
            replacement = inline_script(tag.url, content, indent)
        replacements.append((tag.start, tag.end, replacement))

    # Apply replacements bottom-up so earlier offsets stay valid.
    result = html
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]

    return result, len(cache)


def version_token(version: str) -> str:
    """
    Turn a dotted version into the digits used in dist file names.

    Example: 1.0.2 -> 102

    Raises:
        ValidationError: If the version is not numbers separated by dots.
    """
    if not VERSION_PATTERN.fullmatch(version):
        raise ValidationError(
            "Version must be numbers separated by dots, for example 1.0.2."
        )
    return version.replace(".", "")


def copied_dist_path(version: str) -> Path:
    """
    Return the versioned copy path under ./dist.

    Example: 1.0.2 -> dist/mitey-text-utility-102.html
    """
    token = version_token(version)
    return DIST_DIR / f"{OUTPUT_STEM}-{token}.html"


def offline_path_for(input_path: Path) -> Path:
    """
    Return the default offline path for an input file.

    The suffix stays in place. name.html becomes name-offline.html.
    """
    suffix = input_path.suffix
    return input_path.with_name(f"{input_path.stem}-offline{suffix}")


def validate_paths(input_path: Path, output_path: Path) -> None:
    """
    Validate the bundle input and output paths.

    Raises:
        ValidationError: If the input is missing or the output would overwrite it.
    """
    if not input_path.is_file():
        raise ValidationError(f"Input file not found: {input_path}")

    try:
        if input_path.resolve() == output_path.resolve():
            raise ValidationError(
                "Output path must differ from input path to avoid overwriting the source file."
            )
    except OSError as exc:
        raise ValidationError(f"Could not resolve file paths: {exc}") from exc


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Copy mitey Text Utility into dist and bundle its CDN dependencies "
            "into an offline HTML file."
        ),
        epilog=(
            "Example: python make-mtu-offline.py 1.0.2 "
            "copies dist/mitey-text-utility-102.html and writes "
            "dist/mitey-text-utility-102-offline.html"
        ),
    )
    parser.add_argument(
        "version",
        help="Version number, for example 1.0.2 (required, first argument)",
    )
    parser.add_argument(
        "-i",
        "--input",
        default=None,
        help=(
            "HTML file to bundle "
            "(default: the versioned copy in dist)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Offline HTML file to write "
            "(default: input file name with -offline before the extension)"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of fetch retries per URL (default: 3)",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    """
    Entry point for the offline bundler CLI.

    Returns:
        Process exit code (0 on success).
    """
    args = parse_args(argv)

    if args.timeout < 1:
        print("Error: --timeout must be at least 1.", file=sys.stderr)
        return 1
    if args.retries < 1:
        print("Error: --retries must be at least 1.", file=sys.stderr)
        return 1

    source_path = Path(SOURCE_HTML)

    try:
        copy_path = copied_dist_path(args.version)
        if not source_path.is_file():
            raise ValidationError(f"Input file not found: {source_path}")
        if source_path.resolve() == copy_path.resolve():
            raise ValidationError(
                "The versioned copy path must differ from the source file."
            )
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, copy_path)
        print(f"Copied source HTML to {copy_path}.")

        input_path = Path(args.input) if args.input else copy_path
        output_path = Path(args.output) if args.output else offline_path_for(input_path)
        validate_paths(input_path, output_path)
        html = input_path.read_text(encoding="utf-8")
        offline_html, unique_urls = build_offline_html(
            html,
            timeout=args.timeout,
            retries=args.retries,
        )
        print(f"Bundled {input_path}.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(offline_html, encoding="utf-8", newline="\n")
        print(
            f"Wrote offline HTML to {output_path} "
            f"({len(offline_html):,} bytes, {unique_urls} unique URLs inlined)."
        )
    except OfflineBundlerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"Error writing output file: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
