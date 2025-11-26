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
let batchMode = false;
let selectedGames = new Set();
let top10Games = [];
let isEditingTop10 = false;

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
  
  // Update auth indicator - no emoji
  const indicator = document.getElementById('auth-indicator');
  if (isLoggedIn) {
    indicator.innerHTML = 'Admin Mode';
    indicator.style.color = '#2ed573';
  } else {
    indicator.innerHTML = 'View Only';
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
    
    // BATCH SELECTION CHECKBOX
    if (batchMode) {
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'select-checkbox';
      checkbox.checked = selectedGames.has(game.id);
      checkbox.addEventListener('change', (e) => {
        if (e.target.checked) {
          selectedGames.add(game.id);
        } else {
          selectedGames.delete(game.id);
        }
        // Add selected class for visual feedback
        const card = checkbox.closest('.game-card');
        if (e.target.checked) {
          card.classList.add('selected');
        } else {
          card.classList.remove('selected');
        }
      });
      
      // Position the checkbox in the top-left corner
      checkbox.style.position = 'absolute';
      checkbox.style.top = '8px';
      checkbox.style.left = '8px';
      checkbox.style.zIndex = '10';
      checkbox.style.width = '18px';
      checkbox.style.height = '18px';
      checkbox.style.accentColor = 'var(--accent)';
      
      cover.style.position = 'relative';
      cover.appendChild(checkbox);
    }
    
    // Card head with favorite star
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
    
    // Card row: Hours on left, rating on right
    const cardRow = el.querySelector('.card-row');
    
    // Hours played
    const hours = el.querySelector('.game-hours');
    if (game.hours_played) {
      hours.textContent = `Time: ${game.hours_played}h`;
    } else {
      hours.textContent = 'Time: 0h';
    }
    
    // Rating stars
    const rating = el.querySelector('.game-rating');
    if (game.rating) {
      rating.textContent = '★'.repeat(game.rating) + '☆'.repeat(5 - game.rating);
    } else {
      rating.textContent = '☆☆☆☆☆';
    }
    
    // Tags
    const tagsEl = el.querySelector('.game-tags');
    if (game.tags && game.tags.length > 0) {
      tagsEl.innerHTML = game.tags.map(tag => 
        `<span class="tag">${tag}</span>`
      ).join('');
    }
    
    // Achievement progress bar
    const cardBody = el.querySelector('.card-body');
    
    if (game.achievement_progress && game.achievement_progress.total_achievements > 0) {
      const unlocked = game.achievement_progress.unlocked_achievements || 0;
      const total = game.achievement_progress.total_achievements;
      const percentage = Math.round((unlocked / total) * 100);
      
      const progressBar = document.createElement('div');
      progressBar.className = 'achievement-progress-mini';
      progressBar.innerHTML = `
        <div class="progress-info">
          <span>Achievements: ${unlocked}/${total}</span>
          <span>${percentage}%</span>
        </div>
        <div class="progress-bar-mini">
          <div class="progress-fill-mini" style="width: ${percentage}%"></div>
        </div>
        <div class="completion-percentage">Completion: ${percentage}%</div>
      `;
      
      // Insert progress bar before the card actions
      const cardActions = cardBody.querySelector('.card-actions');
      cardBody.insertBefore(progressBar, cardActions);
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
      const updateBtn = el.querySelector('.update-steam');
      
      if (editBtn && deleteBtn) {
        editBtn.style.display = '';
        deleteBtn.style.display = '';
        editBtn.addEventListener('click', () => editGame(game));
        deleteBtn.addEventListener('click', () => deleteGame(game.id));
      }
      
      // Update Steam button - only show for Steam games
      if (updateBtn && game.steam_app_id) {
        updateBtn.style.display = '';
        updateBtn.addEventListener('click', () => updateGameFromSteam(game.id));
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

// Update single game from Steam
async function updateGameFromSteam(gameId) {
  if (!isLoggedIn) {
    alert('Please login to update games');
    return;
  }
  
  if (!confirm('Update this game from Steam? This will refresh hours played AND achievements. Existing achievements will be replaced.')) return;
  
  try {
    const res = await fetch(`/api/steam/update-game/${gameId}`, { method: 'POST' });
    const result = await res.json();
    
    if (result.success) {
      let message = `Updated game from Steam`;
      if (result.hours_updated) message += ' - hours refreshed';
      if (result.achievements_updated > 0) message += ` - ${result.achievements_updated} achievements updated`;
      
      // Check if we should set completion date
      if (result.all_achievements_unlocked) {
        message += ` - All achievements unlocked! Completion date set to ${result.completion_date}`;
        
        // Update the local game data
        const gameIndex = allGames.findIndex(g => g.id === gameId);
        if (gameIndex !== -1) {
          allGames[gameIndex].status = 'Completed';
          allGames[gameIndex].completion_date = result.completion_date;
        }
      }
      
      alert(message);
      fetchGames(); // Refresh the list
    } else {
      alert('Failed to update game: ' + result.error);
    }
  } catch (err) {
    alert('Error updating game: ' + err.message);
  }
}

// Update all games from Steam
document.getElementById('update-all-steam')?.addEventListener('click', async () => {
  if (!isLoggedIn) {
    alert('Please login to update games');
    return;
  }
  
  if (!confirm('Update ALL Steam games? This will refresh hours played only - achievements will NOT be updated.')) return;
  
  const btn = document.getElementById('update-all-steam');
  const originalText = btn.textContent;
  btn.textContent = 'Updating...';
  btn.disabled = true;
  
  try {
    const res = await fetch('/api/steam/update-all-games', { method: 'POST' });
    const result = await res.json();
    
    if (result.success) {
      let message = `Updated hours for ${result.hours_updated} games from Steam`;
      alert(message);
      fetchGames();
    } else {
      alert('Failed to update games: ' + result.error);
    }
  } catch (err) {
    alert('Error updating games: ' + err.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
});

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

document.getElementById('edit-top10').addEventListener('click', openTop10Editor);
document.getElementById('cancel-edit-top10').addEventListener('click', cancelTop10Edit);
document.getElementById('save-top10').addEventListener('click', saveTop10);
document.getElementById('save-top10-modal').addEventListener('click', saveTop10);

function setupTop10EventListeners() {
    // Wait for DOM to be ready and elements to exist
    setTimeout(() => {
        const editBtn = document.getElementById('edit-top10');
        const cancelEditBtn = document.getElementById('cancel-edit-top10');
        const saveBtn = document.getElementById('save-top10');
        const saveModalBtn = document.getElementById('save-top10-modal');
        
        console.log('Setting up Top 10 event listeners...');
        console.log('Edit button:', editBtn);
        console.log('Cancel button:', cancelEditBtn);
        console.log('Save button:', saveBtn);
        console.log('Save modal button:', saveModalBtn);
        
        if (editBtn) {
            editBtn.addEventListener('click', openTop10Editor);
            console.log('Edit button listener added');
        } else {
            console.error('Edit button not found!');
        }
        
        if (cancelEditBtn) {
            cancelEditBtn.addEventListener('click', cancelTop10Edit);
        }
        
        if (saveBtn) {
            saveBtn.addEventListener('click', saveTop10);
        }
        
        if (saveModalBtn) {
            saveModalBtn.addEventListener('click', saveTop10);
        }
    }, 100);
}

// Initialize everything when auth is checked
checkAuth().then(() => {
  console.log('Starting app initialization...');
  loadSavedFilters();
  fetchGames();
  loadStats();
  loadTop10();
  setupTop10Modal();
  setupTop10Search();
  setupTop10EventListeners();
  setupBatchOperations();
  
  // Set default sort option
  document.getElementById('sort-by').value = currentSort;
  
  console.log('App initialization complete');
  
  // Debug: Check batch actions setup
  setTimeout(() => {
    checkBatchActionsSetup();
  }, 1000);
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
      
      // NEW: Completion sorting cases
      case 'completion':
        const aComp = a.achievement_progress?.completion_percentage || 0;
        const bComp = b.achievement_progress?.completion_percentage || 0;
        return bComp - aComp;
      
      case 'completion-asc':
        const aCompAsc = a.achievement_progress?.completion_percentage || 0;
        const bCompAsc = b.achievement_progress?.completion_percentage || 0;
        return aCompAsc - bCompAsc;
      
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
    
    if (!confirm(`Import ${achievements.length} achievements from Steam? This will replace ALL existing achievements for this game.`)) return;
    
    // Clear existing achievements first to avoid duplicates
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
      <div class="game-info-header">
        <h2>${game.title}</h2>
        <div class="game-meta-row">
          <span class="game-hours">${game.hours_played ? `${game.hours_played}h` : '0h'}</span>
          <span class="game-status badge status-${(game.status || '').toLowerCase()}">${game.status || ''}</span>
          <span class="game-rating">${game.rating ? '★'.repeat(game.rating) + '☆'.repeat(5 - game.rating) : '☆☆☆☆☆'}</span>
        </div>
      </div>
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
        
        if (!confirm(`Import ${achievements.length} achievements from Steam? This will replace ALL existing achievements for this game.`)) return;
        
        importBtn.disabled = true;
        importBtn.textContent = 'Importing...';
        
        // Clear existing achievements first
        const existingAchRes = await fetch(`/api/games/${game.id}/achievements`);
        const existingAchievements = await existingAchRes.json();
        
        for (const ach of existingAchievements) {
          await fetch(`/api/games/${game.id}/achievements/${ach.id}`, {
            method: 'DELETE'
          });
        }
        
        // Import new achievements
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
    document.getElementById('ach-progress-fill').style.width = '0%';
    return;
  }
  
  // Calculate progress
  const unlocked = achievements.filter(a => a.unlocked).length;
  const total = achievements.length;
  const percentage = Math.round((unlocked / total) * 100);
  
  // Update progress bar with animation
  const progressFill = document.getElementById('ach-progress-fill');
  const progressText = document.getElementById('ach-progress-text');
  
  // Reset to 0 then animate to target percentage
  progressFill.style.width = '0%';
  progressText.textContent = '0 / 0 (0%)';
  
  // Use setTimeout to ensure the reset is rendered before animation
  setTimeout(() => {
    progressFill.style.width = percentage + '%';
    progressText.textContent = `${unlocked} / ${total} (${percentage}%)`;
  }, 50);
  
  const actionsHtml = isLoggedIn ? `
    <div class="ach-actions">
      <button class="btn-icon toggle-ach" data-id="ACH_ID" data-game="GAME_ID" data-unlocked="UNLOCKED">
        TOGGLE_ICON
      </button>
      <button class="btn-icon delete-ach" data-id="ACH_ID" data-game="GAME_ID">🗑️</button>
    </div>
  ` : '';
  
  list.innerHTML = achievements.map((ach, index) => {
    const actions = actionsHtml
      .replace(/ACH_ID/g, ach.id)
      .replace(/GAME_ID/g, gameId)
      .replace('UNLOCKED', ach.unlocked)
      .replace('TOGGLE_ICON', ach.unlocked ? '✓' : '○');
    
    // Add staggered animation delay based on index
    const animationDelay = 0.1 + (index * 0.05);
    
    return `
      <div class="achievement-card ${ach.unlocked ? 'unlocked' : 'locked'}" 
           style="animation-delay: ${animationDelay}s">
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
        
        // Add loading state
        btn.disabled = true;
        btn.innerHTML = '⏳';
        
        await fetch(`/api/games/${gameId}/achievements/${achId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ unlocked })
        });
        
        // Reload achievements with animation
        await loadAchievements(gameId);
      });
    });
    
    // Delete achievement
    list.querySelectorAll('.delete-ach').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this achievement?')) return;
        
        const achId = btn.dataset.id;
        const gameId = btn.dataset.game;
        
        // Add loading state
        btn.disabled = true;
        btn.innerHTML = '⏳';
        
        await fetch(`/api/games/${gameId}/achievements/${achId}`, {
          method: 'DELETE'
        });
        
        // Reload achievements with animation
        await loadAchievements(gameId);
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
  document.getElementById('stat-achievements').textContent = stats.achievements_unlocked + ' / ' + stats.achievements_total;
  
  // Remove achievement progress list section entirely
  const progressList = document.getElementById('achievement-progress-list');
  progressList.innerHTML = ''; // Clear it
  progressList.style.display = 'none'; // Hide it
  
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
  
  // Recent completions with game info layout
  const recentCompletions = document.getElementById('recent-completions');
  if (stats.recent_completions && stats.recent_completions.length > 0) {
    recentCompletions.innerHTML = stats.recent_completions.map(game => `
      <div class="completion-item">
        ${game.cover_url ? `<img src="${game.cover_url}" class="completion-cover" />` : ''}
        <div class="completion-info">
          <div class="completion-title">${game.title}</div>
          <div class="completion-meta">
            <span class="completion-hours">${game.hours_played ? `${game.hours_played}h` : '0h'}</span>
            <span class="completion-rating">${game.rating ? '★'.repeat(game.rating) + '☆'.repeat(5 - game.rating) : '☆☆☆☆☆'}</span>
          </div>
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
  
  const importAchievements = False;
  
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

// ========== RANDOM GAME PICKER ==========
document.getElementById('pick-random-game').addEventListener('click', pickRandomGame);
document.getElementById('reroll-random').addEventListener('click', pickRandomGame);

async function pickRandomGame() {
  const status = document.getElementById('random-filter-status').value;
  const platform = document.getElementById('random-filter-platform').value;
  const maxHours = document.getElementById('random-filter-hours').value;
  
  try {
    const url = new URL('/api/random-game', window.location.origin);
    if (status !== 'all') url.searchParams.append('status', status);
    if (platform !== 'all') url.searchParams.append('platform', platform);
    if (maxHours !== '0') url.searchParams.append('max_hours', maxHours);
    
    const res = await fetch(url);
    const game = await res.json();
    
    if (res.status === 404) {
      document.getElementById('random-result').innerHTML = `
        <div class="empty-state">${game.error}</div>
      `;
      return;
    }
    
    displayRandomGame(game);
    document.getElementById('reroll-random').style.display = '';
    
  } catch (err) {
    document.getElementById('random-result').innerHTML = `
      <div class="error">Error picking random game: ${err.message}</div>
    `;
  }
}

function displayRandomGame(game) {
  // Get achievement data - check both possible locations
  let achievementText = 'No achievements';
  let unlocked = 0;
  let total = 0;
  
  if (game.achievement_progress) {
    unlocked = game.achievement_progress.unlocked_achievements || 0;
    total = game.achievement_progress.total_achievements || 0;
  } else if (game.unlocked_achievements !== undefined && game.total_achievements !== undefined) {
    unlocked = game.unlocked_achievements;
    total = game.total_achievements;
  }
  
  if (total > 0) {
    const percentage = Math.round((unlocked / total) * 100);
    achievementText = `${unlocked}/${total} achievements (${percentage}%)`;
  }
  
  document.getElementById('random-result').innerHTML = `
    <div class="random-game-card">
      ${game.cover_url ? `<img src="${game.cover_url}" alt="${game.title}" style="width: 200px; height: 100px; object-fit: cover; border-radius: 8px; margin-bottom: 16px;">` : ''}
      <h3>${game.title}</h3>
      <div class="random-game-meta">
        <span class="badge">${game.platform || 'No platform'}</span>
        <span class="badge status-${(game.status || '').toLowerCase()}">${game.status || 'No status'}</span>
        <span>${game.hours_played || 0}h</span>
      </div>
      <p style="color: var(--text-muted); margin-bottom: 16px;">${achievementText}</p>
      ${game.notes ? `<p style="font-style: italic;">"${game.notes}"</p>` : ''}
      <div class="random-game-actions" style="margin-top: 16px;">
        <button class="btn small" onclick="openAchievementsFromRandom(${game.id})">View Achievements</button>
        ${game.steam_app_id && isLoggedIn ? `<button class="btn small secondary" onclick="updateGameFromSteam(${game.id})">Update from Steam</button>` : ''}
      </div>
    </div>
  `;
  
  document.getElementById('reroll-random').style.display = '';
}

// Helper function to open achievements from random game
function openAchievementsFromRandom(gameId) {
  const game = allGames.find(g => g.id === gameId);
  if (game) {
    // Switch to achievements tab and open this game's achievements
    document.querySelector('[data-tab="achievements"]').click();
    setTimeout(() => {
      openAchievements(game);
    }, 100);
  }
}

// Top 10 Modal Management
function setupTop10Modal() {
    const modal = document.getElementById('top10-modal');
    const closeBtn = modal.querySelector('.modal-close');
    const cancelBtn = document.getElementById('cancel-top10');
    
    // Remove existing event listeners to prevent duplicates
    closeBtn.replaceWith(closeBtn.cloneNode(true));
    cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    
    // Add new event listeners
    modal.querySelector('.modal-close').addEventListener('click', closeTop10Modal);
    document.getElementById('cancel-top10').addEventListener('click', closeTop10Modal);
    
    // Close modal when clicking outside
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeTop10Modal();
        }
    });
    
    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('show')) {
            closeTop10Modal();
        }
    });
}

function closeTop10Modal() {
    const modal = document.getElementById('top10-modal');
    modal.classList.remove('show');
    cancelTop10Edit(); // Reset editing state
}

function openTop10Editor() {
    console.log('openTop10Editor called'); // Debug log
    
    if (!isLoggedIn) {
        alert('Please login to edit Top 10');
        return;
    }
    
    const modal = document.getElementById('top10-modal');
    if (!modal) {
        console.error('Top 10 modal not found!');
        alert('Error: Top 10 modal not found');
        return;
    }
    
    isEditingTop10 = true;
    
    // Hide/show the right buttons
    const editBtn = document.getElementById('edit-top10');
    const saveBtn = document.getElementById('save-top10');
    const cancelEditBtn = document.getElementById('cancel-edit-top10');
    
    if (editBtn) editBtn.style.display = 'none';
    if (saveBtn) saveBtn.style.display = '';
    if (cancelEditBtn) cancelEditBtn.style.display = '';
    
    // Clear the available games list initially
    const availableGames = document.getElementById('available-games');
    if (availableGames) {
        availableGames.innerHTML = '<div class="empty-state">Search for games to add to your Top 10</div>';
    }
    
    const searchInput = document.getElementById('top10-search');
    if (searchInput) {
        searchInput.value = '';
    }
    
    console.log('Opening modal...');
    modal.classList.add('show');
}

// Available games for Top 10 editor - Search-based
// Available games for Top 10 editor - Search-based
function setupTop10Search() {
    const searchInput = document.getElementById('top10-search');
    
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.trim().toLowerCase();
        
        if (searchTerm.length < 2) {
            // Show empty state for short searches
            document.getElementById('available-games').innerHTML = '<div class="empty-state">Type at least 2 characters to search</div>';
            return;
        }
        
        searchAvailableGames(searchTerm);
    });
    
    // Add debounced search for better performance
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const searchTerm = e.target.value.trim().toLowerCase();
        
        if (searchTerm.length < 2) {
            document.getElementById('available-games').innerHTML = '<div class="empty-state">Type at least 2 characters to search</div>';
            return;
        }
        
        searchTimeout = setTimeout(() => {
            searchAvailableGames(searchTerm);
        }, 300);
    });
}

function searchAvailableGames(searchTerm) {
    const availableList = document.getElementById('available-games');
    
    // Show loading state
    availableList.innerHTML = '<div class="loading">Searching games...</div>';
    
    // Filter games based on search term
    const filteredGames = allGames.filter(game => 
        !top10Games.some(top10 => top10.game_id === game.id) &&
        (game.title.toLowerCase().includes(searchTerm) ||
         (game.tags || []).some(tag => tag.toLowerCase().includes(searchTerm)) ||
         (game.platform || '').toLowerCase().includes(searchTerm))
    );
    
    if (filteredGames.length === 0) {
        availableList.innerHTML = '<div class="empty-state">No games found matching "' + searchTerm + '"</div>';
        return;
    }
    
    // Display search results
    availableList.innerHTML = filteredGames.map(game => `
        <div class="available-game-item" data-game-id="${game.id}">
            <div style="flex: 1;">
                <strong>${game.title}</strong>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                    ${game.platform} • ${game.hours_played || 0}h • ${game.status}
                    ${game.tags && game.tags.length > 0 ? `• ${game.tags.slice(0, 2).join(', ')}` : ''}
                </div>
            </div>
            <button class="btn small" style="flex-shrink: 0;">Add</button>
        </div>
    `).join('');
    
    // Add click handlers to search results
    availableList.querySelectorAll('.available-game-item').forEach(item => {
        const addBtn = item.querySelector('button');
        const gameId = parseInt(item.dataset.gameId);
        
        addBtn.addEventListener('click', () => {
            addGameToTop10(gameId);
        });
        
        // Also make the whole item clickable
        item.addEventListener('click', (e) => {
            if (e.target !== addBtn) {
                addGameToTop10(gameId);
            }
        });
    });
}

function addGameToTop10(gameId) {
    if (top10Games.length >= 10) {
        alert('Top 10 is full! Remove a game first.');
        return;
    }
    
    const game = allGames.find(g => g.id === gameId);
    if (game) {
        top10Games.push({
            game_id: game.id,
            title: game.title,
            platform: game.platform,
            hours_played: game.hours_played,
            rating: game.rating,
            cover_url: game.cover_url,
            why_i_love_it: ''
        });
        
        // Refresh both lists
        renderTop10Selection();
        
        // Clear search and show success message
        document.getElementById('top10-search').value = '';
        document.getElementById('available-games').innerHTML = '<div class="success">Game added! Search for more games...</div>';
    }
}

function renderTop10Selection() {
    const selectionList = document.getElementById('top10-selection');
    
    if (top10Games.length === 0) {
        selectionList.innerHTML = '<div class="empty-state">No games in your Top 10 yet. Search and add games above!</div>';
        return;
    }
    
    selectionList.innerHTML = top10Games.map((game, index) => `
        <div class="top10-selection-item" data-game-id="${game.game_id}">
            <div class="drag-handle" style="cursor: move;">⋮⋮</div>
            <div class="game-info" style="flex: 1;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    ${game.cover_url ? `<img src="${game.cover_url}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 4px;">` : ''}
                    <div>
                        <strong>#${index + 1}. ${game.title}</strong>
                        <div style="font-size: 12px; color: var(--text-muted);">
                            ${game.platform} • ${game.hours_played || 0}h
                        </div>
                    </div>
                </div>
                <textarea 
                    class="why-i-love-it" 
                    placeholder="Why I love this game..."
                    style="width: 100%; margin-top: 8px; padding: 8px; border: var(--thin-border); border-radius: 4px; background: rgba(0,0,0,0.3); color: var(--text-color); font-size: 12px; resize: vertical; min-height: 60px;"
                    oninput="updateTop10Reason(${game.game_id}, this.value)"
                >${game.why_i_love_it || ''}</textarea>
            </div>
            <button class="remove-game btn-icon" onclick="removeFromTop10(${game.game_id})" title="Remove">🗑️</button>
        </div>
    `).join('');
}

function updateTop10Reason(gameId, reason) {
    const game = top10Games.find(g => g.game_id === gameId);
    if (game) {
        game.why_i_love_it = reason;
    }
}


function moveTop10Up(index) {
  if (index > 0) {
    [top10Games[index], top10Games[index - 1]] = [top10Games[index - 1], top10Games[index]];
    renderTop10();
  }
}

function moveTop10Down(index) {
  if (index < top10Games.length - 1) {
    [top10Games[index], top10Games[index + 1]] = [top10Games[index + 1], top10Games[index]];
    renderTop10();
  }
}

function removeFromTop10(gameId) {
  top10Games = top10Games.filter(game => game.game_id !== gameId);
  renderTop10();
}

// Available games for Top 10 editor
async function loadAvailableGames() {
  const searchInput = document.getElementById('top10-search');
  const availableList = document.getElementById('available-games');
  
  const filteredGames = allGames.filter(game => 
    !top10Games.some(top10 => top10.game_id === game.id)
  );
  
  availableList.innerHTML = filteredGames.map(game => `
    <div class="available-game-item" data-game-id="${game.id}">
      <div>
        <strong>${game.title}</strong>
        <div style="font-size: 12px; color: var(--text-muted);">
          ${game.platform} • ${game.hours_played || 0}h • ${game.status}
        </div>
      </div>
    </div>
  `).join('');
  
  // Add click handlers
  availableList.querySelectorAll('.available-game-item').forEach(item => {
    item.addEventListener('click', () => {
      const gameId = parseInt(item.dataset.gameId);
      const game = allGames.find(g => g.id === gameId);
      if (game && top10Games.length < 10) {
        top10Games.push({
          game_id: game.id,
          title: game.title,
          platform: game.platform,
          hours_played: game.hours_played,
          rating: game.rating,
          why_i_love_it: ''
        });
        renderTop10();
        loadAvailableGames(); // Refresh available games
      } else if (top10Games.length >= 10) {
        alert('Top 10 is full! Remove a game first.');
      }
    });
  });
  
  // Search functionality
  searchInput.addEventListener('input', (e) => {
    const searchTerm = e.target.value.toLowerCase();
    const items = availableList.querySelectorAll('.available-game-item');
    
    items.forEach(item => {
      const gameTitle = item.querySelector('strong').textContent.toLowerCase();
      item.style.display = gameTitle.includes(searchTerm) ? 'flex' : 'none';
    });
  });
}

// ========== BATCH OPERATIONS ==========
document.getElementById('batch-update')?.addEventListener('click', batchUpdateStatus);
document.getElementById('batch-delete')?.addEventListener('click', batchDeleteGames);
document.getElementById('batch-cancel')?.addEventListener('click', cancelBatchMode);

function toggleBatchMode() {
  console.log('toggleBatchMode called, current batchMode:', batchMode);
  batchMode = !batchMode;
  selectedGames.clear();
  
  const batchActions = document.querySelector('.batch-actions');
  const toggleBtn = document.getElementById('toggle-batch-mode');
  
  console.log('Batch actions element:', batchActions);
  console.log('Toggle button:', toggleBtn);
  
  if (batchMode) {
    document.body.classList.add('batch-mode');
    if (batchActions) {
      batchActions.style.display = 'flex';
      console.log('Batch actions should be visible now');
    }
    if (toggleBtn) toggleBtn.textContent = 'Exit Batch Mode';
    console.log('Batch mode activated');
  } else {
    document.body.classList.remove('batch-mode');
    if (batchActions) batchActions.style.display = 'none';
    if (toggleBtn) toggleBtn.textContent = 'Batch Operations';
    console.log('Batch mode deactivated');
  }
  
  // Force re-render of games to show/hide checkboxes
  applySortingAndFiltering();
}

function checkBatchActionsSetup() {
  console.log('=== BATCH ACTIONS SETUP CHECK ===');
  
  const batchActions = document.querySelector('.batch-actions');
  console.log('Batch actions container:', batchActions);
  
  const batchUpdate = document.getElementById('batch-update');
  const batchDelete = document.getElementById('batch-delete');
  const batchCancel = document.getElementById('batch-cancel');
  
  console.log('Batch update button:', batchUpdate);
  console.log('Batch delete button:', batchDelete);
  console.log('Batch cancel button:', batchCancel);
  
  // Check if event listeners are attached
  if (batchUpdate) {
    console.log('Batch update has click listener:', batchUpdate.hasAttribute('data-listener'));
  }
  if (batchDelete) {
    console.log('Batch delete has click listener:', batchDelete.hasAttribute('data-listener'));
  }
  if (batchCancel) {
    console.log('Batch cancel has click listener:', batchCancel.hasAttribute('data-listener'));
  }
  
  console.log('Current batch mode:', batchMode);
  console.log('Body has batch-mode class:', document.body.classList.contains('batch-mode'));
  console.log('Batch actions display style:', batchActions ? batchActions.style.display : 'N/A');
}

function cancelBatchMode() {
  batchMode = false;
  selectedGames.clear();
  document.body.classList.remove('batch-mode');
  document.querySelector('.batch-actions').style.display = 'none';
  
  const toggleBtn = document.getElementById('toggle-batch-mode');
  if (toggleBtn) toggleBtn.textContent = 'Batch Operations';
  
  applySortingAndFiltering();
}

async function batchUpdateStatus() {
  const newStatus = document.getElementById('batch-status').value;
  
  if (selectedGames.size === 0) {
    alert('Please select at least one game');
    return;
  }
  
  if (!confirm(`Update ${selectedGames.size} game(s)? This will refresh hours played AND achievements from Steam, and automatically set completion status based on achievements.`)) return;
  
  const btn = document.getElementById('batch-update');
  const originalText = btn.textContent;
  btn.textContent = 'Updating...';
  btn.disabled = true;
  
  try {
    let updatedCount = 0;
    let completedCount = 0;
    let achievementsUpdated = 0;
    
    // Process each selected game
    for (const gameId of selectedGames) {
      try {
        console.log(`Updating game ${gameId} from Steam...`);
        
        const res = await fetch(`/api/steam/update-game/${gameId}`, { method: 'POST' });
        const result = await res.json();
        
        if (result.success) {
          updatedCount++;
          
          if (result.achievements_updated > 0) {
            achievementsUpdated += result.achievements_updated;
          }
          
          if (result.all_achievements_unlocked) {
            completedCount++;
            console.log(`Game ${gameId} completed all achievements on ${result.completion_date}`);
          }
          
          // If a specific status was selected, update it
          if (newStatus) {
            await fetch(`/api/games/${gameId}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus })
            });
          }
        }
      } catch (err) {
        console.error(`Error updating game ${gameId}:`, err);
      }
    }
    
    let message = `Updated ${updatedCount} game(s) from Steam`;
    if (achievementsUpdated > 0) {
      message += ` - ${achievementsUpdated} achievements refreshed`;
    }
    if (completedCount > 0) {
      message += ` - ${completedCount} games completed all achievements`;
    }
    
    alert(message);
    cancelBatchMode();
    fetchGames(); // Refresh the list
    
  } catch (err) {
    alert('Error updating games: ' + err.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function batchDeleteGames() {
  if (selectedGames.size === 0) {
    alert('Please select at least one game');
    return;
  }
  
  if (!confirm(`Permanently delete ${selectedGames.size} game(s)? This cannot be undone!`)) return;
  
  try {
    const res = await fetch('/api/batch/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_ids: Array.from(selectedGames)
      })
    });
    
    if (res.ok) {
      alert(`Deleted ${selectedGames.size} game(s) successfully!`);
      cancelBatchMode();
      fetchGames(); // Refresh the list
    }
  } catch (err) {
    alert('Error deleting games: ' + err.message);
  }
}

