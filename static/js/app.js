// Global state
let allGames = [];
let currentEditId = null;
let isLoggedIn = false;

// Check authentication status
async function checkAuth() {
  try {
    const res = await fetch('/api/auth/check');
    const data = await res.json();
    isLoggedIn = data.logged_in;
    updateUIForAuth();
  } catch (err) {
    console.error('Auth check failed:', err);
  }
}

function updateUIForAuth() {
  // Show/hide elements based on auth status
  const adminElements = document.querySelectorAll('.admin-only');
  const guestElements = document.querySelectorAll('.guest-only');
  
  adminElements.forEach(el => {
    el.style.display = isLoggedIn ? '' : 'none';
  });
  
  guestElements.forEach(el => {
    el.style.display = isLoggedIn ? 'none' : '';
  });
  
  // Update auth indicator
  const indicator = document.getElementById('auth-indicator');
  if (isLoggedIn) {
    indicator.innerHTML = '🟢 Admin';
    indicator.style.color = '#2ed573';
  } else {
    indicator.innerHTML = '👁️ View Only';
    indicator.style.color = 'rgba(240, 230, 255, 0.6)';
  }
}

// Login/Logout handlers
document.getElementById('login-btn')?.addEventListener('click', async () => {
  const password = document.getElementById('password-input').value;
  
  if (!password) {
    alert('Please enter the password');
    return;
  }
  
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    
    const data = await response.json();
    
    if (data.success) {
      isLoggedIn = true;
      updateUIForAuth();
      document.getElementById('password-input').value = '';
      alert('✓ Unlocked! You can now edit games.');
    } else {
      alert('❌ Incorrect password');
      document.getElementById('password-input').value = '';
    }
  } catch (err) {
    alert('Error logging in');
  }
});

// Allow Enter key to login
document.getElementById('password-input')?.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    document.getElementById('login-btn').click();
  }
});

document.getElementById('logout-btn')?.addEventListener('click', async () => {
  if (confirm('Are you sure you want to logout?')) {
    await fetch('/api/logout', { method: 'POST' });
    window.location.reload();
  }
});

// Tab navigation
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    
    if (tab === 'stats') loadStats();
    if (tab === 'challenges') loadAllChallenges();
  });
});

// Fetch and render games
async function fetchGames() {
  const res = await fetch('/api/games');
  allGames = await res.json();
  renderGames(allGames);
}

function renderGames(games) {
  const list = document.getElementById('games-list');
  list.innerHTML = '';
  
  if (games.length === 0) {
    list.innerHTML = '<div class="empty-state">No games found. Click "+ Add Game" to get started!</div>';
    return;
  }
  
  games.forEach(game => {
    const template = document.getElementById('game-card');
    const el = template.content.cloneNode(true);
    
    // Cover image
    const cover = el.querySelector('.game-cover');
    if (game.cover_url) {
      cover.style.backgroundImage = `url(${game.cover_url})`;
    }
    
    el.querySelector('.game-title').textContent = game.title;
    el.querySelector('.game-platform').textContent = game.platform || '';
    el.querySelector('.game-notes').textContent = game.notes || '';
    el.querySelector('.game-status').textContent = game.status || '';
    el.querySelector('.game-status').className = `game-status badge status-${(game.status || '').toLowerCase()}`;
    
    // Rating stars
    const rating = el.querySelector('.game-rating');
    if (game.rating) {
      rating.textContent = '★'.repeat(game.rating) + '☆'.repeat(5 - game.rating);
    }
    
    // Hours played
    const hours = el.querySelector('.game-hours');
    if (game.hours_played) {
      hours.textContent = `⏱️ ${game.hours_played}h`;
    }
    
    // Tags
    const tagsEl = el.querySelector('.game-tags');
    if (game.tags && game.tags.length > 0) {
      tagsEl.innerHTML = game.tags.map(tag => 
        `<span class="tag">${tag}</span>`
      ).join('');
    }
    
    // Action buttons - always show achievements and completionist buttons
    const achBtn = el.querySelector('.ach');
    const compBtn = el.querySelector('.comp');
    achBtn.addEventListener('click', () => openAchievements(game));
    compBtn.addEventListener('click', () => openCompletionist(game));
    
    // Edit/Delete buttons - admin only
    if (isLoggedIn) {
      const editBtn = el.querySelector('.edit');
      const deleteBtn = el.querySelector('.delete');
      if (editBtn && deleteBtn) {
        editBtn.style.display = '';
        deleteBtn.style.display = '';
        editBtn.addEventListener('click', () => editGame(game));
        deleteBtn.addEventListener('click', () => deleteGame(game.id));
      }
    }
    
    list.appendChild(el);
  });
}

