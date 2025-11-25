// Global state
let allGames = [];
let currentEditId = null;
let isLoggedIn = false;
let currentSort = localStorage.getItem('gameTracker_sort') || 'recent';
let currentFilters = {
  status: '',
  platform: '',
  search: ''
};

function loadSavedFilters() {
  const savedStatus = localStorage.getItem('gameTracker_filter_status');
  const savedPlatform = localStorage.getItem('gameTracker_filter_platform');
  const savedSearch = localStorage.getItem('gameTracker_filter_search');
  
  if (savedStatus) {
    document.getElementById('filter-status').value = savedStatus;
    currentFilters.status = savedStatus;
  }
  if (savedPlatform) {
    document.getElementById('filter-platform').value = savedPlatform;
    currentFilters.platform = savedPlatform;
  }
  if (savedSearch) {
    document.getElementById('search').value = savedSearch;
    currentFilters.search = savedSearch;
  }
}

// Save filters when they change
function saveFilters() {
  localStorage.setItem('gameTracker_filter_status', currentFilters.status);
  localStorage.setItem('gameTracker_filter_platform', currentFilters.platform);
  localStorage.setItem('gameTracker_filter_search', currentFilters.search);
}

// Sorting and filtering functionality
document.getElementById('sort-by').addEventListener('change', (e) => {
  currentSort = e.target.value;
  localStorage.setItem('gameTracker_sort', currentSort);
  applySortingAndFiltering();
});

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
  });
});

// Fetch and render games
async function fetchGames() {
  const res = await fetch('/api/games');
  allGames = await res.json();
  applySortingAndFiltering();
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
    
    // Update card head to include favorite star
    const cardHead = el.querySelector('.card-head');
    cardHead.innerHTML = `
      <div class="game-title-wrapper">
        ${isLoggedIn ? `
          <button class="favorite-star ${game.is_favorite ? 'favorited' : ''}" 
                  data-id="${game.id}" title="${game.is_favorite ? 'Remove from favorites' : 'Add to favorites'}">
            ${game.is_favorite ? '⭐' : '☆'}
          </button>
        ` : ''}
        <strong class="game-title">${game.title}</strong>
      </div>
      <span class="game-platform badge">${game.platform || ''}</span>
    `;
    
    el.querySelector('.game-notes').textContent = game.notes || '';
    el.querySelector('.game-status').textContent = game.status || '';
    el.querySelector('.game-status').className = `game-status badge status-${(game.status || '').toLowerCase()}`;
    
    // Rating stars
    const rating = el.querySelector('.game-rating');
    if (game.rating) {
      rating.textContent = '★'.repeat(game.rating) + '☆'.repeat(5 - game.rating);
    } else {
      rating.textContent = '☆☆☆☆☆';
    }
    
    // Hours played
    const hours = el.querySelector('.game-hours');
    if (game.hours_played) {
      hours.textContent = `⏱️ ${game.hours_played}h`;
    } else {
      hours.textContent = '⏱️ 0h';
    }
    
    // Tags
    const tagsEl = el.querySelector('.game-tags');
    if (game.tags && game.tags.length > 0) {
      tagsEl.innerHTML = game.tags.map(tag => 
        `<span class="tag">${tag}</span>`
      ).join('');
    }
    
    // Action buttons
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
      
      // Favorite button
      const favoriteBtn = el.querySelector('.favorite-star');
      if (favoriteBtn) {
        favoriteBtn.addEventListener('click', async () => {
          await toggleFavorite(game.id);
        });
      }
    }
    
    list.appendChild(el);
  });
}

// Sorting and filtering functionality
document.getElementById('sort-by').addEventListener('change', (e) => {
  currentSort = e.target.value;
  applySortingAndFiltering();
});

// Update filter functions to use new state
function filterGames() {
  currentFilters.search = document.getElementById('search').value.toLowerCase();
  currentFilters.status = document.getElementById('filter-status').value;
  currentFilters.platform = document.getElementById('filter-platform').value;
  
  saveFilters();
  applySortingAndFiltering();
}

// Initialize event listeners for filtering
document.getElementById('search').addEventListener('input', filterGames);
document.getElementById('filter-status').addEventListener('change', filterGames);
document.getElementById('filter-platform').addEventListener('change', filterGames);

// Initialize
checkAuth().then(() => {
  loadSavedFilters();
  fetchGames();
  loadStats();
  
  // Set sort option from localStorage
  document.getElementById('sort-by').value = currentSort;
});

// Initialize event listeners for filtering
document.getElementById('search').addEventListener('input', filterGames);
document.getElementById('filter-status').addEventListener('change', filterGames);
document.getElementById('filter-platform').addEventListener('change', filterGames);