function setupBatchButton() {
  // Remove existing batch button if any
  const existingBtn = document.getElementById('toggle-batch-mode');
  if (existingBtn) {
    existingBtn.remove();
  }
  
  if (isLoggedIn) {
    const batchToggle = document.createElement('button');
    batchToggle.id = 'toggle-batch-mode';
    batchToggle.className = 'btn';
    batchToggle.textContent = 'Batch Operations';
    batchToggle.addEventListener('click', toggleBatchMode);
    
    // Add it to the games tab header
    const gamesTab = document.getElementById('tab-games');
    
    if (!gamesTab) {
      console.error('Games tab not found');
      return;
    }
    
    // Create or find the tab actions container
    let actionsContainer = gamesTab.querySelector('.tab-actions');
    if (!actionsContainer) {
      actionsContainer = document.createElement('div');
      actionsContainer.className = 'tab-actions';
      
      // Insert after the h2 or at the top if no h2
      const existingH2 = gamesTab.querySelector('h2');
      if (existingH2) {
        existingH2.insertAdjacentElement('afterend', actionsContainer);
      } else {
        gamesTab.insertBefore(actionsContainer, gamesTab.firstChild);
      }
    }
    
    actionsContainer.appendChild(batchToggle);
    console.log('Batch operations button added to tab');
  }
}

