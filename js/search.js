// Search Page JavaScript

let currentPage = 1;
let currentSearchQuery = '';
let currentFilters = {};
let isLoading = false;
let hasMorePages = true;
let allGenres = [];
let allCountries = [];

// DOM Elements
const mainSearchInput = document.getElementById('mainSearchInput');
const headerSearchInput = document.getElementById('headerSearchInput');
const moviesGrid = document.getElementById('moviesGrid');
const loadingElement = document.getElementById('loading');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const resultsHeader = document.getElementById('resultsHeader');
const resultsTitle = document.getElementById('resultsTitle');
const resultsCount = document.getElementById('resultsCount');
const noSearch = document.getElementById('noSearch');
const noResults = document.getElementById('noResults');
const filtersContent = document.getElementById('filtersContent');

// Initialize page
document.addEventListener('DOMContentLoaded', async function() {
    try {
        await loadFiltersData();
        setupEventListeners();
        
        // Check if there's a search query in URL
        const urlParams = new URLSearchParams(window.location.search);
        const query = urlParams.get('q');
        if (query) {
            mainSearchInput.value = query;
            headerSearchInput.value = query;
            await performSearch();
        }
        
    } catch (error) {
        console.error('Error initializing search page:', error);
    }
});

// Load data for filters
async function loadFiltersData() {
    try {
        const [genresResponse, countriesResponse] = await Promise.all([
            movieAPI.getGenres(),
            movieAPI.getCountries()
        ]);
        
        allGenres = genresResponse.data || [];
        allCountries = countriesResponse.data || [];
        
        populateGenresFilter();
        populateCountriesFilter();
        
    } catch (error) {
        console.error('Error loading filters data:', error);
    }
}

// Populate genres filter
function populateGenresFilter() {
    const genresContainer = document.getElementById('genresContainer');
    
    genresContainer.innerHTML = allGenres.map(genre => `
        <label class="genre-option">
            <input type="checkbox" name="genre" value="${genre.id}">
            <span>${genre.name || genre.name_eng}</span>
        </label>
    `).join('');
}

// Populate countries filter
function populateCountriesFilter() {
    const countriesContainer = document.getElementById('countriesContainer');
    
    countriesContainer.innerHTML = allCountries.map(country => `
        <label class="country-option">
            <input type="checkbox" name="country" value="${country.id}">
            <span>${country.name || country.name_eng}</span>
        </label>
    `).join('');
}

// Setup event listeners
function setupEventListeners() {
    // Search inputs
    mainSearchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            performSearch();
        }
    });
    
    headerSearchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchFromHeader();
        }
    });
    
    // Load more button
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', loadMoreResults);
    }
}

// Perform search
async function performSearch() {
    const query = mainSearchInput.value.trim();
    
    // Update header search input
    headerSearchInput.value = query;
    
    // Reset pagination
    currentPage = 1;
    currentSearchQuery = query;
    hasMorePages = true;
    
    // Clear current results
    moviesGrid.innerHTML = '';
    
    // Hide/show appropriate sections
    noSearch.style.display = 'none';
    noResults.style.display = 'none';
    resultsHeader.style.display = 'none';
    
    if (!query && Object.keys(currentFilters).length === 0) {
        noSearch.style.display = 'block';
        loadMoreBtn.style.display = 'none';
        return;
    }
    
    // Update URL
    const newUrl = new URL(window.location);
    if (query) {
        newUrl.searchParams.set('q', query);
    } else {
        newUrl.searchParams.delete('q');
    }
    window.history.pushState({}, '', newUrl);
    
    await searchMovies();
}

// Search movies with current query and filters
async function searchMovies(append = false) {
    if (isLoading) return;
    
    isLoading = true;
    showLoading(true);
    
    try {
        // Prepare search parameters
        const searchParams = {
            page: currentPage,
            limit: 20,
            ...currentFilters
        };
        
        let response;
        
        if (currentSearchQuery) {
            // Search by name
            response = await movieAPI.searchMovies(currentSearchQuery, searchParams);
        } else {
            // Just apply filters
            response = await movieAPI.getMoviesList(searchParams);
        }
        
        if (response && response.data) {
            if (response.data.length === 0 && currentPage === 1) {
                // No results found
                showNoResults();
            } else {
                displaySearchResults(response.data, append);
                updateResultsInfo(response);
                
                // Update pagination
                if (response.meta) {
                    hasMorePages = response.meta.current_page < response.meta.last_page;
                } else {
                    hasMorePages = false;
                }
                
                updateLoadMoreButton();
            }
        } else {
            showNoResults();
        }
        
    } catch (error) {
        console.error('Error searching movies:', error);
        showError('Ошибка при поиске фильмов');
    } finally {
        isLoading = false;
        showLoading(false);
    }
}

