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

## Sprint 2: Chunker + Embedder
**Goal**: Can parse code files into AST-aware chunks and generate embeddings

- [ ] Implement `src/wrag/chunker.py` — tree-sitter chunking (Python, PHP, YAML, JSON, Markdown, fallback)
- [ ] Implement `src/wrag/embedder.py` — LocalEmbedder (sentence-transformers) + OpenAIEmbedder + factory
- [ ] Create `tests/test_chunker.py` — test each language parser
- [ ] Create `tests/test_embedder.py` — test embedding output shape/type
- [ ] Verify: chunk a Python file → get function-level chunks; embed them → get 384-dim vectors

---

## Sprint 3: Vector Store + Indexer
**Goal**: `wrag index <app>` indexes a workspace; `wrag status` shows stats

- [ ] Implement `src/wrag/store.py` — LanceDB connect, upsert, delete, search, stats
- [ ] Implement `src/wrag/sources/workspace.py` — file walker with exclusions + hash computation
- [ ] Implement `src/wrag/indexer.py` — orchestrate: walk → hash compare → chunk → embed → store
- [ ] Add CLI commands: `wrag index [name]`, `wrag index --force`, `wrag status`, `wrag search`
- [ ] Create `tests/test_store.py` — test upsert, search, delete
- [ ] Create `tests/test_indexer.py` — test incremental indexing (mock embedder)
- [ ] Verify: `wrag add devopsagent <path>` + `wrag index devopsagent` → chunks stored; second run skips unchanged

---

## Sprint 4: Confluence Source
**Goal**: `wrag index <confluence-source>` fetches and indexes Confluence pages

- [ ] Implement `src/wrag/sources/confluence.py` — API client, HTML→text, heading chunker
- [ ] Wire into indexer: detect source type, dispatch to confluence handler
- [ ] Add incremental: page version tracking in manifest
- [ ] Create `tests/test_confluence.py` — test HTML parsing, chunking, API mock
- [ ] Verify: `wrag add-confluence lionbridge-docs --domain X --space Y` + `wrag index lionbridge-docs` works

---

## Sprint 5: MCP Server
**Goal**: Copilot can query indexed codebase via MCP tools

- [ ] Implement `src/wrag/mcp_server.py` — FastMCP with search_code, search_docs, search_symbol, list_apps, app_overview
- [ ] Add CLI: `wrag serve` (stdio mode)
- [ ] Create `.vscode/mcp.json` for VS Code integration
- [ ] Create `tests/test_mcp_server.py` — test tool responses
- [ ] Verify: configure in VS Code → Copilot can call `search_code` and get results

---

## Sprint 6: File Watcher + Polish
**Goal**: Auto re-index on file changes; project ready for public GitHub

- [ ] Implement `src/wrag/watcher.py` — watchdog daemon with debounce
- [ ] Add CLI: `wrag watch`, `wrag watch --daemon`
- [ ] Create README.md — setup, usage, MCP integration guide
- [ ] Final testing: end-to-end flow across multiple workspaces + Confluence
- [ ] Push to GitHub

---

## Progress Summary

| Sprint | Status | Tasks Done |
|--------|--------|------------|
| 1 | ✅ Complete | 9/9 |
| 2 | ⬜ Not Started | 0/5 |
| 3 | ⬜ Not Started | 0/7 |
| 4 | ⬜ Not Started | 0/5 |
| 5 | ⬜ Not Started | 0/5 |
| 6 | ⬜ Not Started | 0/5 |