// ========== BATCH OPERATIONS INITIALIZATION ==========
function setupBatchOperations() {
    console.log('Setting up batch operations...');
    
    const batchUpdateBtn = document.getElementById('batch-update');
    const batchDeleteBtn = document.getElementById('batch-delete');
    const batchCancelBtn = document.getElementById('batch-cancel');
    
    console.log('Found batch update button:', !!batchUpdateBtn);
    console.log('Found batch delete button:', !!batchDeleteBtn);
    console.log('Found batch cancel button:', !!batchCancelBtn);
    
    // Remove existing listeners first
    if (batchUpdateBtn) {
        batchUpdateBtn.replaceWith(batchUpdateBtn.cloneNode(true));
    }
    if (batchDeleteBtn) {
        batchDeleteBtn.replaceWith(batchDeleteBtn.cloneNode(true));
    }
    if (batchCancelBtn) {
        batchCancelBtn.replaceWith(batchCancelBtn.cloneNode(true));
    }
    
    // Get fresh references after cloning
    const freshUpdate = document.getElementById('batch-update');
    const freshDelete = document.getElementById('batch-delete');
    const freshCancel = document.getElementById('batch-cancel');
    
    if (freshUpdate) {
        freshUpdate.addEventListener('click', batchUpdateStatus);
        freshUpdate.setAttribute('data-listener', 'attached');
        console.log('Batch update listener added');
    }
    
    if (freshDelete) {
        freshDelete.addEventListener('click', batchDeleteGames);
        freshDelete.setAttribute('data-listener', 'attached');
        console.log('Batch delete listener added');
    }
    
    if (freshCancel) {
        freshCancel.addEventListener('click', cancelBatchMode);
        freshCancel.setAttribute('data-listener', 'attached');
        console.log('Batch cancel listener added');
    }
    
    // Also set up the toggle button
    setupBatchButton();
    
    console.log('Batch operations setup complete');
}