// Search and filter
document.getElementById('search').addEventListener('input', filterGames);
document.getElementById('filter-status').addEventListener('change', filterGames);
document.getElementById('filter-platform').addEventListener('change', filterGames);

function filterGames() {
  const search = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('filter-status').value;
  const platform = document.getElementById('filter-platform').value;
  
  const filtered = allGames.filter(game => {
    const matchSearch = game.title.toLowerCase().includes(search) ||
                       (game.notes || '').toLowerCase().includes(search) ||
                       (game.tags || []).some(t => t.toLowerCase().includes(search));
    const matchStatus = !status || game.status === status;
    const matchPlatform = !platform || game.platform === platform;
    
    return matchSearch && matchStatus && matchPlatform;
  });
  
  renderGames(filtered);
}

// Modal management
const modal = document.getElementById('game-modal');
const modalTitle = document.getElementById('modal-title');

document.getElementById('add-game').addEventListener('click', () => {
  if (!isLoggedIn) {
    alert('Please login to add games');
    return;
  }
  currentEditId = null;
  modalTitle.textContent = 'Add Game';
  clearModalInputs();
  modal.classList.add('show');
});

document.querySelector('.modal-close').addEventListener('click', closeModal);
document.getElementById('cancel-game').addEventListener('click', closeModal);

modal.addEventListener('click', (e) => {
  if (e.target === modal) closeModal();
});

function closeModal() {
  modal.classList.remove('show');
}

function clearModalInputs() {
  document.getElementById('input-title').value = '';
  document.getElementById('input-platform').value = '';
  document.getElementById('input-status').value = '';
  document.getElementById('input-rating').value = '';
  document.getElementById('input-hours').value = '';
  document.getElementById('input-completion').value = '';
  document.getElementById('input-tags').value = '';
  document.getElementById('input-notes').value = '';
  document.getElementById('input-steam-id').value = '';
  document.getElementById('input-cover').value = '';
  document.getElementById('steam-results').innerHTML = '';
}

