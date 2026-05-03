document.addEventListener('DOMContentLoaded', () => {
    const scanForm = document.getElementById('scan-form');
    const scanBtn = document.getElementById('scan-btn');
    const btnText = scanBtn.querySelector('.btn-text');
    const btnSpinner = document.getElementById('btn-spinner');
    const statusMessage = document.getElementById('status-message');
    const projectsList = document.getElementById('projects-list');
    const refreshBtn = document.getElementById('refresh-btn');
    const projectDetailModal = document.getElementById('project-detail-modal');
    const closeDetailBtns = document.querySelectorAll('.close-detail-modal');
    const editProjectName = document.getElementById('edit-project-name');
    const editTargetFolder = document.getElementById('edit-target-folder');
    const saveProjectBtn = document.getElementById('save-project-btn');
    const deleteProjectBtn = document.getElementById('delete-project-btn');
    const browseEditBtn = document.getElementById('browse-edit-btn');
    
    let currentEditingProjectName = null;

    // Fetch initial projects
    fetchProjects();

    refreshBtn.addEventListener('click', fetchProjects);

    closeDetailBtns.forEach(btn => btn.addEventListener('click', () => {
        projectDetailModal.style.display = 'none';
    }));

    saveProjectBtn.addEventListener('click', saveProject);
    deleteProjectBtn.addEventListener('click', deleteProject);
    browseEditBtn.addEventListener('click', () => {
        folderModal.style.display = 'flex';
        // Reuse the folder picker logic, but target the edit input
        targetFolderInputToUpdate = editTargetFolder;
        loadFolder(editTargetFolder.value || "/Users/lammor/Documents");
    });

    scanForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const projectName = document.getElementById('project-name').value;
        const targetFolder = document.getElementById('target-folder').value;

        // UI Loading state
        btnText.textContent = 'Scanning...';
        btnSpinner.style.display = 'block';
        scanBtn.disabled = true;
        hideMessage();

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    project_name: projectName,
                    target_folder: targetFolder
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'An error occurred during scanning');
            }

            // Success
            let statsHtml = '';
            if (data.stats) {
                statsHtml = `
                    <div class="stats-grid">
                        <div class="stat-box"><label>Nodes</label><br><span>${data.stats.nodes}</span></div>
                        <div class="stat-box"><label>Calls</label><br><span>${data.stats.calls_edges}</span></div>
                        <div class="stat-box"><label>Imports</label><br><span>${data.stats.imports_edges}</span></div>
                        <div class="stat-box"><label>Inherits</label><br><span>${data.stats.inherits_edges}</span></div>
                        <div class="stat-box"><label>Implements</label><br><span>${data.stats.implements_edges}</span></div>
                        <div class="stat-box"><label>Defined</label><br><span>${data.stats.defined_in_edges}</span></div>
                    </div>
                `;
            }
            showMessage(`<strong>Success!</strong> ${data.message}${statsHtml}`, 'success');
            scanForm.reset();
            
            // Refresh projects list
            fetchProjects();

        } catch (error) {
            showMessage(`<strong>Error:</strong> ${error.message}`, 'error');
        } finally {
            // Restore UI
            btnText.textContent = 'Scan & Push to Neo4j';
            btnSpinner.style.display = 'none';
            scanBtn.disabled = false;
        }
    });

    async function fetchProjects() {
        projectsList.innerHTML = '<div class="loading-text">Loading projects...</div>';
        
        try {
            const response = await fetch('/api/projects');
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || 'Failed to fetch projects');
            }

            if (data.projects && data.projects.length > 0) {
                renderProjects(data.projects);
            } else {
                projectsList.innerHTML = '<div class="empty-text">No projects found. Scan one above!</div>';
            }
        } catch (error) {
            projectsList.innerHTML = `<div class="empty-text" style="color: #ef4444;">Error loading projects: ${error.message}</div>`;
        }
    }

    function renderProjects(projects) {
        projectsList.innerHTML = '';
        projects.forEach(project => {
            const item = document.createElement('div');
            item.className = 'project-item';
            
            // Get a deterministic icon based on project name
            const icons = ['📦', '🚀', '🛠️', '⚙️', '📂', '⚡', '🌟', '🔍'];
            const charCode = project.name.charCodeAt(0) || 0;
            const icon = icons[charCode % icons.length];

            item.innerHTML = `
                <div class="project-icon">${icon}</div>
                <div class="project-info">
                    <div class="project-name">${project.name}</div>
                    ${project.target_folder ? `<span class="project-meta" title="${project.target_folder}">${project.target_folder}</span>` : ''}
                </div>
                ${project.target_folder ? `
                <button class="view-graph-btn" title="View Graph ${project.name}" data-name="${project.name}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>
                </button>
                <button class="re-scan-btn" title="Re-Scan ${project.name}" data-name="${project.name}" data-folder="${project.target_folder}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
                </button>
                ` : ''}
            `;
            
            // Clicking a project opens the detail modal
            item.addEventListener('click', (e) => {
                if(e.target.closest('.re-scan-btn') || e.target.closest('.view-graph-btn')) return;
                openProjectDetailModal(project);
            });

            const reScanBtn = item.querySelector('.re-scan-btn');
            if (reScanBtn) {
                reScanBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const name = reScanBtn.dataset.name;
                    const folder = reScanBtn.dataset.folder;
                    
                    reScanBtn.classList.add('spinning');
                    hideMessage();

                    try {
                        const response = await fetch('/api/scan', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ project_name: name, target_folder: folder })
                        });
                        const data = await response.json();
                        if (!response.ok) throw new Error(data.detail || 'Error scanning');
                        
                        showMessage(`<strong>Re-Scan Success!</strong> Project '${name}' has been updated.`, 'success');
                    } catch (error) {
                        showMessage(`<strong>Error:</strong> ${error.message}`, 'error');
                    } finally {
                        reScanBtn.classList.remove('spinning');
                        fetchProjects();
                    }
                });
            }

            const viewGraphBtn = item.querySelector('.view-graph-btn');
            if (viewGraphBtn) {
                viewGraphBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openGraphModal(viewGraphBtn.dataset.name);
                });
            }

            projectsList.appendChild(item);
        });
    }

    function showMessage(html, type) {
        statusMessage.innerHTML = html;
        statusMessage.className = `message ${type}`;
        statusMessage.style.display = 'block';
    }

    function hideMessage() {
        statusMessage.style.display = 'none';
    }

    function openProjectDetailModal(project) {
        currentEditingProjectName = project.name;
        editProjectName.value = project.name;
        editTargetFolder.value = project.target_folder || '';
        document.getElementById('detail-title').textContent = `Manage Project: ${project.name}`;
        
        // Clear previous stats
        document.getElementById('detail-stats').innerHTML = `
            <div class="detail-stat-item">
                <label>Folder</label>
                <span title="${project.target_folder}">${project.target_folder ? 'Selected ✓' : 'None'}</span>
            </div>
            <div class="detail-stat-item">
                <label>Status</label>
                <span>Ready</span>
            </div>
        `;
        
        projectDetailModal.style.display = 'flex';
    }

    async function saveProject() {
        if (!currentEditingProjectName) return;
        
        const newName = editProjectName.value.trim();
        const folder = editTargetFolder.value.trim();
        
        if (!newName) {
            alert('Project name cannot be empty');
            return;
        }

        saveProjectBtn.disabled = true;
        saveProjectBtn.textContent = 'Saving...';

        try {
            const response = await fetch(`/api/projects/${encodeURIComponent(currentEditingProjectName)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_name: newName, target_folder: folder })
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Failed to update project');

            showMessage(`<strong>Success!</strong> Project updated.`, 'success');
            projectDetailModal.style.display = 'none';
            fetchProjects();
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            saveProjectBtn.disabled = false;
            saveProjectBtn.textContent = 'Save Changes';
        }
    }

    async function deleteProject() {
        if (!currentEditingProjectName) return;
        
        if (!confirm(`Are you sure you want to delete project "${currentEditingProjectName}" and ALL its components from Neo4j? This cannot be undone.`)) {
            return;
        }

        deleteProjectBtn.disabled = true;
        deleteProjectBtn.textContent = 'Deleting...';

        try {
            const response = await fetch(`/api/projects/${encodeURIComponent(currentEditingProjectName)}`, {
                method: 'DELETE'
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Failed to delete project');

            showMessage(`<strong>Success!</strong> Project deleted.`, 'success');
            projectDetailModal.style.display = 'none';
            fetchProjects();
        } catch (error) {
            alert(`Error: ${error.message}`);
        } finally {
            deleteProjectBtn.disabled = false;
            deleteProjectBtn.textContent = 'Delete Project';
        }
    }

    // --- Folder Picker Logic ---
    const browseBtn = document.getElementById('browse-btn');
    const folderModal = document.getElementById('folder-modal');
    const closeBtns = document.querySelectorAll('.close-modal');
    const folderList = document.getElementById('folder-list');
    const currentPathDisplay = document.getElementById('current-path-display');
    const selectFolderBtn = document.getElementById('select-folder-btn');
    const targetFolderInput = document.getElementById('target-folder');
    
    let currentSelectedPath = "";
    let targetFolderInputToUpdate = targetFolderInput; // Default to the scan form input

    browseBtn.addEventListener('click', () => {
        folderModal.style.display = 'flex';
        targetFolderInputToUpdate = targetFolderInput;
        let initialPath = targetFolderInput.value || "/Users/lammor/Documents";
        loadFolder(initialPath);
    });

    closeBtns.forEach(btn => btn.addEventListener('click', () => {
        folderModal.style.display = 'none';
    }));

    selectFolderBtn.addEventListener('click', () => {
        if (currentSelectedPath) {
            targetFolderInputToUpdate.value = currentSelectedPath;
        }
        folderModal.style.display = 'none';
    });

    async function loadFolder(path) {
        folderList.innerHTML = '<div class="loading-text">Loading...</div>';
        try {
            const response = await fetch(`/api/fs?path=${encodeURIComponent(path)}`);
            const data = await response.json();
            
            if (!response.ok) throw new Error(data.detail || 'Failed to load folders');
            
            currentSelectedPath = data.current_path;
            currentPathDisplay.textContent = currentSelectedPath;
            
            folderList.innerHTML = '';
            
            // Add parent folder option if applicable
            if (data.parent_path) {
                const upItem = document.createElement('div');
                upItem.className = 'folder-item';
                upItem.innerHTML = `<span class="folder-icon">⬆️</span> <span>.. (Up a level)</span>`;
                upItem.addEventListener('click', () => loadFolder(data.parent_path));
                folderList.appendChild(upItem);
            }
            
            if (data.folders.length === 0) {
                folderList.innerHTML += '<div class="empty-text">No subfolders</div>';
            } else {
                data.folders.forEach(folder => {
                    const item = document.createElement('div');
                    item.className = 'folder-item';
                    item.innerHTML = `<span class="folder-icon">📁</span> <span>${folder.name}</span>`;
                    item.addEventListener('click', () => loadFolder(folder.path));
                    folderList.appendChild(item);
                });
            }
        } catch (error) {
            folderList.innerHTML = `<div class="empty-text" style="color: #ef4444;">Error: ${error.message}</div>`;
        }
    }

    // --- Graph Viewer Logic ---
    const graphModal = document.getElementById('graph-modal');
    const closeGraphBtns = document.querySelectorAll('.close-graph-modal');
    const graphContainer = document.getElementById('graph-container');
    const graphTitle = document.getElementById('graph-title');
    const nodeDetails = document.getElementById('node-details');
    let network = null;

    closeGraphBtns.forEach(btn => btn.addEventListener('click', () => {
        graphModal.style.display = 'none';
        if (network) { network.destroy(); network = null; }
        // Clean up injected panel elements
        ['graph-stats-bar', 'graph-legend', 'graph-filter-bar', 'graph-physics-btn'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
    }));

    const KIND_CONFIG = {
        module:   { color: '#10b981', shape: 'hexagon', size: 22 },
        class:    { color: '#f59e0b', shape: 'dot',     size: 18 },
        function: { color: '#8b5cf6', shape: 'dot',     size: 12 },
        method:   { color: '#6366f1', shape: 'dot',     size: 11 },
    };
    const DEFAULT_NODE_CFG = { color: '#3b82f6', shape: 'dot', size: 13 };

    async function openGraphModal(projectName) {
        graphModal.style.display = 'flex';
        graphTitle.textContent = `Graph: ${projectName}`;
        graphContainer.innerHTML = '<div class="loading-text">⏳ Loading graph data...</div>';
        nodeDetails.innerHTML = '<p class="empty-text">Click a node to see details</p>';

        try {
            const response = await fetch(`/api/projects/${projectName}/graph?limit=300`);
            const data = await response.json();

            if (!response.ok) throw new Error(data.detail || 'Failed to load graph');
            if (!data.nodes || data.nodes.length === 0) {
                graphContainer.innerHTML = '<div class="empty-text">No graph data found for this project.<br>Try re-scanning it first.</div>';
                return;
            }

            graphContainer.innerHTML = '';

            // Build vis datasets
            const visNodes = new vis.DataSet(data.nodes.map(n => {
                const cfg = KIND_CONFIG[n.kind] || DEFAULT_NODE_CFG;
                return {
                    id: n.id,
                    label: n.label,
                    title: n.full_name || n.label,
                    color: {
                        background: cfg.color,
                        border: 'rgba(255,255,255,0.2)',
                        highlight: { background: '#60a5fa', border: 'white' },
                        hover:      { background: '#93c5fd', border: 'white' }
                    },
                    font: { color: 'white', size: 11 },
                    shape: cfg.shape,
                    size:  cfg.size,
                    // Store for detail panel
                    _kind:      n.kind,
                    _full_name: n.full_name,
                    _layer:     n.layer,
                    _props:     n.properties || {}
                };
            }));

            const visEdges = new vis.DataSet(data.edges.map(e => ({
                id:    e.id,
                from:  e.from,
                to:    e.to,
                label: e.label,
                font:  { size: 9, align: 'middle', color: 'rgba(148,163,184,0.8)', strokeWidth: 0 },
                color: { color: 'rgba(255,255,255,0.15)', highlight: '#60a5fa', hover: '#93c5fd' },
                arrows: { to: { enabled: true, scaleFactor: 0.6 } },
                smooth: { type: 'dynamic' }
            })));

            const options = {
                physics: {
                    barnesHut: {
                        gravitationalConstant: -3000,
                        centralGravity: 0.2,
                        springLength: 120,
                        springConstant: 0.04,
                        damping: 0.12
                    },
                    stabilization: { iterations: 200, updateInterval: 25 }
                },
                interaction: {
                    hover: true, tooltipDelay: 150,
                    navigationButtons: true, keyboard: true
                },
                layout: { improvedLayout: true }
            };

            network = new vis.Network(graphContainer, { nodes: visNodes, edges: visEdges }, options);

            // Build side panel controls
            buildGraphPanel(data, visNodes);

            // Node click
            network.on('click', (params) => {
                if (params.nodes.length > 0) {
                    showNodeDetails(visNodes.get(params.nodes[0]));
                } else {
                    nodeDetails.innerHTML = '<p class="empty-text">Click a node to see details</p>';
                }
            });

            // Stabilization progress
            network.on('stabilizationProgress', (params) => {
                const pct = Math.round((params.iterations / params.total) * 100);
                const bar = document.getElementById('graph-stats-bar');
                if (bar) bar.textContent = `Stabilizing layout… ${pct}%`;
            });
            network.on('stabilizationIterationsDone', () => {
                network.setOptions({ physics: { enabled: false } });
                const bar = document.getElementById('graph-stats-bar');
                if (bar) bar.textContent = `${data.nodes.length} nodes · ${data.edges.length} edges · Layout done ✓`;
            });

        } catch (error) {
            graphContainer.innerHTML = `<div class="empty-text" style="color:#ef4444;">Error: ${error.message}</div>`;
        }
    }

    function buildGraphPanel(data, visNodes) {
        const kinds = [...new Set(data.nodes.map(n => n.kind).filter(Boolean))];
        const panel = nodeDetails.parentElement;

        // Stats bar
        const statsBar = document.createElement('div');
        statsBar.className = 'graph-stats-bar';
        statsBar.id = 'graph-stats-bar';
        statsBar.textContent = `${data.nodes.length} nodes · ${data.edges.length} edges`;

        // Legend
        const legend = document.createElement('div');
        legend.className = 'graph-legend';
        legend.id = 'graph-legend';
        kinds.forEach(k => {
            const cfg = KIND_CONFIG[k] || DEFAULT_NODE_CFG;
            legend.innerHTML += `<div class="legend-item"><div class="legend-dot" style="background:${cfg.color}"></div>${k}</div>`;
        });

        // Filter chips
        const filterBar = document.createElement('div');
        filterBar.className = 'graph-filter';
        filterBar.id = 'graph-filter-bar';

        const makeChip = (text, kind) => {
            const chip = document.createElement('button');
            chip.className = 'filter-chip' + (kind === '' ? ' active' : '');
            chip.textContent = text;
            chip.dataset.kind = kind;
            return chip;
        };
        filterBar.appendChild(makeChip('All', ''));
        kinds.forEach(k => filterBar.appendChild(makeChip(k, k)));

        filterBar.addEventListener('click', (e) => {
            const chip = e.target.closest('.filter-chip');
            if (!chip || chip.id === 'graph-physics-btn') return;
            filterBar.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            const kind = chip.dataset.kind;
            const visibleIds = kind
                ? new Set(data.nodes.filter(n => n.kind === kind).map(n => n.id))
                : null;
            visNodes.update(visNodes.getIds().map(id => ({ id, hidden: visibleIds ? !visibleIds.has(id) : false })));
            const visible = visNodes.get({ filter: n => !n.hidden }).length;
            const bar = document.getElementById('graph-stats-bar');
            if (bar) bar.textContent = `Showing ${visible} / ${data.nodes.length} nodes · ${data.edges.length} edges`;
        });

        // Physics toggle
        const physicsBtn = document.createElement('button');
        physicsBtn.className = 'filter-chip';
        physicsBtn.id = 'graph-physics-btn';
        physicsBtn.textContent = '⚡ Enable Physics';
        let physicsOn = false;
        physicsBtn.addEventListener('click', () => {
            physicsOn = !physicsOn;
            network.setOptions({ physics: { enabled: physicsOn } });
            physicsBtn.textContent = physicsOn ? '⏹ Stop Physics' : '⚡ Enable Physics';
        });
        filterBar.appendChild(physicsBtn);

        panel.insertBefore(statsBar, nodeDetails);
        panel.insertBefore(legend, nodeDetails);
        panel.insertBefore(filterBar, nodeDetails);
    }

    function showNodeDetails(node) {
        let html = '';
        const addRow = (label, value, isPre = false) => {
            if (value === undefined || value === null || value === '') return;
            html += `<div class="detail-row">
                <label>${label}</label>
                ${isPre ? `<pre>${value}</pre>` : `<span>${value}</span>`}
            </div>`;
        };
        addRow('Name', node._full_name || node.label);
        addRow('Kind', node._kind);
        addRow('Layer', node._layer);
        if (node._props) {
            addRow('Source File', node._props.source_file);
            addRow('Line', node._props.line_number);
            addRow('Signature', node._props.signature, true);
            addRow('Docstring', node._props.docstring, true);
        }
        nodeDetails.innerHTML = html || '<p class="empty-text">No details available</p>';
    }
});