// Display search results
function displaySearchResults(movies, append = false) {
    if (!append) {
        moviesGrid.innerHTML = '';
    }
    
    movies.forEach(movie => {
        const movieCard = createMovieCard(movie);
        moviesGrid.appendChild(movieCard);
    });
    
    // Show results section
    resultsHeader.style.display = 'block';
    noResults.style.display = 'none';
}

// Create movie card (same as in main.js)
function createMovieCard(movie) {
    const card = document.createElement('div');
    card.className = 'movie-card';
    card.onclick = () => openMovieDetails(movie);
    
    const posterUrl = movie.poster_url || 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjQ1MCIgdmlld0JveD0iMCAwIDMwMCA0NTAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIzMDAiIGhlaWdodD0iNDUwIiBmaWxsPSIjMWExYTJlIi8+Cjx0ZXh0IHg9IjE1MCIgeT0iMjI1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjNjRiNWY2IiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTgiPk5ldCDQv9C+0YHRgtC10YDQsDwvdGV4dD4KPC9zdmc+';
    const rating = parseFloat(movie.kp_rating) || parseFloat(movie.imdb_rating) || parseFloat(movie.rating) || parseFloat(movie.vote_average) || 0;
    const year = movie.year || 'Неизвестно';
    const title = movie.name_rus || movie.name_eng || movie.name || 'Без названия';
    
    card.innerHTML = `
        <div class="movie-poster">
            <img src="${posterUrl}" alt="${title}" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjQ1MCIgdmlld0JveD0iMCAwIDMwMCA0NTAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIzMDAiIGhlaWdodD0iNDUwIiBmaWxsPSIjMWExYTJlIi8+Cjx0ZXh0IHg9IjE1MCIgeT0iMjI1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjNjRiNWY2IiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTgiPk5ldCDQv9C+0YHRgtC10YDQsDwvdGV4dD4KPC9zdmc+'"
            ${rating > 0 ? `
                <div class="movie-rating">
                    <i class="fas fa-star"></i>
                    ${rating.toFixed(1)}
                </div>
            ` : ''}
        </div>
        <div class="movie-info">
            <h3 class="movie-title">${title}</h3>
            <p class="movie-year">${year} • ${movie.type === 'movie' ? 'Фильм' : 'Сериал'}</p>
            ${movie.description_short ? `
                <p class="movie-overview">${movie.description_short}</p>
            ` : ''}
        </div>
    `;
    
    return card;
}

// Open movie details
function openMovieDetails(movie) {
    localStorage.setItem('selectedMovie', JSON.stringify(movie));
    window.location.href = `movie-details.html?id=${movie.id}`;
}

// Update results info
function updateResultsInfo(response) {
    if (currentSearchQuery) {
        resultsTitle.textContent = `Результаты поиска: "${currentSearchQuery}"`;
    } else {
        resultsTitle.textContent = 'Результаты фильтрации';
    }
    
    if (response.meta) {
        resultsCount.textContent = `Найдено: ${response.meta.total} ${getMovieWord(response.meta.total)}`;
    } else {
        resultsCount.textContent = `Найдено: ${response.data.length} ${getMovieWord(response.data.length)}`;
    }
}

// Get correct word form for movie count
function getMovieWord(count) {
    const lastDigit = count % 10;
    const lastTwoDigits = count % 100;
    
    if (lastTwoDigits >= 11 && lastTwoDigits <= 14) {
        return 'фильмов';
    }
    
    switch (lastDigit) {
        case 1:
            return 'фильм';
        case 2:
        case 3:
        case 4:
            return 'фильма';
        default:
            return 'фильмов';
    }
}

// Show no results
function showNoResults() {
    noResults.style.display = 'block';
    resultsHeader.style.display = 'none';
    loadMoreBtn.style.display = 'none';
}

// Load more results
async function loadMoreResults() {
    if (!hasMorePages || isLoading) return;
    
    currentPage++;
    await searchMovies(true);
}

// Apply filters
function applyFilters() {
    currentFilters = {};
    
    // Get type filter
    const typeInput = document.querySelector('input[name="type"]:checked');
    if (typeInput && typeInput.value) {
        currentFilters.type = typeInput.value;
    }
    
    // Get year filters
    const yearFrom = document.getElementById('yearFrom').value;
    const yearTo = document.getElementById('yearTo').value;
    
    if (yearFrom || yearTo) {
        currentFilters.year = [];
        const startYear = yearFrom ? parseInt(yearFrom) : 1900;
        const endYear = yearTo ? parseInt(yearTo) : new Date().getFullYear();
        
        for (let year = startYear; year <= endYear; year++) {
            currentFilters.year.push(year);
        }
    }
    
    // Get genre filters
    const selectedGenres = Array.from(document.querySelectorAll('input[name="genre"]:checked'))
        .map(input => parseInt(input.value));
    if (selectedGenres.length > 0) {
        currentFilters.genre = selectedGenres;
    }
    
    // Get country filters
    const selectedCountries = Array.from(document.querySelectorAll('input[name="country"]:checked'))
        .map(input => parseInt(input.value));
    if (selectedCountries.length > 0) {
        currentFilters.country = selectedCountries;
    }
    
    // Perform search with filters
    currentPage = 1;
    performSearch();
}

