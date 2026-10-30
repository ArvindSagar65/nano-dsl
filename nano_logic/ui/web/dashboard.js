/* ============================================================
   nano-dsl Web Observability Dashboard — Logic & Realtime Engine
   ============================================================ */

(function () {
  'use strict';

  // State
  let pollIntervalMs = 2000;
  let pollTimer = null;
  let activeTab = 'overview';
  const historyBufferLength = 20;

  const cpuHistory = [];
  const memHistory = [];
  const timeLabels = [];

  let cpuChartInstance = null;
  let memChartInstance = null;

  let lastDockerData = null;

  // DOM Elements
  const tabs = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');
  const pollSelect = document.getElementById('poll-interval-select');
  const liveStatusText = document.getElementById('live-status-text');

  // ── Tab Switching ──
  tabs.forEach(btn => {
    btn.addEventListener('click', () => {
      const tabName = btn.getAttribute('data-tab');
      switchTab(tabName);
    });
  });

  function switchTab(tabName) {
    activeTab = tabName;
    tabs.forEach(t => t.classList.toggle('active', t.getAttribute('data-tab') === tabName));
    tabContents.forEach(c => c.classList.toggle('active', c.id === `tab-${tabName}`));
    fetchData(); // Trigger immediate update on tab switch
  }

  // ── Polling Control ──
  if (pollSelect) {
    pollSelect.addEventListener('change', (e) => {
      pollIntervalMs = parseInt(e.target.value, 10);
      setupPolling();
    });
  }

  function setupPolling() {
    if (pollTimer) clearInterval(pollTimer);
    if (pollIntervalMs > 0) {
      pollTimer = setInterval(fetchData, pollIntervalMs);
      if (liveStatusText) liveStatusText.textContent = 'LIVE';
    } else {
      if (liveStatusText) liveStatusText.textContent = 'PAUSED';
    }
  }

  // ── Chart Initialization ──
  function initCharts() {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not available — will render SVG fallback.');
      return;
    }

    const commonOptions = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: 'rgba(14, 20, 34, 0.95)',
          titleColor: '#f1f5f9',
          bodyColor: '#cbd5e1',
          borderColor: 'rgba(255, 255, 255, 0.1)',
          borderWidth: 1,
        }
      },
      scales: {
        x: {
          display: true,
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: { color: '#64748b', font: { family: 'monospace', size: 10 }, maxTicksLimit: 6 }
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            color: '#64748b',
            font: { family: 'monospace', size: 10 },
            callback: (v) => `${v}%`
          }
        }
      }
    };

    const cpuCanvas = document.getElementById('chart-cpu');
    if (cpuCanvas) {
      const ctxCpu = cpuCanvas.getContext('2d');
      const gradCpu = ctxCpu.createLinearGradient(0, 0, 0, 220);
      gradCpu.addColorStop(0, 'rgba(0, 240, 255, 0.35)');
      gradCpu.addColorStop(1, 'rgba(0, 240, 255, 0.0)');

      cpuChartInstance = new Chart(ctxCpu, {
        type: 'line',
        data: {
          labels: timeLabels,
          datasets: [{
            label: 'CPU %',
            data: cpuHistory,
            borderColor: '#00f0ff',
            backgroundColor: gradCpu,
            borderWidth: 2,
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
          }]
        },
        options: commonOptions
      });
    }

    const memCanvas = document.getElementById('chart-mem');
    if (memCanvas) {
      const ctxMem = memCanvas.getContext('2d');
      const gradMem = ctxMem.createLinearGradient(0, 0, 0, 220);
      gradMem.addColorStop(0, 'rgba(168, 85, 247, 0.35)');
      gradMem.addColorStop(1, 'rgba(168, 85, 247, 0.0)');

      memChartInstance = new Chart(ctxMem, {
        type: 'line',
        data: {
          labels: timeLabels,
          datasets: [{
            label: 'Memory %',
            data: memHistory,
            borderColor: '#a855f7',
            backgroundColor: gradMem,
            borderWidth: 2,
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
          }]
        },
        options: commonOptions
      });
    }
  }

  // ── Data Fetching Engine ──
  async function fetchData() {
    try {
      if (activeTab === 'overview') {
        const [metrics, rules, docker, nodes] = await Promise.all([
          fetchJson('/api/v1/metrics'),
          fetchJson('/api/v1/rules'),
          fetchJson('/api/v1/docker'),
          fetchJson('/api/v1/nodes')
        ]);
        updateOverview(metrics, rules, docker, nodes);
        updateSystemMetrics(metrics);
        updateRules(rules);
        updateDocker(docker);
        updateNodes(nodes);
      } else if (activeTab === 'metrics') {
        const metrics = await fetchJson('/api/v1/metrics');
        updateSystemMetrics(metrics);
        updateCharts(metrics.cpu.util_percent, metrics.memory.percent);
      } else if (activeTab === 'docker') {
        const docker = await fetchJson('/api/v1/docker');
        updateDocker(docker);
      } else if (activeTab === 'nodes') {
        const nodes = await fetchJson('/api/v1/nodes');
        updateNodes(nodes);
      } else if (activeTab === 'rules') {
        const rules = await fetchJson('/api/v1/rules');
        updateRules(rules);
      }
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    }
  }

  async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);
    return await res.json();
  }

  // ── Render Overview ──
  function updateOverview(metrics, rules, docker, nodes) {
    if (!metrics) return;

    // CPU KPI
    const cpuVal = metrics.cpu.util_percent;
    setText('kpi-cpu', `${cpuVal.toFixed(1)}%`);
    setWidth('bar-cpu', `${Math.min(100, Math.max(0, cpuVal))}%`);
    setText('kpi-cpu-sub', `Load: ${metrics.cpu.load_1m.toFixed(2)}, ${metrics.cpu.load_5m.toFixed(2)}, ${metrics.cpu.load_15m.toFixed(2)}`);
    setText('chart-cpu-current', `${cpuVal.toFixed(1)}%`);

    // Mem KPI
    const memVal = metrics.memory.percent;
    setText('kpi-mem', `${memVal.toFixed(1)}%`);
    setWidth('bar-mem', `${Math.min(100, Math.max(0, memVal))}%`);
    setText('kpi-mem-sub', `${metrics.memory.used_gb} GB / ${metrics.memory.total_gb} GB`);
    setText('chart-mem-current', `${memVal.toFixed(1)}%`);

    // Disk KPI
    const diskVal = metrics.disk.root_usage_percent;
    setText('kpi-disk', `${diskVal.toFixed(1)}%`);
    setWidth('bar-disk', `${Math.min(100, Math.max(0, diskVal))}%`);
    setText('kpi-disk-sub', `${metrics.disk.root_free_gb} GB free`);

    // Docker KPI
    if (docker) {
      setText('kpi-docker', `${docker.running_count}`);
      setText('kpi-docker-sub', `${docker.running_count} running / ${docker.containers_count} total`);
      setText('docker-tab-count', `${docker.containers_count}`);
    }

    // Nodes KPI
    if (nodes) {
      setText('kpi-nodes', `${nodes.total_nodes}`);
      setText('kpi-nodes-sub', `${nodes.online_nodes} online`);
      setText('nodes-tab-count', `${nodes.total_nodes}`);
    }

    // Rules KPI
    if (rules) {
      setText('kpi-rules', `${rules.total_rules}`);
      setText('kpi-rules-sub', `${rules.firing_rules} firing`);
      setText('rules-tab-count', `${rules.total_rules}`);
      const card = document.getElementById('kpi-rules-card');
      if (card) {
        card.classList.toggle('rose', rules.firing_rules > 0);
      }
    }

    // System summary table
    setText('ov-hostname', metrics.system.hostname);
    setText('ov-os', `${metrics.system.os} ${metrics.system.os_release} (${metrics.system.architecture})`);
    setText('ov-uptime', formatUptime(metrics.system.uptime_seconds));
    setText('ov-cpu-cores', `${metrics.system.cpu_count_physical} physical / ${metrics.system.cpu_count_logical} logical`);
    setText('ov-procs', `${metrics.processes.total_count}`);

    // Overview alert events
    if (rules && rules.recent_alerts) {
      renderAlertLogs(rules.recent_alerts, 'ov-alert-logs');
      setText('ov-alert-count', `${rules.recent_alerts.length} logged`);
    }

    // Update history charts
    updateCharts(cpuVal, memVal);
  }

  function updateCharts(cpuVal, memVal) {
    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

    timeLabels.push(timeStr);
    cpuHistory.push(cpuVal);
    memHistory.push(memVal);

    if (timeLabels.length > historyBufferLength) {
      timeLabels.shift();
      cpuHistory.shift();
      memHistory.shift();
    }

    if (cpuChartInstance) cpuChartInstance.update();
    if (memChartInstance) memChartInstance.update();
  }

  // ── Render System Metrics ──
  function updateSystemMetrics(metrics) {
    if (!metrics) return;

    // Per-core grid
    const coreContainer = document.getElementById('core-grid-container');
    const perCore = metrics.cpu.per_core_percent || [];
    setText('metrics-core-count', `${perCore.length} cores`);

    if (coreContainer && perCore.length > 0) {
      coreContainer.innerHTML = perCore.map((pct, idx) => `
        <div class="core-card">
          <div class="core-label">CORE ${idx}</div>
          <div class="core-val">${pct.toFixed(0)}%</div>
          <div class="progress-bar-container" style="height: 4px; margin-top: 0.4rem;">
            <div class="progress-bar-fill fill-cyan" style="width: ${Math.min(100, Math.max(0, pct))}%;"></div>
          </div>
        </div>
      `).join('');
    }

    // Memory breakdown
    setText('m-ram-total', `${metrics.memory.total_gb} GB`);
    setText('m-ram-used', `${metrics.memory.used_gb} GB (${metrics.memory.percent}%)`);
    setText('m-ram-avail', `${metrics.memory.available_gb} GB`);
    setText('m-swap-total', `${metrics.memory.swap_total_gb} GB`);
    setText('m-swap-used', `${metrics.memory.swap_used_gb} GB (${metrics.memory.swap_percent}%)`);

    // Disk partitions table
    const partBody = document.getElementById('disk-partitions-body');
    if (partBody && metrics.disk.partitions) {
      if (metrics.disk.partitions.length === 0) {
        partBody.innerHTML = `<tr><td colspan="5" style="color: var(--text-muted);">Root filesystem: ${metrics.disk.root_usage_percent}% used (${metrics.disk.root_free_gb} GB free)</td></tr>`;
      } else {
        partBody.innerHTML = metrics.disk.partitions.map(p => `
          <tr>
            <td class="mono font-bold">${escapeHtml(p.mountpoint)}</td>
            <td class="mono" style="color: var(--text-muted);">${escapeHtml(p.device)}</td>
            <td class="mono">${p.total_gb} GB</td>
            <td class="mono">${p.used_gb} GB</td>
            <td>
              <div style="display: flex; align-items: center; gap: 0.5rem;">
                <div class="progress-bar-container" style="height: 6px; width: 80px; margin: 0;">
                  <div class="progress-bar-fill ${p.percent > 85 ? 'fill-rose' : 'fill-green'}" style="width: ${p.percent}%;"></div>
                </div>
                <span class="mono">${p.percent}%</span>
              </div>
            </td>
          </tr>
        `).join('');
      }
    }

    // Network stats
    const net = metrics.network;
    if (net && net.io) {
      setText('net-sent', `${net.io.mib_sent || 0} MiB`);
      setText('net-recv', `${net.io.mib_recv || 0} MiB`);
      setText('net-packets', `${(net.io.packets_sent || 0).toLocaleString()} / ${(net.io.packets_recv || 0).toLocaleString()}`);
      setText('net-conns', `${net.active_connections || 0}`);
    }

    // Sensors
    const sensorContainer = document.getElementById('sensor-container');
    if (sensorContainer) {
      const temps = metrics.sensors.temperatures || {};
      const batt = metrics.sensors.battery;
      const entries = [];

      for (const [chip, list] of Object.entries(temps)) {
        list.forEach(t => {
          entries.push(`
            <div style="display: flex; justify-content: space-between; padding: 0.35rem 0; border-bottom: 1px solid rgba(255,255,255,0.03);">
              <span style="color: var(--text-secondary);">${escapeHtml(chip)}: ${escapeHtml(t.label)}</span>
              <span class="mono" style="color: ${t.current > 75 ? 'var(--rose)' : 'var(--cyan)'}; font-weight: 600;">${t.current.toFixed(1)} °C</span>
            </div>
          `);
        });
      }

      if (batt) {
        entries.push(`
          <div style="display: flex; justify-content: space-between; padding: 0.35rem 0;">
            <span style="color: var(--text-secondary);">Battery</span>
            <span class="mono font-bold" style="color: var(--green);">${batt.percent.toFixed(0)}% ${batt.power_plugged ? '(Plugged)' : ''}</span>
          </div>
        `);
      }

      if (entries.length === 0) {
        sensorContainer.innerHTML = `<div style="color: var(--text-muted); font-size: 0.85rem;">No thermal or battery sensors detected on this host.</div>`;
      } else {
        sensorContainer.innerHTML = entries.join('');
      }
    }

    // Top processes
    const topCpuBody = document.getElementById('top-cpu-procs-body');
    if (topCpuBody && metrics.processes.top_cpu) {
      topCpuBody.innerHTML = metrics.processes.top_cpu.map(p => `
        <tr>
          <td class="mono" style="color: var(--text-muted);">${p.pid}</td>
          <td class="mono font-bold">${escapeHtml(p.name)}</td>
          <td class="mono" style="color: var(--cyan); font-weight: 600;">${p.cpu_percent}%</td>
        </tr>
      `).join('');
    }

    const topMemBody = document.getElementById('top-mem-procs-body');
    if (topMemBody && metrics.processes.top_memory) {
      topMemBody.innerHTML = metrics.processes.top_memory.map(p => `
        <tr>
          <td class="mono" style="color: var(--text-muted);">${p.pid}</td>
          <td class="mono font-bold">${escapeHtml(p.name)}</td>
          <td class="mono" style="color: var(--purple); font-weight: 600;">${p.mem_percent}%</td>
        </tr>
      `).join('');
    }
  }

  // ── Render Docker (Portainer Style) ──
  function updateDocker(docker) {
    if (!docker) return;
    lastDockerData = docker;

    const badge = document.getElementById('docker-daemon-badge');
    if (badge) {
      if (!docker.docker_installed) {
        badge.className = 'badge badge-offline';
        badge.textContent = 'Docker Not Installed';
      } else if (!docker.daemon_reachable) {
        badge.className = 'badge badge-stale';
        badge.textContent = 'Daemon Not Reachable';
      } else {
        badge.className = 'badge badge-online';
        badge.textContent = 'Daemon Online';
      }
    }

    setText('docker-kpi-running', `${docker.running_count}`);
    setText('docker-kpi-total', `${docker.containers_count}`);
    setText('docker-kpi-images', `${docker.images_count}`);
    setText('docker-kpi-version', docker.system_info?.ServerVersion || 'N/A');

    renderDockerContainersTable();
    renderDockerImagesTable();
  }

  function renderDockerContainersTable() {
    if (!lastDockerData) return;
    const body = document.getElementById('docker-containers-body');
    if (!body) return;

    const containers = lastDockerData.containers || [];
    const filterText = (document.getElementById('docker-filter-input')?.value || '').toLowerCase().trim();

    const filtered = containers.filter(c => {
      if (!filterText) return true;
      const name = (c.names || c.name || '').toLowerCase();
      const image = (c.image || '').toLowerCase();
      const id = (c.id || '').toLowerCase();
      return name.includes(filterText) || image.includes(filterText) || id.includes(filterText);
    });

    if (filtered.length === 0) {
      body.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">No matching containers found.</td></tr>`;
      return;
    }

    body.innerHTML = filtered.map(c => {
      const isUp = (c.state === 'running' || (c.status && c.status.startsWith('Up')));
      const stateBadge = isUp ? 'badge-running' : 'badge-stopped';
      const name = c.names || c.name || 'unnamed';
      const ports = c.ports || '-';

      return `
        <tr>
          <td><span class="badge ${stateBadge}">${isUp ? 'RUNNING' : 'STOPPED'}</span></td>
          <td class="font-bold mono" style="color: var(--text-primary);">${escapeHtml(name)}</td>
          <td class="mono" style="color: var(--cyan);">${escapeHtml(c.image || '-')}</td>
          <td class="mono" style="color: var(--text-muted); font-size: 0.8rem;">${(c.id || '').substring(0, 12)}</td>
          <td style="font-size: 0.8rem; color: var(--text-secondary);">${escapeHtml(c.status || '-')}</td>
          <td class="mono" style="font-size: 0.8rem; color: var(--amber);">${escapeHtml(ports)}</td>
        </tr>
      `;
    }).join('');
  }

  // Filter input event listener
  const filterInput = document.getElementById('docker-filter-input');
  if (filterInput) {
    filterInput.addEventListener('input', renderDockerContainersTable);
  }

  function renderDockerImagesTable() {
    if (!lastDockerData) return;
    const body = document.getElementById('docker-images-body');
    if (!body) return;

    const images = lastDockerData.images || [];
    if (images.length === 0) {
      body.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">No Docker images present.</td></tr>`;
      return;
    }

    body.innerHTML = images.map(img => `
      <tr>
        <td class="font-bold mono" style="color: var(--cyan);">${escapeHtml(img.repository || img.repo || '<none>')}</td>
        <td class="mono"><span class="badge badge-info">${escapeHtml(img.tag || 'latest')}</span></td>
        <td class="mono" style="color: var(--text-muted); font-size: 0.8rem;">${(img.id || img.image_id || '').substring(0, 12)}</td>
        <td class="mono">${escapeHtml(img.size || '-')}</td>
        <td style="color: var(--text-secondary); font-size: 0.8rem;">${escapeHtml(img.created || '-')}</td>
      </tr>
    `).join('');
  }

  // ── Render EC2 & Remote Nodes ──
  function updateNodes(nodes) {
    if (!nodes) return;
    const container = document.getElementById('nodes-cards-container');
    setText('nodes-summary-badge', `${nodes.total_nodes} Total (${nodes.online_nodes} Online)`);

    if (!container) return;

    if (!nodes.nodes || nodes.nodes.length === 0) {
      container.innerHTML = `
        <div class="panel" style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 3rem;">
          No remote EC2 instances reporting yet.<br>
          Run an agent on an EC2 instance: <code style="color: var(--cyan);">nano-agent --receiver-url http://&lt;YOUR_IP&gt;:8080/metrics</code>
        </div>
      `;
      return;
    }

    container.innerHTML = nodes.nodes.map(n => {
      const meta = n.metadata || {};
      const metrics = n.metrics || {};
      const statusClass = n.status === 'online' ? 'badge-online' : (n.status === 'stale' ? 'badge-stale' : 'badge-offline');

      return `
        <div class="node-card">
          <div class="node-card-header">
            <span class="node-title">${escapeHtml(n.node_id)}</span>
            <span class="badge ${statusClass}">${n.status}</span>
          </div>

          <div class="node-meta-row">
            <span class="node-meta-label">Instance Type:</span>
            <span class="node-meta-value">${escapeHtml(meta.instance_type || n.node_type)}</span>
          </div>
          <div class="node-meta-row">
            <span class="node-meta-label">Availability Zone:</span>
            <span class="node-meta-value">${escapeHtml(meta.availability_zone || 'N/A')}</span>
          </div>
          <div class="node-meta-row">
            <span class="node-meta-label">Public IP:</span>
            <span class="node-meta-value" style="color: var(--cyan);">${escapeHtml(meta.public_ip || 'N/A')}</span>
          </div>
          <div class="node-meta-row">
            <span class="node-meta-label">Private IP:</span>
            <span class="node-meta-value">${escapeHtml(meta.private_ip || 'N/A')}</span>
          </div>
          <div class="node-meta-row">
            <span class="node-meta-label">Last Seen:</span>
            <span class="node-meta-value" style="color: var(--text-muted);">${n.last_seen_seconds_ago}s ago</span>
          </div>

          <!-- Telemetry mini metrics -->
          <div style="background: rgba(0,0,0,0.2); border-radius: var(--radius-sm); padding: 0.5rem; margin-top: 0.25rem;">
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; margin-bottom: 0.25rem;">
              <span>CPU: <strong class="mono" style="color: var(--cyan);">${metrics['cpu.util'] !== undefined ? metrics['cpu.util'].toFixed(1) + '%' : '--'}</strong></span>
              <span>MEM: <strong class="mono" style="color: var(--purple);">${metrics['mem.util'] !== undefined ? metrics['mem.util'].toFixed(1) + '%' : '--'}</strong></span>
              <span>DISK: <strong class="mono" style="color: var(--green);">${metrics['disk.usage'] !== undefined ? metrics['disk.usage'].toFixed(1) + '%' : '--'}</strong></span>
            </div>
            <div class="progress-bar-container" style="height: 4px; margin: 0;">
              <div class="progress-bar-fill fill-cyan" style="width: ${metrics['cpu.util'] || 0}%;"></div>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // ── Render Alert Rules ──
  function updateRules(rules) {
    if (!rules) return;
    const body = document.getElementById('rules-table-body');
    setText('rules-status-badge', `${rules.total_rules} Rules (${rules.firing_rules} Alerting)`);

    if (body) {
      if (!rules.rules || rules.rules.length === 0) {
        body.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No active alert rules configured in nano-dsl.</td></tr>`;
      } else {
        body.innerHTML = rules.rules.map(r => {
          const isAlerting = r.status === 'alerting';
          const statusBadge = isAlerting ? 'badge-alerting' : 'badge-normal';

          return `
            <tr>
              <td class="mono" style="color: var(--text-muted);">${r.id}</td>
              <td class="mono font-bold" style="color: var(--text-primary);">${escapeHtml(r.name)}</td>
              <td class="mono" style="color: var(--cyan);">${escapeHtml(r.metric)}</td>
              <td class="mono font-bold">${escapeHtml(r.operator)}</td>
              <td class="mono">${r.threshold}</td>
              <td><span class="badge badge-info">${escapeHtml(r.action)}</span></td>
              <td class="mono font-bold" style="color: ${isAlerting ? 'var(--rose)' : 'var(--green)'};">${r.current_value !== null ? r.current_value : 'N/A'}</td>
              <td><span class="badge ${statusBadge}">${isAlerting ? 'ALERTING' : 'NORMAL'}</span></td>
            </tr>
          `;
        }).join('');
      }
    }

    if (rules.recent_alerts) {
      renderAlertLogs(rules.recent_alerts, 'rules-alert-logs');
    }
  }

  function renderAlertLogs(alerts, targetId) {
    const el = document.getElementById(targetId);
    if (!el) return;

    if (!alerts || alerts.length === 0) {
      el.innerHTML = `<div class="log-item" style="color: var(--text-muted);">No alert events recorded yet.</div>`;
      return;
    }

    el.innerHTML = alerts.map(a => `
      <div class="log-item">
        <span class="log-time">[${escapeHtml(a.timestamp || 'RECENT')}]</span>
        <span class="log-rule">${escapeHtml(a.rule)}:</span>
        <span class="log-msg">${escapeHtml(a.message || a.raw)}</span>
      </div>
    `).join('');
  }

  // ── Helper Utilities ──
  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setWidth(id, width) {
    const el = document.getElementById(id);
    if (el) el.style.width = width;
  }

  function formatUptime(seconds) {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0 || d > 0) parts.push(`${h}h`);
    parts.push(`${m}m`);
    parts.push(`${s}s`);
    return parts.join(' ');
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return String(str || '');
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ── Initialize App ──
  window.addEventListener('DOMContentLoaded', () => {
    initCharts();
    setupPolling();
    fetchData();
  });

})();
