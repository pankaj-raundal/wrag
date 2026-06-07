"""AST-aware code chunking using tree-sitter.

Chunks source files at semantic boundaries (functions, classes, methods)
for better embedding quality. Falls back to line-based chunking for
unsupported languages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Chunk:
    """A single chunk of code or text."""

    id: str  # unique: <app_name>::<path>::<symbol_or_line>
    text: str
    path: str  # relative path within the workspace
    app_name: str
    language: str
    symbol_name: str = ""
    symbol_type: str = ""  # function, class, method, section, block
    start_line: int = 0
    end_line: int = 0
    source_type: str = "workspace"  # workspace or confluence

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "path": self.path,
            "app_name": self.app_name,
            "language": self.language,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_type": self.source_type,
        }


# Language detection by extension
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".php": "php",
    ".module": "php",
    ".inc": "php",
    ".install": "php",
    ".theme": "php",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "bash",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".css": "css",
    ".html": "html",
    ".twig": "html",
    ".xml": "xml",
}

# tree-sitter node types to extract per language
AST_CHUNK_NODES = {
    "python": [
        "function_definition",
        "class_definition",
        "decorated_definition",
    ],
    "php": [
        "function_definition",
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "trait_declaration",
    ],
    "javascript": [
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ],
    "typescript": [
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
        "interface_declaration",
        "type_alias_declaration",
    ],
}

# Name extraction node types per language
NAME_NODES = {
    "python": "name",
    "php": "name",
    "javascript": "name",
    "typescript": "name",
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext, "unknown")


def chunk_file(
    content: str,
    file_path: str,
    app_name: str,
    max_lines: int = 60,
    overlap_lines: int = 10,
) -> list[Chunk]:
    """Chunk a file into semantic pieces.

    Uses tree-sitter for supported languages (Python, PHP, JS/TS),
    heading-based splitting for Markdown/YAML, and line-based fallback.
    """
    language = detect_language(file_path)

    if language in AST_CHUNK_NODES:
        chunks = _chunk_with_treesitter(content, file_path, app_name, language, max_lines)
    elif language == "markdown":
        chunks = _chunk_markdown(content, file_path, app_name)
    elif language == "yaml":
        chunks = _chunk_yaml(content, file_path, app_name, max_lines)
    elif language == "json":
        chunks = _chunk_json(content, file_path, app_name, max_lines)
    else:
        chunks = _chunk_by_lines(content, file_path, app_name, language, max_lines, overlap_lines)

    return chunks


def _chunk_with_treesitter(
    content: str,
    file_path: str,
    app_name: str,
    language: str,
    max_lines: int,
) -> list[Chunk]:
    """Chunk using tree-sitter AST parsing."""
    try:
        from tree_sitter_languages import get_parser
    except ImportError:
        # Fallback if tree-sitter-languages not installed
        return _chunk_by_lines(content, file_path, app_name, language, max_lines, 10)

    parser = get_parser(language)
    tree = parser.parse(content.encode("utf-8"))

    chunks: list[Chunk] = []
    target_types = set(AST_CHUNK_NODES[language])
    lines = content.split("\n")

    # Walk AST and collect top-level and class-level definitions
    visited_ranges: list[tuple[int, int]] = []

    def _walk(node, depth=0):
        if node.type in target_types:
            start_line = node.start_point[0]
            end_line = node.end_point[0]

            # Extract symbol name
            symbol_name = _extract_symbol_name(node, language)
            symbol_type = _node_type_to_symbol_type(node.type)

            # Get the text for this node
            chunk_text = "\n".join(lines[start_line : end_line + 1])

            # If chunk is too large, split it but still record the top-level chunk
            if end_line - start_line + 1 > max_lines * 2:
                # For very large nodes, extract sub-nodes (methods in a class)
                sub_chunks = _extract_sub_chunks(
                    node, lines, file_path, app_name, language, max_lines
                )
                if sub_chunks:
                    chunks.extend(sub_chunks)
                    visited_ranges.append((start_line, end_line))
                    return
                # If no sub-chunks, fall through to add as single chunk

            chunk_id = f"{app_name}::{file_path}::{symbol_type}::{symbol_name or f'L{start_line}'}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=chunk_text,
                    path=file_path,
                    app_name=app_name,
                    language=language,
                    symbol_name=symbol_name,
                    symbol_type=symbol_type,
                    start_line=start_line + 1,  # 1-indexed
                    end_line=end_line + 1,
                )
            )
            visited_ranges.append((start_line, end_line))
        else:
            for child in node.children:
                if depth < 100:  # Cap recursion depth for deeply nested files
                    _walk(child, depth + 1)

    try:
        _walk(tree.root_node)
    except RecursionError:
        # Fallback for extremely nested files
        return _chunk_by_lines(content, file_path, app_name, language, max_lines, 10)

    # If no AST chunks found or file has significant uncovered regions,
    # add the remaining content as line-based chunks
    if not chunks:
        return _chunk_by_lines(content, file_path, app_name, language, max_lines, 10)

    return chunks


def _extract_sub_chunks(
    node, lines: list[str], file_path: str, app_name: str, language: str, max_lines: int
) -> list[Chunk]:
    """Extract method-level chunks from a large class node."""
    sub_chunks: list[Chunk] = []
    target_types = {"method_declaration", "method_definition", "function_definition"}

    for child in node.children:
        if child.type in target_types:
            start_line = child.start_point[0]
            end_line = child.end_point[0]
            symbol_name = _extract_symbol_name(child, language)
            symbol_type = _node_type_to_symbol_type(child.type)
            chunk_text = "\n".join(lines[start_line : end_line + 1])

            chunk_id = f"{app_name}::{file_path}::{symbol_type}::{symbol_name or f'L{start_line}'}"
            sub_chunks.append(
                Chunk(
                    id=chunk_id,
                    text=chunk_text,
                    path=file_path,
                    app_name=app_name,
                    language=language,
                    symbol_name=symbol_name,
                    symbol_type=symbol_type,
                    start_line=start_line + 1,
                    end_line=end_line + 1,
                )
            )
        # Recurse into nested classes/blocks
        elif child.type in {"class_body", "declaration_list", "block", "compound_statement"}:
            sub_chunks.extend(
                _extract_sub_chunks(child, lines, file_path, app_name, language, max_lines)
            )

    return sub_chunks


def _extract_symbol_name(node, language: str) -> str:
    """Extract the name of a function/class/method from a tree-sitter node."""
    # Look for a 'name' or 'identifier' child
    for child in node.children:
        if child.type in ("name", "identifier", "property_identifier"):
            return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
    # For decorated definitions, look inside
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                return _extract_symbol_name(child, language)
    return ""


def _node_type_to_symbol_type(node_type: str) -> str:
    """Map tree-sitter node type to a simpler symbol type."""
    mapping = {
        "function_definition": "function",
        "function_declaration": "function",
        "class_definition": "class",
        "class_declaration": "class",
        "method_declaration": "method",
        "method_definition": "method",
        "interface_declaration": "interface",
        "trait_declaration": "trait",
        "decorated_definition": "function",
        "arrow_function": "function",
        "export_statement": "export",
        "type_alias_declaration": "type",
    }
    return mapping.get(node_type, "block")


def _chunk_markdown(content: str, file_path: str, app_name: str) -> list[Chunk]:
    """Chunk markdown by heading boundaries."""
    lines = content.split("\n")
    chunks: list[Chunk] = []
    current_heading = ""
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+", line):
            # Save previous section
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    chunk_id = f"{app_name}::{file_path}::section::{current_heading or 'intro'}"
                    chunks.append(
                        Chunk(
                            id=chunk_id,
                            text=text,
                            path=file_path,
                            app_name=app_name,
                            language="markdown",
                            symbol_name=current_heading or "intro",
                            symbol_type="section",
                            start_line=current_start + 1,
                            end_line=i,
                        )
                    )
            current_heading = re.sub(r"^#+\s+", "", line).strip()
            current_lines = [line]
            current_start = i
        else:
            current_lines.append(line)

    # Last section
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            chunk_id = f"{app_name}::{file_path}::section::{current_heading or 'intro'}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    path=file_path,
                    app_name=app_name,
                    language="markdown",
                    symbol_name=current_heading or "intro",
                    symbol_type="section",
                    start_line=current_start + 1,
                    end_line=len(lines),
                )
            )

    return chunks if chunks else _chunk_by_lines(content, file_path, app_name, "markdown", 60, 10)


def _chunk_yaml(
    content: str, file_path: str, app_name: str, max_lines: int
) -> list[Chunk]:
    """Chunk YAML by top-level keys."""
    lines = content.split("\n")
    chunks: list[Chunk] = []
    current_key = ""
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(lines):
        # Top-level key (no indentation, ends with colon)
        if line and not line[0].isspace() and ":" in line and not line.startswith("#"):
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    chunk_id = f"{app_name}::{file_path}::key::{current_key or 'header'}"
                    chunks.append(
                        Chunk(
                            id=chunk_id,
                            text=text,
                            path=file_path,
                            app_name=app_name,
                            language="yaml",
                            symbol_name=current_key or "header",
                            symbol_type="key",
                            start_line=current_start + 1,
                            end_line=i,
                        )
                    )
            current_key = line.split(":")[0].strip()
            current_lines = [line]
            current_start = i
        else:
            current_lines.append(line)

    # Last key
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            chunk_id = f"{app_name}::{file_path}::key::{current_key or 'header'}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    path=file_path,
                    app_name=app_name,
                    language="yaml",
                    symbol_name=current_key or "header",
                    symbol_type="key",
                    start_line=current_start + 1,
                    end_line=len(lines),
                )
            )

    return chunks if chunks else _chunk_by_lines(content, file_path, app_name, "yaml", max_lines, 10)


def _chunk_json(
    content: str, file_path: str, app_name: str, max_lines: int
) -> list[Chunk]:
    """Chunk JSON — typically treat as single chunk or by top-level keys."""
    lines = content.split("\n")
    if len(lines) <= max_lines:
        return [
            Chunk(
                id=f"{app_name}::{file_path}::file::root",
                text=content,
                path=file_path,
                app_name=app_name,
                language="json",
                symbol_name=Path(file_path).name,
                symbol_type="file",
                start_line=1,
                end_line=len(lines),
            )
        ]
    # For large JSON, fall back to line-based
    return _chunk_by_lines(content, file_path, app_name, "json", max_lines, 10)


def _chunk_by_lines(
    content: str,
    file_path: str,
    app_name: str,
    language: str,
    max_lines: int,
    overlap_lines: int,
) -> list[Chunk]:
    """Fallback: chunk by line windows with overlap."""
    lines = content.split("\n")
    chunks: list[Chunk] = []

    if len(lines) <= max_lines:
        # Small file: single chunk
        return [
            Chunk(
                id=f"{app_name}::{file_path}::file::full",
                text=content,
                path=file_path,
                app_name=app_name,
                language=language,
                symbol_name=Path(file_path).name,
                symbol_type="file",
                start_line=1,
                end_line=len(lines),
            )
        ]

    i = 0
    chunk_num = 0
    while i < len(lines):
        end = min(i + max_lines, len(lines))
        chunk_text = "\n".join(lines[i:end])
        chunk_id = f"{app_name}::{file_path}::block::L{i + 1}"
        chunks.append(
            Chunk(
                id=chunk_id,
                text=chunk_text,
                path=file_path,
                app_name=app_name,
                language=language,
                symbol_name=f"block_{chunk_num}",
                symbol_type="block",
                start_line=i + 1,
                end_line=end,
            )
        )
        chunk_num += 1
        i = end - overlap_lines if end < len(lines) else end

    return chunks
