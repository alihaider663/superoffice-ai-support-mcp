"""Lightweight visual web dashboard for Pre-Flight Health-Check verification."""

from __future__ import annotations

import asyncio
import webbrowser

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from platform_core.preflight.engine import run_preflight_probes

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SuperOffice AI Support MCP — Pre-Flight Health Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --green: #22c55e;
      --green-bg: rgba(34, 197, 94, 0.15);
      --yellow: #eab308;
      --yellow-bg: rgba(234, 179, 8, 0.15);
      --red: #ef4444;
      --red-bg: rgba(239, 68, 68, 0.15);
      --cyan: #06b6d4;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        Roboto, Helvetica, Arial, sans-serif;
    }
    body { background-color: var(--bg); color: var(--text); padding: 2rem; min-height: 100vh; }
    .container { max-width: 1100px; margin: 0 auto; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
    }
    h1 { font-size: 1.5rem; font-weight: 700; color: var(--cyan); }
    .subtitle { font-size: 0.875rem; color: var(--muted); margin-top: 0.25rem; }
    .btn-rerun {
      background: var(--cyan);
      color: #000;
      border: none;
      padding: 0.6rem 1.2rem;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      transition: opacity 0.2s;
    }
    .btn-rerun:hover { opacity: 0.9; }
    .status-banner {
      padding: 1.25rem;
      border-radius: 8px;
      margin-bottom: 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border: 1px solid transparent;
    }
    .status-banner.ready {
      background: var(--green-bg);
      border-color: var(--green);
      color: var(--green);
    }
    .status-banner.not-ready {
      background: var(--red-bg);
      border-color: var(--red);
      color: var(--red);
    }
    .banner-title { font-size: 1.25rem; font-weight: 700; }
    .banner-subtitle { font-size: 0.875rem; color: var(--muted); margin-top: 0.25rem; }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .metric-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      padding: 1rem;
      border-radius: 8px;
      text-align: center;
    }
    .metric-val { font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }
    .metric-val.green { color: var(--green); }
    .metric-val.yellow { color: var(--yellow); }
    .metric-val.red { color: var(--red); }
    .metric-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0.05em;
    }
    .category-section { margin-bottom: 1.75rem; }
    .category-title {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--cyan);
      margin-bottom: 0.75rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .probe-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem 1.25rem;
      margin-bottom: 0.75rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .probe-info { flex: 1; }
    .probe-name { font-weight: 600; font-size: 0.95rem; margin-bottom: 0.25rem; }
    .probe-msg { font-size: 0.85rem; color: var(--muted); }
    .probe-meta { display: flex; align-items: center; gap: 1rem; }
    .latency { font-size: 0.8rem; color: var(--muted); font-family: monospace; }
    .badge {
      padding: 0.25rem 0.65rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .badge.success {
      background: var(--green-bg);
      color: var(--green);
      border: 1px solid var(--green);
    }
    .badge.warning {
      background: var(--yellow-bg);
      color: var(--yellow);
      border: 1px solid var(--yellow);
    }
    .badge.failure {
      background: var(--red-bg);
      color: var(--red);
      border: 1px solid var(--red);
    }
    .badge.skipped {
      background: rgba(148, 163, 184, 0.15);
      color: var(--muted);
      border: 1px solid var(--muted);
    }
    footer {
      text-align: center;
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 3rem;
      padding-top: 1rem;
      border-top: 1px solid var(--border);
    }
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid #000;
      border-radius: 50%;
      border-top-color: transparent;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>SuperOffice AI Support MCP Platform</h1>
        <div class="subtitle">System Pre-Flight Health & Connectivity Probes</div>
      </div>
      <button class="btn-rerun" id="rerun-btn" onclick="fetchProbes()">
        <span id="btn-icon">&#x21bb;</span> Re-run Probes
      </button>
    </header>

    <div id="status-banner" class="status-banner ready">
      <div>
        <div class="banner-title" id="banner-title">Executing Probes...</div>
        <div class="banner-subtitle" id="banner-subtitle">
          Connecting to local and remote backends...
        </div>
      </div>
      <div id="banner-badge" class="badge success">INITIALIZING</div>
    </div>

    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Passed Checks</div>
        <div class="metric-val green" id="metric-passed">0</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Warnings</div>
        <div class="metric-val yellow" id="metric-warn">0</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Failures</div>
        <div class="metric-val red" id="metric-fail">0</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Duration</div>
        <div class="metric-val" id="metric-time">0ms</div>
      </div>
    </div>

    <div id="probes-container">
      <!-- Dynamically generated probe cards grouped by category -->
    </div>

    <footer>
      SuperOffice AI Support MCP Platform &bull;
      Local Pre-Flight Diagnostic Dashboard &bull; Read-Only Probes
    </footer>
  </div>

  <script>
    async function fetchProbes() {
      const btn = document.getElementById('rerun-btn');
      btn.innerHTML = '<span class="spinner"></span> Probing...';
      btn.disabled = true;

      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        renderDashboard(data);
      } catch (err) {
        alert('Failed to execute diagnostic probes: ' + err);
      } finally {
        btn.innerHTML = '<span>&#x21bb;</span> Re-run Probes';
        btn.disabled = false;
      }
    }

    function renderDashboard(data) {
      document.getElementById('metric-passed').textContent = data.passed_count;
      document.getElementById('metric-warn').textContent = data.warning_count;
      document.getElementById('metric-fail').textContent = data.failure_count;
      document.getElementById('metric-time').textContent = data.total_duration_ms + 'ms';

      const banner = document.getElementById('status-banner');
      const bTitle = document.getElementById('banner-title');
      const bSub = document.getElementById('banner-subtitle');
      const bBadge = document.getElementById('banner-badge');

      if (data.ready_to_launch) {
        banner.className = 'status-banner ready';
        bTitle.textContent = 'SYSTEM READY FOR PLATFORM LAUNCH';
        bSub.textContent =
          'All critical backend connections, app servers, and database configurations verified.';
        bBadge.className = 'badge success';
        bBadge.textContent = 'PASSED';
      } else {
        banner.className = 'status-banner not-ready';
        bTitle.textContent = 'ACTION REQUIRED: BACKEND ISSUES DETECTED';
        bSub.textContent =
          'One or more critical dependencies failed. ' +
          'Resolve blocking issues before starting MCP services.';
        bBadge.className = 'badge failure';
        bBadge.textContent = 'FAILED';
      }

      // Group by category
      const categories = {};
      data.results.forEach(r => {
        if (!categories[r.category]) categories[r.category] = [];
        categories[r.category].push(r);
      });

      const container = document.getElementById('probes-container');
      container.innerHTML = '';

      for (const [cat, items] of Object.entries(categories)) {
        const section = document.createElement('div');
        section.className = 'category-section';

        const title = document.createElement('div');
        title.className = 'category-title';
        title.textContent = cat;
        section.appendChild(title);

        items.forEach(item => {
          const card = document.createElement('div');
          card.className = 'probe-card';

          const info = document.createElement('div');
          info.className = 'probe-info';

          const name = document.createElement('div');
          name.className = 'probe-name';
          name.textContent = item.name;

          const msg = document.createElement('div');
          msg.className = 'probe-msg';
          msg.textContent = item.message;

          info.appendChild(name);
          info.appendChild(msg);

          const meta = document.createElement('div');
          meta.className = 'probe-meta';

          if (item.latency_ms > 0) {
            const lat = document.createElement('div');
            lat.className = 'latency';
            lat.textContent = item.latency_ms + ' ms';
            meta.appendChild(lat);
          }

          const badge = document.createElement('div');
          badge.className = 'badge ' + item.status;
          badge.textContent = item.status;
          meta.appendChild(badge);

          card.appendChild(info);
          card.appendChild(meta);
          section.appendChild(card);
        });

        container.appendChild(section);
      }
    }

    // Auto-fetch on load
    window.addEventListener('DOMContentLoaded', fetchProbes);
  </script>
</body>
</html>
"""


async def get_dashboard(_request) -> HTMLResponse:
    """Serve the single-page visual dashboard HTML."""
    return HTMLResponse(content=DASHBOARD_HTML)


async def get_status_api(_request) -> JSONResponse:
    """Execute live diagnostic probes and return JSON report."""
    report = await run_preflight_probes()
    return JSONResponse(content=report.model_dump(mode="json"))


def create_preflight_gui_app() -> Starlette:
    """Instantiate Starlette application for preflight dashboard."""
    routes = [
        Route("/", endpoint=get_dashboard, methods=["GET"]),
        Route("/api/status", endpoint=get_status_api, methods=["GET"]),
    ]
    return Starlette(routes=routes)


def start_gui(host: str = "127.0.0.1", port: int = 8088, auto_open: bool = True) -> None:
    """Start local GUI dashboard web server and launch default browser."""
    app = create_preflight_gui_app()
    url = f"http://{host}:{port}"
    print(f"\n[+] Launching Pre-Flight Visual Dashboard at {url}...")

    if auto_open:

        async def _open_browser() -> None:
            await asyncio.sleep(0.5)
            webbrowser.open(url)

        asyncio.get_event_loop_policy().get_event_loop().create_task(_open_browser())

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_gui()
