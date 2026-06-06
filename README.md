# wRag — Local Codebase RAG for GitHub Copilot

Index your local workspaces and Confluence docs into a vector database, then let GitHub Copilot query them via MCP — reducing API calls and improving context relevance.

## Features

- **AST-aware code chunking** — tree-sitter parsing for Python, PHP, JS/TS; heading-based for Markdown/YAML
- **Confluence integration** — indexes Confluence spaces via REST API
- **Incremental indexing** — only re-processes changed files (SHA-256 manifest)
- **MCP server** — exposes search tools directly to GitHub Copilot
- **File watcher** — auto re-indexes on file changes
- **Local embeddings** — `all-MiniLM-L6-v2` (384-dim), no API key needed

## Quick Start

```bash
# Clone and install
git clone https://github.com/pankaj-raundal/wrag.git
cd wrag
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Register a workspace
wrag add myproject /path/to/project

# Index it
wrag index myproject

# Check status
wrag status

# Search
wrag search "authentication middleware" --app myproject
```

## MCP Integration (VS Code / GitHub Copilot)

1. The project includes `.vscode/mcp.json` that configures the MCP server.
2. Open the wRag folder (or any folder with a copy of the mcp.json) in VS Code.
3. Copilot will auto-discover the `wrag` MCP server and gain access to these tools:

| Tool | Description |
|------|-------------|
| `search_code` | Semantic search across indexed code |
| `search_docs` | Search indexed Confluence documentation |
| `search_symbol` | Find functions/classes by name |
| `list_apps` | Show all indexed apps with stats |
| `app_overview` | Get details on a specific app |

To use from any workspace, copy `.vscode/mcp.json` there or add to your user-level MCP config.

## Commands

```
wrag add <name> <path>          Register a local workspace
wrag add-confluence <name>      Register a Confluence space
wrag remove <name>              Remove a registered source
wrag list                       List all registered sources
wrag index [name]               Index a source (or all)
wrag index --force              Re-index everything
wrag status                     Show indexing stats
wrag search <query>             Semantic search
wrag serve                      Start MCP server (stdio)
wrag watch                      Watch workspaces, auto re-index
wrag config                     Show current config
```

## Confluence Setup

```bash
# Register a Confluence space
wrag add-confluence docs --domain mycompany.atlassian.net --space DEV --email user@company.com

# Set credentials (env vars or ~/.config/dai/credentials.env)
export CONFLUENCE_API_TOKEN=your_token
export CONFLUENCE_USER_EMAIL=user@company.com

# Index
wrag index docs
```

## File Watcher

```bash
# Watch all registered workspaces for changes
wrag watch

# Custom debounce (seconds before triggering re-index)
wrag watch --debounce 5
```

## Architecture

```
src/wrag/
├── cli.py              Click CLI entry point
├── config.py           YAML config management
├── chunker.py          AST-aware code chunking (tree-sitter)
├── embedder.py         Embedding abstraction (local + OpenAI)
├── store.py            LanceDB vector store
├── indexer.py          Orchestrator (walk → chunk → embed → store)
├── mcp_server.py       FastMCP server (5 tools)
├── watcher.py          File watcher (watchdog + debounce)
└── sources/
    ├── workspace.py    Local filesystem walker
    └── confluence.py   Confluence REST API client
```

## Configuration

Config lives at `config.yaml` in the project root:

```yaml
workspaces:
  - name: myproject
    path: /home/user/projects/myproject
confluences:
  - name: docs
    domain: mycompany.atlassian.net
    space_key: DEV
    email: user@company.com
settings:
  embedding_model: local
  chunk_max_lines: 60
  excluded_dirs: [vendor, node_modules, .git, __pycache__, .venv]
```

## Requirements

- Python 3.10+
- ~500MB disk for the embedding model (downloaded on first use)

## License

MIT
