"""Tests for wrag.chunker — AST-aware code chunking."""

import pytest

from wrag.chunker import Chunk, chunk_file, detect_language


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("src/main.py") == "python"

    def test_php(self):
        assert detect_language("web/modules/custom/my_module.module") == "php"
        assert detect_language("src/Controller.php") == "php"

    def test_yaml(self):
        assert detect_language("config/services.yml") == "yaml"
        assert detect_language("docker-compose.yaml") == "yaml"

    def test_markdown(self):
        assert detect_language("README.md") == "markdown"

    def test_javascript(self):
        assert detect_language("app.js") == "javascript"
        assert detect_language("component.tsx") == "typescript"

    def test_unknown(self):
        assert detect_language("Makefile") == "unknown"
        assert detect_language("data.csv") == "unknown"


class TestChunkMarkdown:
    def test_splits_by_headings(self):
        content = """# Title

Introduction text.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
        chunks = chunk_file(content, "README.md", "testapp")
        assert len(chunks) >= 2
        assert all(isinstance(c, Chunk) for c in chunks)
        # All chunks should have markdown language
        assert all(c.language == "markdown" for c in chunks)

    def test_single_section(self):
        content = "# Just a title\n\nSome content here.\n"
        chunks = chunk_file(content, "doc.md", "testapp")
        assert len(chunks) == 1
        assert chunks[0].symbol_type == "section"

    def test_empty_file(self):
        chunks = chunk_file("", "empty.md", "testapp")
        # Should handle gracefully
        assert len(chunks) == 0 or all(c.text.strip() == "" for c in chunks)


class TestChunkYAML:
    def test_splits_by_top_level_keys(self):
        content = """name: my-project
version: 1.0

dependencies:
  click: ">=8.1"
  pyyaml: ">=6.0"

settings:
  debug: true
  port: 8080
"""
        chunks = chunk_file(content, "config.yml", "testapp")
        assert len(chunks) >= 2
        assert all(c.language == "yaml" for c in chunks)
        # Should have named keys
        key_names = [c.symbol_name for c in chunks]
        assert "name" in key_names or "dependencies" in key_names

    def test_small_yaml_single_key(self):
        content = "key: value\n"
        chunks = chunk_file(content, "small.yml", "testapp")
        assert len(chunks) >= 1


class TestChunkPython:
    def test_splits_at_functions(self):
        content = '''"""Module docstring."""

def hello():
    """Say hello."""
    print("hello")

def goodbye():
    """Say goodbye."""
    print("goodbye")

class MyClass:
    """A class."""

    def method_one(self):
        pass

    def method_two(self):
        pass
'''
        chunks = chunk_file(content, "module.py", "testapp")
        assert len(chunks) >= 2
        # Should find function names
        names = [c.symbol_name for c in chunks]
        assert "hello" in names or "goodbye" in names or "MyClass" in names

    def test_small_python_file(self):
        content = "x = 1\ny = 2\n"
        chunks = chunk_file(content, "small.py", "testapp")
        # Small file with no functions: falls back to line-based
        assert len(chunks) >= 1


class TestChunkPHP:
    def test_splits_at_functions(self):
        content = """<?php

namespace Drupal\\my_module;

function my_function() {
    return 'hello';
}

class MyService {
    public function doSomething() {
        return true;
    }

    public function doAnother() {
        return false;
    }
}
"""
        chunks = chunk_file(content, "MyService.php", "testapp")
        assert len(chunks) >= 1
        assert all(c.language == "php" for c in chunks)


class TestChunkByLines:
    def test_large_file_splits(self):
        # Create a file larger than max_lines
        lines = [f"line {i}" for i in range(200)]
        content = "\n".join(lines)
        chunks = chunk_file(content, "large.txt", "testapp", max_lines=60)
        assert len(chunks) > 1
        # Chunks should cover the full file
        assert chunks[0].start_line == 1

    def test_small_file_single_chunk(self):
        content = "line 1\nline 2\nline 3\n"
        chunks = chunk_file(content, "small.txt", "testapp", max_lines=60)
        assert len(chunks) == 1
        assert chunks[0].symbol_type == "file"


class TestChunkMetadata:
    def test_chunk_has_required_fields(self):
        content = "x = 1\n"
        chunks = chunk_file(content, "test.py", "myapp")
        for chunk in chunks:
            assert chunk.app_name == "myapp"
            assert chunk.path == "test.py"
            assert chunk.id.startswith("myapp::")
            assert chunk.start_line >= 1
            assert chunk.end_line >= chunk.start_line

    def test_chunk_to_dict(self):
        chunk = Chunk(
            id="app::file.py::function::foo",
            text="def foo(): pass",
            path="file.py",
            app_name="app",
            language="python",
            symbol_name="foo",
            symbol_type="function",
            start_line=1,
            end_line=1,
        )
        d = chunk.to_dict()
        assert d["id"] == "app::file.py::function::foo"
        assert d["symbol_name"] == "foo"
        assert d["source_type"] == "workspace"