// Save game
document.getElementById('save-game').addEventListener('click', async () => {
  if (!isLoggedIn) {
    alert('Please login to save games');
    return;
  }
  
  const title = document.getElementById('input-title').value.trim();
  if (!title) {
    alert('Title is required');
    return;
  }
  
  const tags = document.getElementById('input-tags').value
    .split(',')
    .map(t => t.trim())
    .filter(t => t);
  
  const gameData = {
    title,
    platform: document.getElementById('input-platform').value,
    status: document.getElementById('input-status').value,
    rating: parseInt(document.getElementById('input-rating').value) || null,
    hours_played: parseFloat(document.getElementById('input-hours').value) || null,
    completion_date: document.getElementById('input-completion').value || null,
    tags,
    notes: document.getElementById('input-notes').value,
    steam_app_id: parseInt(document.getElementById('input-steam-id').value) || null,
    cover_url: document.getElementById('input-cover').value || null
  };
  
  try {
    let response;
    if (currentEditId) {
      response = await fetch(`/api/games/${currentEditId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(gameData)
      });
    } else {
      response = await fetch('/api/games', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(gameData)
      });
    }
    
    if (response.status === 401) {
      alert('Your session has expired. Please login again.');
      window.location.href = '/login';
      return;
    }
    
    closeModal();
    fetchGames();
  } catch (err) {
    alert('Error saving game: ' + err.message);
  }
});

// Edit game
function editGame(game) {
  if (!isLoggedIn) {
    alert('Please login to edit games');
    return;
  }
  
  currentEditId = game.id;
  modalTitle.textContent = 'Edit Game';
  
  document.getElementById('input-title').value = game.title || '';
  document.getElementById('input-platform').value = game.platform || '';
  document.getElementById('input-status').value = game.status || '';
  document.getElementById('input-rating').value = game.rating || '';
  document.getElementById('input-hours').value = game.hours_played || '';
  document.getElementById('input-completion').value = game.completion_date || '';
  document.getElementById('input-tags').value = (game.tags || []).join(', ');
  document.getElementById('input-notes').value = game.notes || '';
  document.getElementById('input-steam-id').value = game.steam_app_id || '';
  document.getElementById('input-cover').value = game.cover_url || '';
  
  modal.classList.add('show');
}

// Delete game
async function deleteGame(id) {
  if (!isLoggedIn) {
    alert('Please login to delete games');
    return;
  }
  
  if (!confirm('Delete this game? This will also delete all associated achievements.')) return;
  
  try {
    const response = await fetch(`/api/games/${id}`, { method: 'DELETE' });
    
    if (response.status === 401) {
      alert('Your session has expired. Please enter the password again.');
      isLoggedIn = false;
      updateUIForAuth();
      return;
    }
    
    fetchGames();
  } catch (err) {
    alert('Error deleting game: ' + err.message);
  }
}

// Steam integration
document.getElementById('steam-search-btn').addEventListener('click', async () => {
  const query = document.getElementById('input-title').value.trim();
  if (!query) {
    alert('Enter a game title first');
    return;
  }
  
  const resultsDiv = document.getElementById('steam-results');
  resultsDiv.innerHTML = '<div class="loading">Searching Steam...</div>';
  
  try {
    const res = await fetch(`/api/steam/search?q=${encodeURIComponent(query)}`);
    const results = await res.json();
    
    if (results.length === 0) {
      resultsDiv.innerHTML = '<div class="no-results">No Steam games found</div>';
      return;
    }
    
    resultsDiv.innerHTML = results.map(game => `
      <div class="steam-result" data-id="${game.id}" data-name="${game.name}" data-img="${game.capsule_image || game.tiny_image}">
        <img src="${game.tiny_image}" alt="${game.name}" />
        <div class="steam-result-info">
          <strong>${game.name}</strong>
          <span class="steam-price">${game.price?.final_formatted || 'N/A'}</span>
        </div>
      </div>
    `).join('');
    
    // Handle selection
    resultsDiv.querySelectorAll('.steam-result').forEach(el => {
      el.addEventListener('click', async () => {
        document.getElementById('input-title').value = el.dataset.name;
        document.getElementById('input-steam-id').value = el.dataset.id;
        document.getElementById('input-cover').value = el.dataset.img;
        document.getElementById('input-platform').value = 'PC';
        resultsDiv.innerHTML = '<div class="loading">Loading game details...</div>';
        
        // Fetch additional details (hours played, tags)
        try {
          const detailsRes = await fetch(`/api/steam/game-details/${el.dataset.id}`);
          const details = await detailsRes.json();
          
          if (details.hours_played) {
            document.getElementById('input-hours').value = details.hours_played;
          }
          
          if (details.tags && details.tags.length > 0) {
            document.getElementById('input-tags').value = details.tags.join(', ');
          }
          
          resultsDiv.innerHTML = '<div class="success">✓ Game details loaded from Steam</div>';
          
          // Offer to import achievements
          setTimeout(() => {
            if (confirm('Import achievements from Steam?')) {
              importSteamAchievements(el.dataset.id);
            }
          }, 500);
        } catch (err) {
          resultsDiv.innerHTML = '<div class="success">✓ Game selected from Steam</div>';
        }
      });
    });
  } catch (err) {
    resultsDiv.innerHTML = '<div class="error">Failed to search Steam</div>';
  }
});

async function importSteamAchievements(appId) {
  try {
    const res = await fetch(`/api/steam/achievements/${appId}`);
    const achievements = await res.json();
    
    alert(`Found ${achievements.length} achievements. Save the game first, then you can import them.`);
  } catch (err) {
    alert('Failed to load achievements from Steam');
  }
}

// Achievements
async function openAchievements(game) {
  document.querySelector('[data-tab="achievements"]').click();
  const achPane = document.getElementById('achievements-pane');
  
  const addBtnHtml = isLoggedIn ? '<button id="add-ach-btn" class="btn">+ Add Achievement</button>' : '';
  const importBtnHtml = (isLoggedIn && game.steam_app_id) ? '<button id="import-steam-ach" class="btn">Import from Steam</button>' : '';
  
  achPane.innerHTML = `
    <div class="achievement-header">
      <h2>🏆 ${game.title}</h2>
      <div class="achievement-actions">
        ${addBtnHtml}
        ${importBtnHtml}
      </div>
    </div>
    <div class="achievement-progress-bar-container">
      <div class="achievement-progress-bar">
        <div class="achievement-progress-fill" id="ach-progress-fill" style="width: 0%"></div>
      </div>
      <div class="achievement-progress-text" id="ach-progress-text">0 / 0 (0%)</div>
    </div>
    <div id="ach-list"></div>
  `;
  
  await loadAchievements(game.id);
  
  if (isLoggedIn) {
    const addBtn = document.getElementById('add-ach-btn');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        const title = prompt('Achievement title');
        if (!title) return;
        const desc = prompt('Description (optional)');
        
        fetch(`/api/games/${game.id}/achievements`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title,
            description: desc || '',
            date: new Date().toISOString().slice(0, 10),
            unlocked: 1
          })
        }).then(() => loadAchievements(game.id))
        .catch(err => {
          alert('Error adding achievement. Your session may have expired.');
          isLoggedIn = false;
          updateUIForAuth();
        });
      });
    }
    
    const importBtn = document.getElementById('import-steam-ach');
    if (importBtn && game.steam_app_id) {
      importBtn.addEventListener('click', async () => {
        const res = await fetch(`/api/steam/achievements/${game.steam_app_id}`);
        const achievements = await res.json();
        
        if (!confirm(`Import ${achievements.length} achievements from Steam?`)) return;
        
        importBtn.disabled = true;
        importBtn.textContent = 'Importing...';
        
        for (const ach of achievements) {
          await fetch(`/api/games/${game.id}/achievements`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              title: ach.name,
              description: ach.description,
              date: ach.unlock_date || new Date().toISOString().slice(0, 10),
              unlocked: ach.achieved || 0,
              icon_url: ach.icon
            })
          });
        }
        
        // Auto-refresh after import
        loadAchievements(game.id);
        importBtn.textContent = 'Import from Steam';
        importBtn.disabled = false;
      });
    }
  }
}

// Open completionist for a game
async function openCompletionist(game) {
  document.querySelector('[data-tab="completionist"]').click();
  const compPane = document.getElementById('completionist-pane');
  
  const compAddBtnHtml = isLoggedIn ? '<button id="add-comp-btn" class="btn">+ Add Challenge</button>' : '';
  const compSortHtml = `
    <select id="comp-sort" class="sort-select">
      <option value="date">Sort by Date</option>
      <option value="difficulty">Sort by Difficulty</option>
    </select>
  `;
  
  compPane.innerHTML = `
    <div class="achievement-header">
      <h2>🎯 ${game.title}</h2>
      <div class="achievement-actions">
        ${compSortHtml}
        ${compAddBtnHtml}
      </div>
    </div>
    <div id="comp-list"></div>
  `;
  
  await loadCompletionistAchievements(game.id);
  
  // Setup sort change handler
  document.getElementById('comp-sort')?.addEventListener('change', (e) => {
    loadCompletionistAchievements(game.id, e.target.value);
  });
  
  // Completionist add button
  if (isLoggedIn) {
    const compBtn = document.getElementById('add-comp-btn');
    if (compBtn) {
      compBtn.addEventListener('click', () => {
        showCompletionistModal(game.id);
      });
    }
  }
}

async function loadAchievements(gameId) {
  const res = await fetch(`/api/games/${gameId}/achievements`);
  const achievements = await res.json();
  const list = document.getElementById('ach-list');
  
  if (achievements.length === 0) {
    list.innerHTML = '<div class="empty-state">No achievements yet</div>';
    document.getElementById('ach-progress-text').textContent = '0 / 0 (0%)';
    return;
  }
  
  // Calculate progress
  const unlocked = achievements.filter(a => a.unlocked).length;
  const total = achievements.length;
  const percentage = Math.round((unlocked / total) * 100);
  
  // Update progress bar
  document.getElementById('ach-progress-fill').style.width = percentage + '%';
  document.getElementById('ach-progress-text').textContent = `${unlocked} / ${total} (${percentage}%)`;
  
  const actionsHtml = isLoggedIn ? `
    <div class="ach-actions">
      <button class="btn-icon toggle-ach" data-id="ACH_ID" data-game="GAME_ID" data-unlocked="UNLOCKED">
        TOGGLE_ICON
      </button>
      <button class="btn-icon delete-ach" data-id="ACH_ID" data-game="GAME_ID">🗑️</button>
    </div>
  ` : '';
  
  list.innerHTML = achievements.map(ach => {
    const actions = actionsHtml
      .replace(/ACH_ID/g, ach.id)
      .replace(/GAME_ID/g, gameId)
      .replace('UNLOCKED', ach.unlocked)
      .replace('TOGGLE_ICON', ach.unlocked ? '✓' : '○');
    
    return `
      <div class="achievement-card ${ach.unlocked ? 'unlocked' : 'locked'}">
        ${ach.icon_url ? `<img src="${ach.icon_url}" class="ach-icon" />` : ''}
        <div class="ach-content">
          <div class="ach-title">${ach.title}</div>
          <div class="ach-desc">${ach.description || ''}</div>
          ${ach.date ? `<div class="ach-date">📅 ${ach.date}</div>` : ''}
        </div>
        ${actions}
      </div>
    `;
  }).join('');
  
  if (isLoggedIn) {
    // Toggle achievement
    list.querySelectorAll('.toggle-ach').forEach(btn => {
      btn.addEventListener('click', async () => {
        const achId = btn.dataset.id;
        const gameId = btn.dataset.game;
        const unlocked = btn.dataset.unlocked === '1' ? 0 : 1;
        
        await fetch(`/api/games/${gameId}/achievements/${achId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ unlocked })
        });
        
        loadAchievements(gameId);
      });
    });
    
    // Delete achievement
    list.querySelectorAll('.delete-ach').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this achievement?')) return;
        
        const achId = btn.dataset.id;
        const gameId = btn.dataset.game;
        
        await fetch(`/api/games/${gameId}/achievements/${achId}`, {
          method: 'DELETE'
        });
        
        loadAchievements(gameId);
      });
    });
  }
}

