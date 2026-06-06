# wRag — Local Codebase RAG for GitHub Copilot

> **One-liner:** Index your code and docs locally, so GitHub Copilot already knows your project before you ask it anything.

---

## What is wRag?

When you use GitHub Copilot (or any AI coding assistant), it reads files, searches your workspace, and calls APIs to understand your code. Each of those operations costs a **request** against your plan's quota.

**wRag eliminates redundant requests** by pre-indexing your codebase and documentation into a local vector database. Instead of Copilot scanning hundreds of files each time you ask a question, it queries wRag's index in milliseconds and gets exactly the relevant code snippets — saving 60–80% of requests on repeated questions.

### The Problem (Without wRag)

```
You: "How does the authentication work in our Drupal module?"

Copilot's work behind the scenes:
  → Request 1: Read project structure
  → Request 2: Search for "auth" in files  
  → Request 3: Read src/Auth/Provider.php
  → Request 4: Read src/Auth/TokenManager.php
  → Request 5: Read config/auth.yaml
  → Request 6: Search for related tests
  → Request 7: Read Confluence docs about auth flow
  = 7 requests consumed
```

### The Solution (With wRag)

```
You: "How does the authentication work in our Drupal module?"

Copilot's work behind the scenes:
  → Request 1: wRag search_code("authentication") 
    ← Returns: relevant snippets from Provider.php, TokenManager.php, auth.yaml
  → Request 2: wRag search_docs("authentication flow")
    ← Returns: Confluence doc section about auth
  = 2 requests consumed (same quality answer, 70% savings)
```

---

## How Does It Work?

Think of wRag like a **search engine for your own code**. Here's the simple version:

```
┌─────────────────────────────────────────────────────┐
│                    Your Machine                       │
│                                                       │
│   ┌───────────┐    index     ┌──────────────────┐   │
│   │ Your Code │ ──────────→  │  Vector Database  │   │
│   │ + Docs    │              │  (local, fast)    │   │
│   └───────────┘              └────────┬─────────┘   │
│                                       │              │
│                                  query│results       │
│                                       │              │
│   ┌───────────┐   MCP tools   ┌──────┴─────────┐   │
│   │  Copilot  │ ◄───────────► │  wRag Server    │   │
│   └───────────┘               └────────────────┘   │
└─────────────────────────────────────────────────────┘
```

1. **Index** — wRag reads your source code and documentation, breaks them into smart chunks (functions, classes, doc sections), and stores them with semantic embeddings.
2. **Serve** — wRag runs a tiny local server that Copilot talks to via MCP (Model Context Protocol).
3. **Query** — When you ask Copilot a question, it calls wRag to find relevant code instead of reading files one by one.

Everything stays **on your machine**. No code leaves your laptop. No external API needed.

---

## Who Is This For?

| You are... | Benefit |
|------------|---------|
| **Developer with large codebase** | Copilot answers faster and more accurately |
| **Team lead managing AI tool costs** | 60–80% fewer Copilot requests per developer |
| **Developer working with Confluence docs** | Copilot can reference your team's documentation |
| **Anyone hitting Copilot rate limits** | Get more done within your quota |

---

## Real-World Example

Say you work on a Drupal project with 15,000+ files and Confluence documentation:

```bash
# One-time setup (5 minutes)
wrag add connector ~/projects/drupal-connector
wrag add-confluence team-docs --domain myteam.atlassian.net --space DEV
wrag index connector      # indexes 2,400 relevant files → 8,000 chunks
wrag index team-docs      # indexes 150 Confluence pages → 600 chunks
```

Now every time you ask Copilot:
- *"Where is the translation job submitted?"* → wRag returns the exact function in 50ms
- *"What does the API response format look like?"* → wRag returns the Confluence doc section
- *"Find all event subscribers"* → wRag returns all subscriber classes instantly

**Without wRag:** Copilot would use 5–10 requests per question scanning files.  
**With wRag:** Copilot uses 1–2 requests per question querying the index.

Over a typical workday (50+ questions), that's **~300 requests saved per day**.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/pankaj-raundal/wrag.git
cd wrag
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Register Your Project