// Call this after loading games
async function fetchGames() {
  const res = await fetch('/api/games');
  allGames = await res.json();
  applySortingAndFiltering();
  setupBatchButton();
}

async function loadTop10() {
    try {
        const res = await fetch('/api/top10');
        top10Games = await res.json();
        renderTop10();
    } catch (err) {
        console.error('Error loading Top 10:', err);
    }
}

function renderTop10() {
    const list = document.getElementById('top10-list');
    
    if (!list) {
        console.error('top10-list element not found');
        return;
    }
    
    if (!top10Games || top10Games.length === 0) {
        list.innerHTML = '<div class="empty-state">No top 10 games set yet. Click "Edit Top 10" to get started!</div>';
        return;
    }
    
    list.innerHTML = top10Games.map((game, index) => `
        <div class="top10-game-card">
            <div class="top10-rank">#${index + 1}</div>
            ${game.cover_url ? `<img src="${game.cover_url}" class="top10-cover" alt="${game.title}" />` : ''}
            <div class="top10-content">
                <h3>${game.title}</h3>
                <div class="top10-meta">
                    <span class="platform">${game.platform}</span>
                    <span class="hours">${game.hours_played || 0}h</span>
                    ${game.rating ? `<span class="rating">${'★'.repeat(game.rating)}${'☆'.repeat(5 - game.rating)}</span>` : ''}
                </div>
                ${game.why_i_love_it ? `<p class="why-i-love-it">"${game.why_i_love_it}"</p>` : ''}
            </div>
        </div>
    `).join('');
}