// Statistics
async function loadStats() {
  const res = await fetch('/api/stats');
  const stats = await res.json();
  
  document.getElementById('stat-total').textContent = stats.total_games;
  document.getElementById('stat-completed').textContent = stats.completed_games;
  document.getElementById('stat-hours').textContent = stats.total_hours + 'h';
  document.getElementById('stat-achievements').textContent = `${stats.achievements_unlocked} / ${stats.achievements_total}`;
  
  // Achievement progress list
  const progressList = document.getElementById('achievement-progress-list');
  if (stats.achievement_progress && stats.achievement_progress.length > 0) {
    progressList.innerHTML = stats.achievement_progress.map(game => {
      const percentage = game.total_achievements > 0 ? Math.round((game.unlocked_achievements / game.total_achievements) * 100) : 0;
      return `
        <div class="progress-item">
          <div class="progress-item-header">
            <span class="progress-game-title">${game.title}</span>
            <span class="progress-count">${game.unlocked_achievements} / ${game.total_achievements}</span>
          </div>
          <div class="progress-bar-small">
            <div class="progress-bar-fill-small" style="width: ${percentage}%"></div>
          </div>
        </div>
      `;
    }).join('');
  } else {
    progressList.innerHTML = '<div class="empty-state">No achievements tracked yet</div>';
  }
  
  // Status breakdown
  const statusBreakdown = document.getElementById('status-breakdown');
  if (stats.status_breakdown && Object.keys(stats.status_breakdown).length > 0) {
    statusBreakdown.innerHTML = Object.entries(stats.status_breakdown).map(([status, count]) => `
      <div class="breakdown-item">
        <span class="breakdown-label">${status}</span>
        <span class="breakdown-value">${count}</span>
      </div>
    `).join('');
  } else {
    statusBreakdown.innerHTML = '<div class="empty-state">No status data</div>';
  }
  
  // Platform breakdown
  const platformBreakdown = document.getElementById('platform-breakdown');
  if (stats.platform_breakdown && Object.keys(stats.platform_breakdown).length > 0) {
    platformBreakdown.innerHTML = Object.entries(stats.platform_breakdown).map(([platform, count]) => `
      <div class="breakdown-item">
        <span class="breakdown-label">${platform}</span>
        <span class="breakdown-value">${count}</span>
      </div>
    `).join('');
  } else {
    platformBreakdown.innerHTML = '<div class="empty-state">No platform data</div>';
  }
  
  // Recent completions
  const recentCompletions = document.getElementById('recent-completions');
  if (stats.recent_completions && stats.recent_completions.length > 0) {
    recentCompletions.innerHTML = stats.recent_completions.map(game => `
      <div class="completion-item">
        ${game.cover_url ? `<img src="${game.cover_url}" class="completion-cover" />` : ''}
        <div class="completion-info">
          <div class="completion-title">${game.title}</div>
          <div class="completion-date">📅 ${game.completion_date}</div>
        </div>
      </div>
    `).join('');
  } else {
    recentCompletions.innerHTML = '<div class="empty-state">No completed games yet</div>';
  }
}