// Reset filters
function resetFilters() {
    // Reset form inputs
    document.querySelectorAll('input[name="type"]')[0].checked = true;
    document.getElementById('yearFrom').value = '';
    document.getElementById('yearTo').value = '';
    document.querySelectorAll('input[name="genre"]:checked').forEach(input => {
        input.checked = false;
    });
    document.querySelectorAll('input[name="country"]:checked').forEach(input => {
        input.checked = false;
    });
    
    // Clear filters and search
    currentFilters = {};
    currentPage = 1;
    performSearch();
}

// Toggle filters visibility
function toggleFilters() {
    const isHidden = filtersContent.classList.contains('hidden');
    const toggleBtn = document.querySelector('.toggle-filters span');
    
    if (isHidden) {
        filtersContent.classList.remove('hidden');
        toggleBtn.textContent = 'Скрыть фильтры';
    } else {
        filtersContent.classList.add('hidden');
        toggleBtn.textContent = 'Показать фильтры';
    }
}

// Search from header
function searchFromHeader() {
    const query = headerSearchInput.value.trim();
    mainSearchInput.value = query;
    performSearch();
}

// Show/hide loading
function showLoading(show) {
    if (loadingElement) {
        loadingElement.classList.toggle('show', show);
        
        if (show) {
            // Показываем прогресс-бар
            const searchProgress = document.getElementById('searchProgress');
            if (searchProgress) {
                searchProgress.style.display = 'block';
            }
            
            // Запускаем мониторинг прогресса
            startProgressMonitoring();
        } else {
            // Скрываем прогресс-бар
            const searchProgress = document.getElementById('searchProgress');
            if (searchProgress) {
                searchProgress.style.display = 'none';
            }
            
            stopProgressMonitoring();
        }
    }
}

// Мониторинг прогресса поиска
let progressInterval = null;

function startProgressMonitoring() {
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const loadingText = document.getElementById('loadingText');
    
    let progress = 0;
    let phase = 1;
    
    if (progressInterval) {
        clearInterval(progressInterval);
    }
    
    progressInterval = setInterval(() => {
        progress += 2;
        
        if (progress > 100) {
            progress = 100;
        }
        
        if (progressFill) {
            progressFill.style.width = progress + '%';
        }
        
        // Обновляем текст в зависимости от фазы
        if (progress < 30) {
            phase = 1;
            if (progressText) progressText.textContent = '🚀 Фаза 1: Быстрый поиск в популярных фильмах...';
            if (loadingText) loadingText.textContent = 'Сканирование первых 500 страниц...';
        } else if (progress < 60) {
            if (phase === 1) {
                phase = 2;
                if (progressText) progressText.textContent = '🔍 Фаза 2: Расширенный поиск по базе данных...';
                if (loadingText) loadingText.textContent = 'Сканирование страниц 500-5000...';
            }
        } else if (progress < 90) {
            if (phase === 2) {
                phase = 3;
                if (progressText) progressText.textContent = '🌐 Фаза 3: Глубокий поиск по всей базе (20000 страниц)...';
                if (loadingText) loadingText.textContent = 'Полное сканирование базы данных...';
            }
        } else {
            if (progressText) progressText.textContent = '✅ Завершение поиска и сортировка результатов...';
            if (loadingText) loadingText.textContent = 'Обработка результатов...';
        }
        
        if (progress >= 100) {
            clearInterval(progressInterval);
        }
    }, 300);
}

function stopProgressMonitoring() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    // Сбрасываем прогресс
    const progressFill = document.getElementById('progressFill');
    if (progressFill) {
        progressFill.style.width = '0%';
    }
}

// Update load more button
function updateLoadMoreButton() {
    if (loadMoreBtn) {
        loadMoreBtn.style.display = hasMorePages ? 'block' : 'none';
        loadMoreBtn.disabled = isLoading;
    }
}

// Show error message
function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-notification';
    errorDiv.innerHTML = `
        <div class="error-content">
            <i class="fas fa-exclamation-triangle"></i>
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    errorDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: rgba(220, 53, 69, 0.95);
        color: white;
        padding: 1rem;
        border-radius: 8px;
        z-index: 10000;
        max-width: 400px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    `;
    
    document.body.appendChild(errorDiv);
    
    setTimeout(() => {
        if (errorDiv.parentElement) {
            errorDiv.remove();
        }
    }, 5000);
}

// Global functions
window.performSearch = performSearch;
window.searchFromHeader = searchFromHeader;
window.loadMoreResults = loadMoreResults;
window.applyFilters = applyFilters;
window.resetFilters = resetFilters;
window.toggleFilters = toggleFilters;