function openTop10Editor() {
    console.log('openTop10Editor called');
    
    if (!isLoggedIn) {
        alert('Please login to edit Top 10');
        return;
    }
    
    isEditingTop10 = true;
    document.getElementById('edit-top10').style.display = 'none';
    document.getElementById('save-top10').style.display = '';
    document.getElementById('cancel-edit-top10').style.display = '';
    
    document.getElementById('available-games').innerHTML = '<div class="empty-state">Search for games to add to your Top 10</div>';
    document.getElementById('top10-search').value = '';
    
    document.getElementById('top10-modal').classList.add('show');
}

function cancelTop10Edit() {
    isEditingTop10 = false;
    document.getElementById('edit-top10').style.display = '';
    document.getElementById('save-top10').style.display = 'none';
    document.getElementById('cancel-edit-top10').style.display = 'none';
    loadTop10();
}

async function saveTop10() {
    try {
        console.log('Saving Top 10:', top10Games);
        
        const gamesToSave = top10Games.map((game, index) => ({
            game_id: game.game_id,
            position: index + 1,
            why_i_love_it: game.why_i_love_it || ''
        }));
        
        console.log('Transformed data:', gamesToSave);
        
        const response = await fetch('/api/top10', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(gamesToSave)
        });

        console.log('Response status:', response.status);
        
        if (response.ok) {
            const result = await response.json();
            console.log('Save successful:', result);
            alert('Top 10 saved successfully!');
            closeTop10Modal();
            cancelTop10Edit();
            loadTop10();
        } else {
            const errorText = await response.text();
            console.error('Server error:', errorText);
            alert('Error saving Top 10: ' + errorText);
        }
    } catch (err) {
        console.error('Network error:', err);
        alert('Network error saving Top 10: ' + err.message);
    }
}

function removeFromTop10(gameId) {
    top10Games = top10Games.filter(game => game.game_id !== gameId);
    renderTop10Selection();
}

function setupTop10EventListeners() {
    // Wait for elements to exist
    setTimeout(() => {
        const editBtn = document.getElementById('edit-top10');
        const cancelEditBtn = document.getElementById('cancel-edit-top10');
        const saveBtn = document.getElementById('save-top10');
        const saveModalBtn = document.getElementById('save-top10-modal');
        
        console.log('Setting up Top 10 event listeners...');
        
        if (editBtn) {
            editBtn.addEventListener('click', openTop10Editor);
            console.log('Edit button listener added');
        }
        
        if (cancelEditBtn) cancelEditBtn.addEventListener('click', cancelTop10Edit);
        if (saveBtn) saveBtn.addEventListener('click', saveTop10);
        if (saveModalBtn) saveModalBtn.addEventListener('click', saveTop10);
    }, 500);
}

function cancelTop10Edit() {
    isEditingTop10 = false;
    document.getElementById('edit-top10').style.display = '';
    document.getElementById('save-top10').style.display = 'none';
    document.getElementById('cancel-edit-top10').style.display = 'none';
    loadTop10(); // Reload the display view
}