// Main sorting and filtering function
function applySortingAndFiltering() {
  let filtered = [...allGames];
  
  // Apply filters
  filtered = filtered.filter(game => {
    const matchSearch = currentFilters.search === '' || 
                       game.title.toLowerCase().includes(currentFilters.search) ||
                       (game.notes || '').toLowerCase().includes(currentFilters.search) ||
                       (game.tags || []).some(t => t.toLowerCase().includes(currentFilters.search));
    
    const matchStatus = !currentFilters.status || game.status === currentFilters.status;
    const matchPlatform = !currentFilters.platform || game.platform === currentFilters.platform;
    
    return matchSearch && matchStatus && matchPlatform;
  });
  
  // Apply sorting
  filtered.sort((a, b) => {
    switch (currentSort) {
      case 'title':
        return a.title.localeCompare(b.title);
      
      case 'title-desc':
        return b.title.localeCompare(a.title);
      
      case 'hours':
        return (b.hours_played || 0) - (a.hours_played || 0);
      
      case 'hours-asc':
        return (a.hours_played || 0) - (b.hours_played || 0);
      
      case 'rating':
        return (b.rating || 0) - (a.rating || 0);
      
      case 'rating-asc':
        return (a.rating || 0) - (b.rating || 0);
      
      case 'status':
        return (a.status || '').localeCompare(b.status || '');
      
      case 'platform':
        return (a.platform || '').localeCompare(b.platform || '');
      
      case 'recent':
      default:
        return new Date(b.created_at) - new Date(a.created_at);
    }
  });
  
  renderGames(filtered);
}

// Toggle favorite function
async function toggleFavorite(gameId) {
  try {
    const response = await fetch(`/api/games/${gameId}/favorite`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' }
    });
    
    if (response.ok) {
      const result = await response.json();
      
      // Update the game in allGames array
      const gameIndex = allGames.findIndex(g => g.id === gameId);
      if (gameIndex !== -1) {
        allGames[gameIndex].is_favorite = result.is_favorite;
        applySortingAndFiltering(); // Re-render with updated favorite status
      }
    }
  } catch (err) {
    console.error('Error toggling favorite:', err);
  }
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
      window.location.reload();
      return;
    }
    
    closeModal();
    fetchGames();

    const autoImportAppId = sessionStorage.getItem('autoImportAchievements');
    if (autoImportAppId && !currentEditId) { // Only for new games, not edits
      // Find the newly created game (it should be the first one in the list)
      setTimeout(async () => {
        const gamesRes = await fetch('/api/games');
        const games = await gamesRes.json();
        const newGame = games.find(g => g.steam_app_id == autoImportAppId);
        
        if (newGame) {
          await importAchievementsForGame(newGame.id, autoImportAppId);
        }
        
        sessionStorage.removeItem('autoImportAchievements');
      }, 1000);
    }
  } catch (err) {
    alert('Error saving game: ' + err.message);
  }
});

