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
    <title>wRag — See How AI Gets Smarter Context</title>
    <style>
        :root { --primary: #2563eb; --primary-light: #dbeafe; --bg: #f8fafc; --surface: #fff; --text: #1e293b; --muted: #64748b; --border: #e2e8f0; --green: #16a34a; --red: #dc2626; --orange: #ea580c; --code-bg: #1e293b; --purple: #7c3aed; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; }

        .header { background: linear-gradient(135deg, #1e40af, #7c3aed); color: white; padding: 32px 24px; text-align: center; }
        .header h1 { font-size: 2rem; margin-bottom: 6px; }
        .header p { opacity: 0.9; font-size: 1.05rem; max-width: 600px; margin: 0 auto; }

        .container { max-width: 1000px; margin: 0 auto; padding: 32px 24px; }

        /* Flow Diagram */
        .flow-section { margin-bottom: 36px; }
        .flow-section h2 { font-size: 1.4rem; margin-bottom: 16px; text-align: center; }
        .flow-diagram { display: flex; align-items: center; justify-content: center; gap: 0; flex-wrap: wrap; padding: 20px; background: var(--surface); border-radius: 12px; border: 1px solid var(--border); }
        .flow-step { text-align: center; padding: 12px 16px; min-width: 140px; }
        .flow-step .icon { font-size: 2rem; margin-bottom: 6px; }
        .flow-step .label { font-size: 0.8rem; color: var(--muted); }
        .flow-step .title { font-weight: 700; font-size: 0.9rem; }
        .flow-step.active { background: var(--primary-light); border-radius: 10px; }
        .flow-arrow { font-size: 1.5rem; color: var(--muted); padding: 0 4px; }

        /* Search Section */
        .search-section { background: var(--surface); border-radius: 12px; padding: 28px; border: 1px solid var(--border); margin-bottom: 28px; }
        .search-section h2 { font-size: 1.3rem; margin-bottom: 4px; }
        .search-section .subtitle { color: var(--muted); font-size: 0.9rem; margin-bottom: 16px; }
        .form-row { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
        .form-row input[type="text"] { flex: 1; min-width: 200px; padding: 12px 16px; border: 1px solid var(--border); border-radius: 8px; font-size: 1rem; }
        .form-row select { padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px; font-size: 0.9rem; background: white; }
        .form-row button { padding: 12px 28px; background: var(--primary); color: white; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        .form-row button:hover { background: #1d4ed8; }

        /* Step-by-step explanation after search */
        .explanation { margin-bottom: 28px; }
        .explanation h3 { font-size: 1.1rem; margin-bottom: 12px; color: var(--primary); }
        .step-list { list-style: none; }
        .step-list li { padding: 10px 14px; margin-bottom: 8px; border-radius: 8px; border-left: 4px solid var(--border); background: var(--surface); font-size: 0.92rem; }
        .step-list li.done { border-left-color: var(--green); background: #f0fdf4; }
        .step-list li .step-num { display: inline-block; width: 24px; height: 24px; border-radius: 50%; background: var(--green); color: white; text-align: center; line-height: 24px; font-size: 0.75rem; font-weight: 700; margin-right: 8px; }
        .step-list li .step-detail { color: var(--muted); font-size: 0.82rem; display: block; margin-top: 4px; margin-left: 32px; }

        /* Comparison */
        .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 28px; }
        @media (max-width: 700px) { .comparison { grid-template-columns: 1fr; } }
        .compare-card { background: var(--surface); border-radius: 12px; padding: 20px; border: 1px solid var(--border); }
        .compare-card.without { border-top: 4px solid var(--red); }
        .compare-card.with { border-top: 4px solid var(--green); }
        .compare-card h4 { margin-bottom: 8px; font-size: 1rem; }
        .compare-card .cost { font-size: 1.8rem; font-weight: 800; margin: 8px 0; }
        .compare-card .cost.red { color: var(--red); }
        .compare-card .cost.green { color: var(--green); }
        .compare-card .detail { font-size: 0.85rem; color: var(--muted); }

        /* Results */
        .results-section h3 { font-size: 1.1rem; margin-bottom: 4px; }
        .results-section .results-subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 14px; }
        .result { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; overflow: hidden; }
        .result-header { padding: 12px 16px; background: #f1f5f9; border-bottom: 1px solid var(--border); font-size: 0.85rem; color: var(--muted); display: flex; justify-content: space-between; align-items: center; }
        .result-header strong { color: var(--text); font-size: 0.92rem; }
        .result-header .badge { background: var(--primary-light); color: var(--primary); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
        .result-body { padding: 16px; }
        .result-body pre { background: var(--code-bg); color: #e2e8f0; padding: 14px; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; line-height: 1.5; white-space: pre-wrap; max-height: 200px; }
        .meta { font-size: 0.78rem; color: var(--muted); margin-bottom: 8px; }

        /* Stats */
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; }
        .stat-card .value { font-size: 1.8rem; font-weight: 800; color: var(--primary); }
        .stat-card .value.green { color: var(--green); }
        .stat-card .label { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }

        .empty { text-align: center; color: var(--muted); padding: 40px; }
        .spinner { display: none; text-align: center; padding: 30px; color: var(--muted); font-size: 1.1rem; }
        .spinner.active { display: block; }
        .hidden { display: none; }

        /* How it works explainer */
        .explainer { background: linear-gradient(135deg, #eff6ff, #f5f3ff); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 28px; }
        .explainer h3 { font-size: 1.1rem; margin-bottom: 12px; }
        .explainer p { font-size: 0.92rem; color: var(--text); margin-bottom: 8px; }
        .explainer .highlight { background: #fef3c7; padding: 2px 6px; border-radius: 4px; font-weight: 600; }
    </style>
</head>
<body>
    <div class="header">
        <h1>wRag — Query Simulator</h1>
        <p>See exactly how your AI assistant uses pre-indexed knowledge instead of scanning files one by one</p>
    </div>

    <div class="container">

        <!-- How it works (always visible) -->
        <div class="explainer">
            <h3>What happens when you ask Copilot a question?</h3>
            <p><strong>Without wRag:</strong> Copilot reads your project folder, opens files one by one, runs searches — each action costs a <span class="highlight">request</span> from your quota.</p>
            <p><strong>With wRag:</strong> Copilot asks wRag "find me relevant code about X" → wRag instantly returns the right snippets from its pre-built index → Copilot uses those snippets to answer. <span class="highlight">1 call instead of 5-15.</span></p>
        </div>

        <!-- Flow Diagram -->
        <div class="flow-section">
            <h2>The Flow (Step by Step)</h2>
            <div class="flow-diagram" id="flowDiagram">
                <div class="flow-step" id="flow-1">
                    <div class="icon">💬</div>
                    <div class="title">Your Question</div>
                    <div class="label">You type a prompt</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="flow-step" id="flow-2">
                    <div class="icon">🤖</div>
                    <div class="title">Copilot Thinks</div>
                    <div class="label">"I need context about this"</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="flow-step" id="flow-3">
                    <div class="icon">🔍</div>
                    <div class="title">wRag Search</div>
                    <div class="label">Finds relevant code instantly</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="flow-step" id="flow-4">
                    <div class="icon">📋</div>
                    <div class="title">Context Injected</div>
                    <div class="label">Code snippets added to prompt</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="flow-step" id="flow-5">
                    <div class="icon">✅</div>
                    <div class="title">Answer</div>
                    <div class="label">Copilot responds with knowledge</div>
                </div>
            </div>
        </div>

        <!-- Search Box -->
        <div class="search-section">
            <h2>Try It — Simulate a Copilot Query</h2>
            <p class="subtitle">Type the same question you'd ask Copilot. We'll show you what happens behind the scenes.</p>
            <form id="searchForm">
                <div class="form-row">
                    <input type="text" id="query" name="query" placeholder="e.g. How does auto-bundling work in this module?" autofocus>
                    <select id="tool" name="tool">
                        <option value="search_code">Code Search</option>
                        <option value="search_docs">Docs Search</option>
                        <option value="search_symbol">Symbol Lookup</option>
                    </select>
                    <select id="app_name" name="app_name">
                        <option value="">All Projects</option>
                    </select>
                    <button type="submit">Simulate →</button>
                </div>
            </form>
        </div>

        <div class="spinner" id="spinner">🔍 Searching the index...</div>

        <!-- After search: step-by-step explanation -->
        <div id="postSearch" class="hidden">

            <!-- Step by step what happened -->
            <div class="explanation">
                <h3>Here's what just happened (what Copilot does behind the scenes):</h3>
                <ol class="step-list" id="stepList"></ol>
            </div>

            <!-- Cost comparison -->
            <div class="comparison" id="comparison"></div>

            <!-- The actual context Copilot receives -->
            <div class="results-section">
                <h3>📋 The Context Copilot Receives</h3>
                <p class="results-subtitle">These code snippets get injected into Copilot's prompt. It reads these instead of opening files individually.</p>
                <div id="results"></div>
            </div>
        </div>

        <!-- Cumulative stats -->
        <div style="margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px;">
            <h3 style="text-align: center; margin-bottom: 16px; color: var(--muted);">Session Statistics (All Queries)</h3>
            <div class="stats-grid" id="statsGrid"></div>
        </div>

        <!-- Real Benchmark Data -->
        <div style="margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px;" id="benchmarkSection" class="hidden">
            <h3 style="text-align: center; margin-bottom: 6px;">Real Measured Results</h3>
            <p style="text-align: center; color: var(--muted); font-size: 0.85rem; margin-bottom: 16px;">Actual Copilot usage counter readings — same prompts tested with and without wRag</p>
            <div id="benchmarkContent"></div>
        </div>

        <!-- OTel Real Token Savings -->
        <div style="margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px;" id="tokenSection" class="hidden">
            <h3 style="text-align: center; margin-bottom: 6px;">Real Token Savings <span style="font-size:0.75rem;background:var(--primary);color:white;padding:2px 8px;border-radius:99px;vertical-align:middle;">OpenTelemetry</span></h3>
            <p style="text-align: center; color: var(--muted); font-size: 0.85rem; margin-bottom: 16px;">Actual LLM token counts from VS Code OTel traces — sessions with wRag vs without</p>
            <div id="tokenContent"></div>
        </div>

        <div id="tokenSetupNotice" class="hidden" style="margin-top: 24px; background: var(--surface); border: 1px dashed var(--border); border-radius: 12px; padding: 20px; text-align: center;">
            <p style="color: var(--muted); margin: 0 0 10px;">OTel not yet configured. Add to <code>dconnector933/.vscode/settings.json</code>:</p>
            <pre style="text-align:left;background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:8px;font-size:0.8rem;display:inline-block;">"github.copilot.chat.otel.enabled": true,
"github.copilot.chat.otel.exporterType": "file",
"github.copilot.chat.otel.outfile": ".../.data/copilot-otel.jsonl"</pre>
            <p style="color: var(--muted); margin: 10px 0 0; font-size: 0.8rem;">Then reload VS Code window and ask Copilot questions to generate real token data.</p>
        </div>

    </div>

    <script>
        // Load apps
        fetch('/api/apps').then(r => r.json()).then(data => {
            const sel = document.getElementById('app_name');
            data.apps.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a; opt.textContent = a;
                sel.appendChild(opt);
            });
        });

        function loadStats() {
            fetch('/api/stats').then(r => r.json()).then(data => {
                const grid = document.getElementById('statsGrid');
                const saved = data.total * 3;
                grid.innerHTML = `
                    <div class="stat-card"><div class="value">${data.total}</div><div class="label">wRag Calls Made</div></div>
                    <div class="stat-card"><div class="value">${data.total_results}</div><div class="label">Code Snippets Served</div></div>
                    <div class="stat-card"><div class="value">${data.total * 4}</div><div class="label">Would Cost Without wRag</div></div>
                    <div class="stat-card"><div class="value green">${Math.round((1 - data.total / Math.max(data.total * 4, 1)) * 100)}%</div><div class="label">Requests Saved</div></div>
                `;
            });

            // Load real benchmark data
            fetch('/api/benchmark').then(r => r.json()).then(data => {
                if (data.count === 0) return;
                const section = document.getElementById('benchmarkSection');
                section.classList.remove('hidden');

                let html = `<table style="width:100%;border-collapse:collapse;background:var(--surface);border-radius:12px;overflow:hidden;border:1px solid var(--border);">
                    <thead><tr style="background:var(--primary);color:white;">
                        <th style="padding:12px;text-align:left;">Prompt</th>
                        <th style="padding:12px;text-align:center;">Without wRag</th>
                        <th style="padding:12px;text-align:center;">With wRag</th>
                        <th style="padding:12px;text-align:center;">Saved</th>
                    </tr></thead><tbody>`;

                data.tests.forEach(t => {
                    const pct = t.savings.percentage;
                    html += `<tr style="border-bottom:1px solid var(--border);">
                        <td style="padding:12px;font-size:0.9rem;">${escapeHtml(t.prompt.substring(0, 50))}${t.prompt.length > 50 ? '...' : ''}</td>
                        <td style="padding:12px;text-align:center;color:var(--red);font-weight:700;">${t.without_wrag.requests} req<br><span style="font-size:0.75rem;font-weight:400;">${t.without_wrag.tool_calls} tool calls</span></td>
                        <td style="padding:12px;text-align:center;color:var(--green);font-weight:700;">${t.with_wrag.requests} req<br><span style="font-size:0.75rem;font-weight:400;">${t.with_wrag.tool_calls} tool calls</span></td>
                        <td style="padding:12px;text-align:center;font-weight:800;color:var(--green);">${pct}%</td>
                    </tr>`;
                });

                html += `</tbody></table>`;

                // Summary bar
                const totals = data.totals;
                html += `<div style="display:flex;gap:16px;margin-top:16px;justify-content:center;flex-wrap:wrap;">
                    <div class="stat-card" style="flex:1;min-width:150px;"><div class="value" style="color:var(--red);">${totals.without_wrag_requests}</div><div class="label">Total Requests (Without)</div></div>
                    <div class="stat-card" style="flex:1;min-width:150px;"><div class="value green">${totals.with_wrag_requests}</div><div class="label">Total Requests (With wRag)</div></div>
                    <div class="stat-card" style="flex:1;min-width:150px;"><div class="value green">${totals.total_saved}</div><div class="label">Total Requests Saved</div></div>
                    <div class="stat-card" style="flex:1;min-width:150px;"><div class="value green">${totals.average_savings_percent}%</div><div class="label">Average Savings</div></div>
                </div>`;

                document.getElementById('benchmarkContent').innerHTML = html;
            });

            // Load OTel real token data
            fetch('/api/tokens').then(r => r.json()).then(data => {
                if (!data.otel_enabled) {
                    document.getElementById('tokenSetupNotice').classList.remove('hidden');
                    return;
                }
                if (!data.has_data) return;

                document.getElementById('tokenSection').classList.remove('hidden');
                const savings = data.savings;
                let html = '';

                if (savings.baseline_sessions > 0 && savings.wrag_sessions > 0) {
                    html += `<div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:20px;">
                        <div class="stat-card" style="flex:1;min-width:140px;"><div class="value" style="color:var(--red);">${savings.baseline_avg_input_tokens.toLocaleString()}</div><div class="label">Avg Input Tokens<br>(Without wRag)</div></div>
                        <div class="stat-card" style="flex:1;min-width:140px;"><div class="value green">${savings.wrag_avg_input_tokens.toLocaleString()}</div><div class="label">Avg Input Tokens<br>(With wRag)</div></div>
                        <div class="stat-card" style="flex:1;min-width:140px;"><div class="value green">${savings.input_token_reduction_pct}%</div><div class="label">Input Token<br>Reduction</div></div>
                        <div class="stat-card" style="flex:1;min-width:140px;"><div class="value green">${savings.total_input_tokens_saved.toLocaleString()}</div><div class="label">Total Input Tokens<br>Saved</div></div>
                    </div>`;
                } else {
                    html += `<p style="text-align:center;color:var(--muted);">Need sessions both with and without wRag to compare. ${data.wrag_session_count} wRag sessions, ${data.baseline_session_count} baseline sessions recorded.</p>`;
                }

                // Per-session table
                if (data.per_session && data.per_session.length > 0) {
                    html += `<table style="width:100%;border-collapse:collapse;background:var(--surface);border-radius:12px;overflow:hidden;border:1px solid var(--border);">
                        <thead><tr style="background:var(--primary);color:white;">
                            <th style="padding:10px;text-align:left;">Session</th>
                            <th style="padding:10px;text-align:center;">wRag</th>
                            <th style="padding:10px;text-align:right;">Input Tokens</th>
                            <th style="padding:10px;text-align:right;">Output Tokens</th>
                            <th style="padding:10px;text-align:center;">wRag Calls</th>
                            <th style="padding:10px;text-align:center;">Native Calls</th>
                        </tr></thead><tbody>`;

                    data.per_session.slice(-15).forEach(s => {
                        html += `<tr style="border-bottom:1px solid var(--border);">
                            <td style="padding:8px 10px;font-family:monospace;font-size:0.8rem;">${s.conversation_id}</td>
                            <td style="padding:8px 10px;text-align:center;">${s.used_wrag ? '<span style="color:var(--green);">✓</span>' : '<span style="color:var(--red);">✗</span>'}</td>
                            <td style="padding:8px 10px;text-align:right;${s.used_wrag ? 'color:var(--green)' : 'color:var(--red)'};">${s.input_tokens.toLocaleString()}</td>
                            <td style="padding:8px 10px;text-align:right;">${s.output_tokens.toLocaleString()}</td>
                            <td style="padding:8px 10px;text-align:center;color:var(--green);">${s.wrag_tool_calls}</td>
                            <td style="padding:8px 10px;text-align:center;color:var(--red);">${s.native_tool_calls}</td>
                        </tr>`;
                    });
                    html += '</tbody></table>';
                }

                document.getElementById('tokenContent').innerHTML = html;
            }).catch(() => {
                document.getElementById('tokenSetupNotice').classList.remove('hidden');
            });
        }
        loadStats();

        // Animate flow steps
        function animateFlow(step) {
            for (let i = 1; i <= 5; i++) {
                document.getElementById('flow-' + i).classList.remove('active');
            }
            if (step >= 1 && step <= 5) {
                document.getElementById('flow-' + step).classList.add('active');
            }
        }

        // Search
        document.getElementById('searchForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const query = document.getElementById('query').value.trim();
            if (!query) return;

            const tool = document.getElementById('tool').value;
            const app = document.getElementById('app_name').value;
            const postSearch = document.getElementById('postSearch');
            const spinner = document.getElementById('spinner');

            postSearch.classList.add('hidden');
            spinner.classList.add('active');

            // Animate: step 1
            animateFlow(1);
            setTimeout(() => animateFlow(2), 400);
            setTimeout(() => animateFlow(3), 800);

            const start = performance.now();
            fetch(`/api/search?query=${encodeURIComponent(query)}&tool=${tool}&app_name=${app}&top_k=10`)
                .then(r => r.json())
                .then(data => {
                    const elapsed = ((performance.now() - start) / 1000).toFixed(2);
                    spinner.classList.remove('active');
                    postSearch.classList.remove('hidden');

                    // Animate: step 4, 5
                    animateFlow(4);
                    setTimeout(() => animateFlow(5), 600);

                    // Build step-by-step explanation
                    const toolLabel = tool === 'search_code' ? 'code search' : tool === 'search_docs' ? 'documentation search' : 'symbol lookup';
                    const stepList = document.getElementById('stepList');
                    stepList.innerHTML = `
                        <li class="done"><span class="step-num">1</span><strong>You asked:</strong> "${escapeHtml(query)}"
                            <span class="step-detail">This is your original prompt to Copilot.</span></li>
                        <li class="done"><span class="step-num">2</span><strong>Copilot decides:</strong> "I need ${toolLabel} for this"
                            <span class="step-detail">The AI determines the best tool to find relevant context.</span></li>
                        <li class="done"><span class="step-num">3</span><strong>wRag searched:</strong> Found ${data.results.length} relevant snippets in ${elapsed}s
                            <span class="step-detail">Vector similarity search across ${app || 'all'} indexed projects. No files opened, no folders scanned.</span></li>
                        <li class="done"><span class="step-num">4</span><strong>Context injected:</strong> ${data.results.length} code blocks added to Copilot's prompt
                            <span class="step-detail">Copilot now has targeted knowledge. It reads ONLY these snippets (shown below), not the whole project.</span></li>
                        <li class="done"><span class="step-num">5</span><strong>Copilot answers:</strong> Uses the context above to give you an informed response
                            <span class="step-detail">The answer is grounded in real code from your project — accurate and specific.</span></li>
                    `;

                    // Cost comparison
                    const withoutCost = Math.max(data.results.length + 3, 6); // file reads + searches + structure
                    const withCost = 1; // single wRag call
                    const savings = Math.round((1 - withCost / withoutCost) * 100);
                    document.getElementById('comparison').innerHTML = `
                        <div class="compare-card without">
                            <h4>❌ Without wRag</h4>
                            <div class="cost red">~${withoutCost} requests</div>
                            <div class="detail">Copilot would: list directory → read ${data.results.length} files → search for keywords → read related files</div>
                        </div>
                        <div class="compare-card with">
                            <h4>✅ With wRag</h4>
                            <div class="cost green">${withCost} request</div>
                            <div class="detail">Copilot calls wRag once → gets all ${data.results.length} relevant snippets instantly (${elapsed}s)</div>
                            <div style="margin-top:8px;font-weight:700;color:var(--green);">Saved: ${savings}% fewer requests</div>
                        </div>
                    `;

                    // Results
                    const resultsDiv = document.getElementById('results');
                    if (data.results.length === 0) {
                        resultsDiv.innerHTML = '<div class="empty">No results found for this query. Try rephrasing or check indexing.</div>';
                        return;
                    }

                    resultsDiv.innerHTML = data.results.map((r, i) => {
                        const header = tool === 'search_docs'
                            ? `<strong>${r.symbol_name}</strong>`
                            : `<strong>${r.path}</strong>:${r.start_line}-${r.end_line}`;
                        const badge = r.symbol_type || 'chunk';
                        const meta = `${r.app_name} | ${r.language} | ${r.symbol_type}: ${r.symbol_name}` +
                            (r.score !== undefined ? ` | relevance: ${(1 - r.score).toFixed(2)}` : '');
                        return `<div class="result">
                            <div class="result-header"><span>#${i+1} ${header}</span><span class="badge">${badge}</span></div>
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
                    document.getElementById('results').innerHTML = `<div class="empty">Error: ${err.message}</div>`;
                    postSearch.classList.remove('hidden');
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
        elif path == "/api/benchmark":
            self._handle_benchmark()
        elif path == "/api/tokens":
            self._handle_tokens()
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

    def _handle_benchmark(self):
        from wrag.benchmark import get_benchmark_summary
        self._respond(200, get_benchmark_summary())

    def _handle_tokens(self):
        from wrag.otel_analyzer import get_token_summary
        self._respond(200, get_token_summary())

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