// All Challenges View
async function loadAllChallenges() {
  const pane = document.getElementById('challenges-pane');
  
  const filterHtml = `
    <div class="achievement-header">
      <h2>🎯 All Challenges</h2>
      <div class="achievement-actions">
        <select id="challenge-filter" class="sort-select">
          <option value="all">All Challenges</option>
          <option value="in_progress">In Progress</option>
          <option value="completed">Completed</option>
        </select>
        <select id="challenge-sort" class="sort-select">
          <option value="date">Sort by Date</option>
          <option value="difficulty">Sort by Difficulty</option>
        </select>
      </div>
    </div>
    <div id="challenges-list"></div>
  `;
  
  pane.innerHTML = filterHtml;
  
  const filterSelect = document.getElementById('challenge-filter');
  const sortSelect = document.getElementById('challenge-sort');
  
  const loadChallenges = async () => {
    const status = filterSelect.value;
    const sort = sortSelect.value;
    const res = await fetch(`/api/completionist/all?status=${status}&sort=${sort}`);
    const challenges = await res.json();
    const list = document.getElementById('challenges-list');
    
    if (challenges.length === 0) {
      list.innerHTML = '<div class="empty-state">No challenges found</div>';
      return;
    }
    
    list.innerHTML = challenges.map(comp => {
      const difficultyColor = comp.difficulty >= 80 ? '#ff4757' : 
                             comp.difficulty >= 50 ? '#ffa502' : 
                             '#2ed573';
      
      const editDeleteHtml = isLoggedIn ? `
        <div class="comp-actions">
          <button class="btn-icon toggle-comp" data-id="${comp.id}" data-game="${comp.game_id}" data-completed="${comp.completed}" title="Toggle Status">
            ${comp.completed ? '✓' : '○'}
          </button>
          <button class="btn-icon edit-comp-all" data-id="${comp.id}" data-game="${comp.game_id}" title="Edit">✏️</button>
          <button class="btn-icon delete-comp-all" data-id="${comp.id}" data-game="${comp.game_id}" title="Delete">🗑️</button>
        </div>
      ` : '';
      
      return `
        <div class="completionist-card">
          <div class="comp-header">
            <div class="comp-title-section">
              <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">${comp.game_title}</div>
              <div class="comp-title ${comp.completed ? 'completed-strike' : ''}">${comp.title}</div>
              <div class="comp-difficulty" style="color: ${difficultyColor}">
                Difficulty: ${comp.difficulty}/100
              </div>
            </div>
            ${editDeleteHtml}
          </div>
          
          ${comp.description ? `<div class="comp-desc">${comp.description}</div>` : ''}
          
          <div class="comp-meta">
            ${comp.time_to_complete ? `<span>⏱️ ${comp.time_to_complete}</span>` : ''}
            ${comp.completion_date ? `<span>📅 ${comp.completion_date}</span>` : ''}
            <span style="color: ${comp.completed ? '#2ed573' : '#ffa502'}">
              ${comp.completed ? '✓ Completed' : '⏳ In Progress'}
            </span>
          </div>
          
          ${comp.notes ? `<div class="comp-notes">${comp.notes}</div>` : ''}
        </div>
      `;
    }).join('');
    
    if (isLoggedIn) {
      // Toggle completion status
      list.querySelectorAll('.toggle-comp').forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = parseInt(btn.dataset.id);
          const gameId = parseInt(btn.dataset.game);
          const comp = challenges.find(c => c.id === id);
          const newCompleted = comp.completed ? 0 : 1;
          
          await fetch(`/api/games/${gameId}/completionist/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...comp, completed: newCompleted })
          });
          
          loadChallenges();
        });
      });
      
      // Edit handlers
      list.querySelectorAll('.edit-comp-all').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = parseInt(btn.dataset.id);
          const comp = challenges.find(c => c.id === id);
          const gameId = parseInt(btn.dataset.game);
          showCompletionistModal(gameId, comp);
        });
      });
      
      // Delete handlers
      list.querySelectorAll('.delete-comp-all').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('Delete this challenge?')) return;
          
          const id = parseInt(btn.dataset.id);
          const gameId = parseInt(btn.dataset.game);
          await fetch(`/api/games/${gameId}/completionist/${id}`, {
            method: 'DELETE'
          });
          
          loadChallenges();
        });
      });
    }
  };
  
  await loadChallenges();
  
  filterSelect.addEventListener('change', loadChallenges);
  sortSelect.addEventListener('change', loadChallenges);
}

// Import/Export
document.getElementById('export-json').addEventListener('click', async () => {
  const res = await fetch('/api/games');
  const data = await res.json();
  document.getElementById('ie-data').value = JSON.stringify(data, null, 2);
});

document.getElementById('import-json').addEventListener('click', async () => {
  const raw = document.getElementById('ie-data').value;
  try {
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) throw new Error('JSON must be an array of games');
    
    if (!confirm(`Import ${arr.length} games? This will add to your existing library.`)) return;
    
    for (const game of arr) {
      await fetch('/api/games', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(game)
      });
    }
    
    alert('Import complete!');
    fetchGames();
  } catch (e) {
    alert('Invalid JSON: ' + e.message);
  }
});

// Initialize
checkAuth().then(() => {
  fetchGames();
  loadStats();
});

// Completionist Achievements Modal & Functions
let currentCompGame = null;
let currentCompEdit = null;

function showCompletionistModal(gameId, existing = null) {
  currentCompGame = gameId;
  currentCompEdit = existing;
  
  const modalHtml = `
    <div class="modal show" id="comp-modal">
      <div class="modal-content">
        <div class="modal-header">
          <h2>${existing ? 'Edit' : 'Add'} Completionist Challenge</h2>
          <button class="modal-close" onclick="closeCompModal()">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>Challenge Title *</label>
            <input type="text" id="comp-title" placeholder="e.g., 100% Completion, Platinum Trophy" value="${existing?.title || ''}" required />
          </div>
          
          <div class="form-group">
            <label>Description</label>
            <textarea id="comp-desc" rows="2" placeholder="What does this challenge involve?">${existing?.description || ''}</textarea>
          </div>
          
          <div class="form-row">
            <div class="form-group">
              <label>Difficulty (1-100) *</label>
              <input type="number" id="comp-difficulty" min="1" max="100" placeholder="50" value="${existing?.difficulty || ''}" required />
              <small style="opacity: 0.7; font-size: 12px;">Rate how hard this is/was to complete</small>
            </div>
            
            <div class="form-group">
              <label>Time to Complete</label>
              <input type="text" id="comp-time" placeholder="e.g., 50 hours, 3 months" value="${existing?.time_to_complete || ''}" />
            </div>
          </div>
          
          <div class="form-group">
            <label>Completion Date</label>
            <input type="date" id="comp-date" value="${existing?.completion_date || ''}" />
          </div>
          
          <div class="form-group">
            <label>
              <input type="checkbox" id="comp-completed" ${existing?.completed ? 'checked' : ''} />
              Challenge Completed
            </label>
          </div>
          
          <div class="form-group">
            <label>Notes</label>
            <textarea id="comp-notes" rows="3" placeholder="Tips, memorable moments, or anything else...">${existing?.notes || ''}</textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button onclick="closeCompModal()" class="btn secondary">Cancel</button>
          <button onclick="saveCompletionist()" class="btn primary">Save Challenge</button>
        </div>
      </div>
    </div>
  `;
  
  // Remove existing modal if any
  document.getElementById('comp-modal')?.remove();
  
  // Add new modal
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeCompModal() {
  document.getElementById('comp-modal')?.remove();
  currentCompGame = null;
  currentCompEdit = null;
}

async function saveCompletionist() {
  const title = document.getElementById('comp-title').value.trim();
  const difficulty = parseInt(document.getElementById('comp-difficulty').value);
  const completed = document.getElementById('comp-completed').checked ? 1 : 0;
  
  if (!title || !difficulty) {
    alert('Title and Difficulty are required');
    return;
  }
  
  if (difficulty < 1 || difficulty > 100) {
    alert('Difficulty must be between 1 and 100');
    return;
  }
  
  const data = {
    title,
    description: document.getElementById('comp-desc').value.trim(),
    difficulty,
    time_to_complete: document.getElementById('comp-time').value.trim(),
    completion_date: document.getElementById('comp-date').value || null,
    notes: document.getElementById('comp-notes').value.trim(),
    completed
  };
  
  try {
    if (currentCompEdit) {
      await fetch(`/api/games/${currentCompGame}/completionist/${currentCompEdit.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
    } else {
      await fetch(`/api/games/${currentCompGame}/completionist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
    }
    
    closeCompModal();
    const sortBy = document.getElementById('comp-sort')?.value || 'date';
    loadCompletionistAchievements(currentCompGame, sortBy);
  } catch (err) {
    alert('Error saving challenge: ' + err.message);
  }
}

async function loadCompletionistAchievements(gameId, sortBy = 'date') {
  const res = await fetch(`/api/games/${gameId}/completionist?sort=${sortBy}`);
  const achievements = await res.json();
  const list = document.getElementById('comp-list');
  
  if (achievements.length === 0) {
    list.innerHTML = '<div class="empty-state">No completionist challenges yet</div>';
    return;
  }
  
  list.innerHTML = achievements.map(comp => {
    const difficultyColor = comp.difficulty >= 80 ? '#ff4757' : 
                           comp.difficulty >= 50 ? '#ffa502' : 
                           '#2ed573';
    
    const editDeleteHtml = isLoggedIn ? `
      <div class="comp-actions">
        <button class="btn-icon toggle-comp-status" data-id="${comp.id}" data-completed="${comp.completed}" title="Toggle Status">
          ${comp.completed ? '✓' : '○'}
        </button>
        <button class="btn-icon edit-comp" data-id="${comp.id}" title="Edit">✏️</button>
        <button class="btn-icon delete-comp" data-id="${comp.id}" title="Delete">🗑️</button>
      </div>
    ` : '';
    
    return `
      <div class="completionist-card ${comp.completed ? 'completed' : ''}">
        <div class="comp-header">
          <div class="comp-title-section">
            <div class="comp-title ${comp.completed ? 'completed-strike' : ''}">${comp.title}</div>
            <div class="comp-difficulty" style="color: ${difficultyColor}">
              Difficulty: ${comp.difficulty}/100
            </div>
          </div>
          ${editDeleteHtml}
        </div>
        
        ${comp.description ? `<div class="comp-desc">${comp.description}</div>` : ''}
        
        <div class="comp-meta">
          ${comp.time_to_complete ? `<span>⏱️ ${comp.time_to_complete}</span>` : ''}
          ${comp.completion_date ? `<span>📅 ${comp.completion_date}</span>` : ''}
          <span style="color: ${comp.completed ? '#2ed573' : '#ffa502'}">
            ${comp.completed ? '✓ Completed' : '⏳ In Progress'}
          </span>
        </div>
        
        ${comp.notes ? `<div class="comp-notes">${comp.notes}</div>` : ''}
      </div>
    `;
  }).join('');
  
  if (isLoggedIn) {
    // Toggle completion status
    list.querySelectorAll('.toggle-comp-status').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = parseInt(btn.dataset.id);
        const comp = achievements.find(c => c.id === id);
        const newCompleted = comp.completed ? 0 : 1;
        
        await fetch(`/api/games/${gameId}/completionist/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...comp, completed: newCompleted })
        });
        
        loadCompletionistAchievements(gameId, sortBy);
      });
    });
    
    // Edit handlers
    list.querySelectorAll('.edit-comp').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.id);
        const comp = achievements.find(c => c.id === id);
        showCompletionistModal(gameId, comp);
      });
    });
    
    // Delete handlers
    list.querySelectorAll('.delete-comp').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this challenge?')) return;
        
        const id = parseInt(btn.dataset.id);
        await fetch(`/api/games/${gameId}/completionist/${id}`, {
          method: 'DELETE'
        });
        
        loadCompletionistAchievements(gameId, sortBy);
      });
    });
  }
}