```bash
wrag add myproject /path/to/your/project
```

### 3. Index It

```bash
wrag index myproject
```

### 4. Connect to VS Code Copilot

Copy the `.vscode/mcp.json` file to your project:

```bash
cp /path/to/wrag/.vscode/mcp.json /path/to/your/project/.vscode/mcp.json
```

Or add to your VS Code user settings (works globally):
```json
{
  "servers": {
    "wrag": {
      "type": "stdio",
      "command": "wrag",
      "args": ["serve"]
    }
  }
}
```

That's it. Copilot now has access to your indexed codebase via 5 search tools.

### 5. (Optional) Auto-Update Index

```bash
wrag watch   # watches for file changes, re-indexes automatically
```

---

## What Copilot Gets

Once connected, Copilot can use these tools automatically:

| Tool | What It Does | Example Use |
|------|-------------|-------------|
| `search_code` | Find relevant code by meaning | *"How does caching work?"* |
| `search_docs` | Search Confluence documentation | *"What's the deployment process?"* |
| `search_symbol` | Find functions/classes by name | *"Find the UserController class"* |
| `list_apps` | See all indexed projects | *"What projects are indexed?"* |
| `app_overview` | Get project statistics | *"How big is the connector project?"* |

---

## Adding Confluence Docs

```bash
# Register your Confluence space
wrag add-confluence docs --domain mycompany.atlassian.net --space DEV --email you@company.com

# Set your API token (generate at https://id.atlassian.com/manage-profile/security/api-tokens)
export CONFLUENCE_API_TOKEN=your_token_here

# Index all pages in that space
wrag index docs
```

---

## All Commands

```
wrag add <name> <path>          Register a local workspace
wrag add-confluence <name>      Register a Confluence space  
wrag remove <name>              Remove a registered source
wrag list                       List all registered sources
wrag index [name]               Index one source (or all if no name given)
wrag index --force              Re-index everything from scratch
wrag status                     Show what's indexed (chunks, files, languages)
wrag search <query>             Quick semantic search from terminal
wrag serve                      Start MCP server (for Copilot)
wrag watch                      Watch files, auto re-index on changes
wrag config                     Show current configuration
```

---

## How It Saves Requests — The Math

| Scenario | Without wRag | With wRag | Savings |
|----------|-------------|-----------|---------|
| Simple code question | 5–8 requests | 1–2 requests | ~75% |
| "Find where X is defined" | 3–6 requests | 1 request | ~80% |
| "Explain this module" | 8–12 requests | 2–3 requests | ~70% |
| Repeated questions (same topic) | Same cost each time | Cached in index, 1 request | ~90% |

**Conservative estimate:** A developer asking 50 questions/day saves **150–250 requests daily**.

---

## Architecture (For the Curious)

```
src/wrag/
├── cli.py              Command-line interface (Click)
├── config.py           YAML config management
├── chunker.py          Smart code splitting (understands Python, PHP, JS/TS syntax)
├── embedder.py         Converts text → vectors (runs locally, no API needed)
├── store.py            LanceDB vector database
├── indexer.py          Orchestrator (walk → chunk → embed → store)
├── mcp_server.py       MCP server (5 tools for Copilot)
├── watcher.py          File change detection (auto re-index)
└── sources/
    ├── workspace.py    Local file system walker
    └── confluence.py   Confluence REST API client
```

**Key design decisions:**
- **All local** — embeddings run on your CPU (no OpenAI key required)
- **Incremental** — only re-indexes files that actually changed (SHA-256 tracking)
- **Language-aware** — splits code at function/class boundaries, not arbitrary line counts
- **Fast** — vector search returns results in <100ms

---

## Configuration

Config lives at `config.yaml` in the wRag directory:

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
  embedding_model: local          # or "openai" if you prefer
  chunk_max_lines: 60
  excluded_dirs: [vendor, node_modules, .git, __pycache__, .venv]
```

---

## Requirements

- Python 3.10+
- ~500MB disk for the embedding model (auto-downloaded on first use)
- No external API keys needed (unless you opt for OpenAI embeddings)

## License

MIT
