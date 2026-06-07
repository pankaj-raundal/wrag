# wRag — Sprint Tracker

## Sprint 1: Project Skeleton + Config ✅
**Goal**: Runnable CLI with `wrag add/remove/list/config` commands

- [x] Create project directory structure (`src/wrag/`, `src/wrag/sources/`, `tests/`)
- [x] Create `pyproject.toml` with all dependencies and entry point
- [x] Create `.gitignore`
- [x] Create `src/wrag/__init__.py`
- [x] Create `src/wrag/sources/__init__.py`
- [x] Implement `src/wrag/config.py` — load/save YAML config (workspaces + confluences + settings)
- [x] Implement `src/wrag/cli.py` — Click CLI with `add`, `add-confluence`, `remove`, `list`, `config`
- [x] Create `config.yaml` template
- [x] Verify: `pip install -e .` + `wrag list` works

---

## Sprint 2: Chunker + Embedder ✅
**Goal**: Can parse code files into AST-aware chunks and generate embeddings

- [x] Implement `src/wrag/chunker.py` — tree-sitter chunking (Python, PHP, YAML, JSON, Markdown, fallback)
- [x] Implement `src/wrag/embedder.py` — LocalEmbedder (sentence-transformers) + OpenAIEmbedder + factory
- [x] Create `tests/test_chunker.py` — test each language parser
- [x] Create `tests/test_embedder.py` — test embedding output shape/type
- [x] Verify: chunk a Python file → get function-level chunks; embed them → get 384-dim vectors

---

## Sprint 3: Vector Store + Indexer ✅
**Goal**: `wrag index <app>` indexes a workspace; `wrag status` shows stats

- [x] Implement `src/wrag/store.py` — LanceDB connect, upsert, delete, search, stats
- [x] Implement `src/wrag/sources/workspace.py` — file walker with exclusions + hash computation
- [x] Implement `src/wrag/indexer.py` — orchestrate: walk → hash compare → chunk → embed → store
- [x] Add CLI commands: `wrag index [name]`, `wrag index --force`, `wrag status`, `wrag search`
- [x] Create `tests/test_store.py` — test upsert, search, delete
- [x] Create `tests/test_indexer.py` — test incremental indexing (mock embedder)
- [x] Verify: `wrag add devopsagent <path>` + `wrag index devopsagent` → chunks stored; second run skips unchanged

---

## Sprint 4: Confluence Source ✅
**Goal**: `wrag index <confluence-source>` fetches and indexes Confluence pages

- [x] Implement `src/wrag/sources/confluence.py` — API client, HTML→text, heading chunker
- [x] Wire into indexer: detect source type, dispatch to confluence handler
- [x] Add incremental: page version tracking in manifest
- [x] Create `tests/test_confluence.py` — test HTML parsing, chunking, API mock
- [x] Verify: `wrag add-confluence lionbridge-docs --domain X --space Y` + `wrag index lionbridge-docs` works

---

## Sprint 5: MCP Server ✅
**Goal**: Copilot can query indexed codebase via MCP tools

- [x] Implement `src/wrag/mcp_server.py` — FastMCP with search_code, search_docs, search_symbol, list_apps, app_overview
- [x] Add CLI: `wrag serve` (stdio mode)
- [x] Create `.vscode/mcp.json` for VS Code integration
- [x] Create `tests/test_mcp_server.py` — test tool responses
- [x] Verify: configure in VS Code → Copilot can call `search_code` and get results

---

## Sprint 6: File Watcher + Polish ✅
**Goal**: Auto re-index on file changes; project ready for public GitHub

- [x] Implement `src/wrag/watcher.py` — watchdog daemon with debounce
- [x] Add CLI: `wrag watch`, `wrag watch --debounce`
- [x] Create README.md — setup, usage, MCP integration guide
- [x] Final testing: end-to-end flow across multiple workspaces + Confluence
- [x] Push to GitHub

---

## Sprint 7: Preview UI + Query Testing ✅
**Goal**: Local web UI to test queries, preview results, and validate what Copilot would receive from wRag

- [x] Implement `src/wrag/web_ui.py` — Built-in HTTP server with search UI
- [x] Create HTML template with search form, results display, tool selector
- [x] Add CLI: `wrag ui` (starts local web server on port 8787)
- [x] Show request log / stats in the UI
- [x] Verify: open browser → search → see same results Copilot gets

---

## Progress Summary

| Sprint | Status | Tasks Done |
|--------|--------|------------|
| 1 | ✅ Complete | 9/9 |
| 2 | ✅ Complete | 5/5 |
| 3 | ✅ Complete | 7/7 |
| 4 | ✅ Complete | 5/5 |
| 5 | ✅ Complete | 5/5 |
| 6 | ✅ Complete | 5/5 |
| 7 | ✅ Complete | 5/5 |