// Function to import achievements for a specific game
async function importAchievementsForGame(gameId, steamAppId) {
  try {
    const res = await fetch(`/api/steam/achievements/${steamAppId}`);
    const achievements = await res.json();
    
    if (achievements.length === 0) {
      alert('No achievements found for this game on Steam.');
      return;
    }
    
    // Delete existing achievements first to avoid duplicates
    const existingAchRes = await fetch(`/api/games/${gameId}/achievements`);
    const existingAchievements = await existingAchRes.json();
    
    // Delete all existing achievements
    for (const ach of existingAchievements) {
      await fetch(`/api/games/${gameId}/achievements/${ach.id}`, {
        method: 'DELETE'
      });
    }
    
    // Import new achievements
    let importedCount = 0;
    for (const ach of achievements) {
      await fetch(`/api/games/${gameId}/achievements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: ach.name,
          description: ach.description,
          date: ach.unlock_date || null,
          unlocked: ach.achieved || 0,
          icon_url: ach.icon
        })
      });
      importedCount++;
    }
    
    alert(`Imported ${importedCount} achievements for this game!`);
    
    // Refresh achievements view if we're on the achievements tab
    if (document.getElementById('tab-achievements').classList.contains('active')) {
      const currentGame = allGames.find(g => g.id === gameId);
      if (currentGame) {
        openAchievements(currentGame);
      }
    }
  } catch (err) {
    alert('Error importing achievements: ' + err.message);
  }
}

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
          
          // Auto-check if achievements are available and offer to import
          const achRes = await fetch(`/api/steam/achievements/${el.dataset.id}`);
          const achievements = await achRes.json();
          
          if (achievements.length > 0) {
            resultsDiv.innerHTML += '<div class="success" style="margin-top: 8px;">🎮 ' + achievements.length + ' achievements available</div>';
            // Automatically import achievements when game is saved
            sessionStorage.setItem('autoImportAchievements', el.dataset.id);
          }
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
  document.getElementById('stat-achievements').textContent = stats.total_achievements;
  
  // Achievement progress list
  const progressList = document.getElementById('achievement-progress-list');
  if (stats.achievement_progress && stats.achievement_progress.length > 0) {
    progressList.innerHTML = stats.achievement_progress.map(game => {
      const percentage = Math.round((game.unlocked_achievements / game.total_achievements) * 100);
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

// Steam library import
document.getElementById('import-steam-library').addEventListener('click', async () => {
  if (!isLoggedIn) {
    alert('Please login to import Steam library');
    return;
  }
  
  const importAchievements = document.getElementById('import-achievements').checked;
  
  let confirmMessage = 'Import your Steam library? This will add all games from your Steam account.';
  if (importAchievements) {
    confirmMessage += ' AND automatically import their achievements.';
  } else {
    confirmMessage += ' (Achievements will NOT be imported).';
  }
  
  if (!confirm(confirmMessage)) return;
  
  const btn = document.getElementById('import-steam-library');
  const originalText = btn.textContent;
  btn.textContent = 'Importing...';
  btn.disabled = true;
  
  try {
    const res = await fetch('/api/steam/import-library', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({ 
        import_achievements: importAchievements 
      })
    });
    
    // Check if response is OK
    if (!res.ok) {
      // Try to get error message from response
      let errorMsg = `Server returned ${res.status}: ${res.statusText}`;
      try {
        const errorData = await res.json();
        if (errorData.error) {
          errorMsg = errorData.error;
        }
      } catch {
        // If we can't parse JSON, use the status text
      }
      throw new Error(errorMsg);
    }
    
    const result = await res.json();
    
    if (result.success) {
      let message = `Successfully imported ${result.imported} games from Steam`;
      if (importAchievements && result.achievements_imported > 0) {
        message += ` with ${result.achievements_imported} achievements`;
      }
      if (result.skipped > 0) {
        message += ` (skipped ${result.skipped} duplicates)`;
      }
      if (importAchievements && result.achievements_failed > 0) {
        message += ` - ${result.achievements_failed} games had no achievements`;
      }
      alert(message);
      fetchGames();
    } else {
      alert('Failed to import Steam library: ' + result.error);
    }
  } catch (err) {
    console.error('Import error:', err);
    alert('Error importing Steam library: ' + err.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
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
              <small style="opacity: 0.7; font-size: 12px;">Rate how hard this was to complete</small>
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
    notes: document.getElementById('comp-notes').value.trim()
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
        <button class="btn-icon edit-comp" data-id="${comp.id}" title="Edit">✏️</button>
        <button class="btn-icon delete-comp" data-id="${comp.id}" title="Delete">🗑️</button>
      </div>
    ` : '';
    
    return `
      <div class="completionist-card">
        <div class="comp-header">
          <div class="comp-title-section">
            <div class="comp-title">${comp.title}</div>
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
        </div>
        
        ${comp.notes ? `<div class="comp-notes">${comp.notes}</div>` : ''}
      </div>
    `;
  }).join('');
  
  if (isLoggedIn) {
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
        
        const sortBy = document.getElementById('comp-sort')?.value || 'date';
        loadCompletionistAchievements(gameId, sortBy);
      });
    });
  }
}

// Initialize
checkAuth().then(() => {
  fetchGames();
  loadStats();
  
  // Set default sort option
  document.getElementById('sort-by').value = currentSort;
});

// Add to your app.js
document.getElementById('fix-images')?.addEventListener('click', async () => {
  if (!confirm('This will fix image associations for all Steam games. Continue?')) return;
  
  const btn = document.getElementById('fix-images');
  const originalText = btn.textContent;
  btn.textContent = 'Fixing...';
  btn.disabled = true;
  
  try {
    const res = await fetch('/api/fix-image-associations', { method: 'POST' });
    const result = await res.json();
    
    const resultDiv = document.getElementById('admin-tools-result');
    if (result.success) {
      resultDiv.innerHTML = `<div class="success">✓ ${result.message}</div>`;
      if (result.errors && result.errors.length > 0) {
        resultDiv.innerHTML += `<div class="error" style="margin-top: 8px;">Errors: ${result.errors.join(', ')}</div>`;
      }
      // Refresh games to show fixed images
      fetchGames();
    } else {
      resultDiv.innerHTML = `<div class="error">❌ ${result.error}</div>`;
    }
  } catch (err) {
    document.getElementById('admin-tools-result').innerHTML = `<div class="error">Error: ${err.message}</div>`;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
});

document.getElementById('cleanup-images')?.addEventListener('click', async () => {
  if (!confirm('This will remove unused image files. Continue?')) return;
  
  const btn = document.getElementById('cleanup-images');
  const originalText = btn.textContent;
  btn.textContent = 'Cleaning...';
  btn.disabled = true;
  
  try {
    const res = await fetch('/api/cleanup-orphaned-images', { method: 'POST' });
    const result = await res.json();
    
    const resultDiv = document.getElementById('admin-tools-result');
    if (result.success) {
      resultDiv.innerHTML = `<div class="success">✓ ${result.message}</div>`;
    } else {
      resultDiv.innerHTML = `<div class="error">❌ ${result.error}</div>`;
    }
  } catch (err) {
    document.getElementById('admin-tools-result').innerHTML = `<div class="error">Error: ${err.message}</div>`;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
});