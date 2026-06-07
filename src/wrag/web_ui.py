"""Web UI for wRag — preview search results, test queries, view stats."""

from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from wrag import store
from wrag.config import load_config
from wrag.embedder import get_embedder
from wrag.mcp_server import get_request_stats, _STATS_FILE


def _embed_query(text: str) -> list[float]:
    """Embed a query string."""
    cfg = load_config()
    embedder = get_embedder(cfg.settings)
    return embedder.embed([text])[0]


def _search(query: str, tool: str, app_name: str, top_k: int) -> list[dict]:
    """Run a search and return results."""
    if tool == "search_symbol":
        return store.search_symbol(name=query, app_name=app_name or None)

    vector = _embed_query(query)
    source_type = "confluence" if tool == "search_docs" else "workspace"
    return store.search(
        query_vector=vector,
        app_name=app_name or None,
        top_k=top_k,
        source_type=source_type,
    )


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>wRag — Query Preview</title>
    <style>
        :root { --primary: #2563eb; --bg: #f8fafc; --surface: #fff; --text: #1e293b; --muted: #64748b; --border: #e2e8f0; --green: #16a34a; --code-bg: #1e293b; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
        .header { background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; padding: 24px; text-align: center; }
        .header h1 { font-size: 1.8rem; margin-bottom: 4px; }
        .header p { opacity: 0.85; font-size: 0.95rem; }
        .container { max-width: 960px; margin: 0 auto; padding: 24px; }
        .search-box { background: var(--surface); border-radius: 12px; padding: 24px; border: 1px solid var(--border); margin-bottom: 24px; }
        .form-row { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
        .form-row input[type="text"] { flex: 1; min-width: 200px; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 1rem; }
        .form-row select { padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 0.9rem; background: white; }
        .form-row button { padding: 10px 24px; background: var(--primary); color: white; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; }
        .form-row button:hover { background: #1d4ed8; }
        .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
        .tab { padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9rem; border: 1px solid var(--border); background: var(--surface); }
        .tab.active { background: var(--primary); color: white; border-color: var(--primary); }
        .result { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; overflow: hidden; }
        .result-header { padding: 12px 16px; background: #f1f5f9; border-bottom: 1px solid var(--border); font-size: 0.85rem; color: var(--muted); }
        .result-header strong { color: var(--text); font-size: 0.95rem; }
        .result-body { padding: 16px; }
        .result-body pre { background: var(--code-bg); color: #e2e8f0; padding: 14px; border-radius: 8px; overflow-x: auto; font-size: 0.82rem; line-height: 1.5; white-space: pre-wrap; }
        .meta { font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; }
        .stat-card .value { font-size: 2rem; font-weight: 800; color: var(--primary); }
        .stat-card .label { font-size: 0.85rem; color: var(--muted); }
        .info-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-bottom: 16px; font-size: 0.9rem; }
        .info-box strong { color: var(--green); }
        .empty { text-align: center; color: var(--muted); padding: 40px; }
        .timing { font-size: 0.8rem; color: var(--muted); margin-top: 8px; }
        #results { min-height: 100px; }
        .spinner { display: none; text-align: center; padding: 30px; color: var(--muted); }
        .spinner.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <h1>wRag Query Preview</h1>
        <p>Test queries and see exactly what Copilot receives from wRag</p>
    </div>
    <div class="container">
        <div class="search-box">
            <form id="searchForm">
                <div class="form-row">
                    <input type="text" id="query" name="query" placeholder="Type your query... (e.g. 'how does auto-bundling work')" autofocus>
                    <select id="tool" name="tool">
                        <option value="search_code">search_code</option>
                        <option value="search_docs">search_docs</option>
                        <option value="search_symbol">search_symbol</option>
                    </select>
                    <select id="app_name" name="app_name">
                        <option value="">All apps</option>
                        <!-- filled dynamically -->
                    </select>
                    <button type="submit">Search</button>
                </div>
            </form>
            <div class="info-box">
                <strong>How to use:</strong> Type the same prompt you'd ask Copilot. This shows the chunks wRag would return — the exact context Copilot uses instead of scanning files.
            </div>
        </div>

        <div id="statsSection">
            <div class="stats-grid" id="statsGrid"></div>
        </div>

        <div class="spinner" id="spinner">Searching...</div>
        <div id="results"></div>
        <div class="timing" id="timing"></div>
    </div>

    <script>
        // Load apps on page load
        fetch('/api/apps').then(r => r.json()).then(data => {
            const sel = document.getElementById('app_name');
            data.apps.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a; opt.textContent = a;
                sel.appendChild(opt);
            });
        });

        // Load stats
        function loadStats() {
            fetch('/api/stats').then(r => r.json()).then(data => {
                const grid = document.getElementById('statsGrid');
                grid.innerHTML = `
                    <div class="stat-card"><div class="value">${data.total}</div><div class="label">Total Tool Calls</div></div>
                    <div class="stat-card"><div class="value">${data.total_results}</div><div class="label">Results Returned</div></div>
                    <div class="stat-card"><div class="value">${data.total * 4}</div><div class="label">Estimated Native Requests</div></div>
                    <div class="stat-card"><div class="value">${Math.round((1 - data.total / Math.max(data.total * 4, 1)) * 100)}%</div><div class="label">Savings</div></div>
                `;
            });
        }
        loadStats();

        // Search
        document.getElementById('searchForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const query = document.getElementById('query').value.trim();
            if (!query) return;

            const tool = document.getElementById('tool').value;
            const app = document.getElementById('app_name').value;
            const resultsDiv = document.getElementById('results');
            const spinner = document.getElementById('spinner');
            const timing = document.getElementById('timing');

            spinner.classList.add('active');
            resultsDiv.innerHTML = '';
            timing.textContent = '';

            const start = performance.now();
            fetch(`/api/search?query=${encodeURIComponent(query)}&tool=${tool}&app_name=${app}&top_k=10`)
                .then(r => r.json())
                .then(data => {
                    spinner.classList.remove('active');
                    const elapsed = ((performance.now() - start) / 1000).toFixed(2);
                    timing.textContent = `${data.results.length} results in ${elapsed}s`;

                    if (data.results.length === 0) {
                        resultsDiv.innerHTML = '<div class="empty">No results found. Try a different query or check that the app is indexed.</div>';
                        return;
                    }

                    resultsDiv.innerHTML = data.results.map((r, i) => {
                        const header = tool === 'search_docs'
                            ? `<strong>${r.symbol_name}</strong> — ${r.path}`
                            : `<strong>${r.path}</strong>:${r.start_line}-${r.end_line}`;
                        const meta = `${r.app_name} | ${r.language} | ${r.symbol_type}: ${r.symbol_name}` +
                            (r.score !== undefined ? ` | distance: ${r.score.toFixed(4)}` : '');
                        return `<div class="result">
                            <div class="result-header">#${i+1} ${header}</div>
                            <div class="result-body">
                                <div class="meta">${meta}</div>
                                <pre>${escapeHtml(r.text)}</pre>
                            </div>
                        </div>`;
                    }).join('');

                    loadStats();
                })
                .catch(err => {
                    spinner.classList.remove('active');
                    resultsDiv.innerHTML = `<div class="empty">Error: ${err.message}</div>`;
                });
        });

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>"""


class WragUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the preview UI."""

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/search":
            self._handle_search(params)
        elif path == "/api/apps":
            self._handle_apps()
        elif path == "/api/stats":
            self._handle_stats()
        else:
            self._respond(404, {"error": "Not found"})

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _handle_search(self, params):
        query = params.get("query", [""])[0]
        tool = params.get("tool", ["search_code"])[0]
        app_name = params.get("app_name", [""])[0]
        top_k = int(params.get("top_k", ["10"])[0])

        if not query:
            self._respond(400, {"error": "query parameter required"})
            return

        try:
            results = _search(query, tool, app_name, top_k)
            self._respond(200, {"query": query, "tool": tool, "results": results})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _handle_apps(self):
        cfg = load_config()
        apps = cfg.all_source_names()
        self._respond(200, {"apps": apps})

    def _handle_stats(self):
        stats = get_request_stats()
        # Add total chunks count (fast operation)
        stats["total_chunks"] = store.total_chunks()
        self._respond(200, stats)

    def _respond(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))


def run_ui(port: int = 8787):
    """Start the web UI server."""
    server = HTTPServer(("0.0.0.0", port), WragUIHandler)
    print(f"wRag UI running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nUI server stopped.")
