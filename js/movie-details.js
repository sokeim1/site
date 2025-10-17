// Movie Details Page JavaScript

let currentMovie = null;
let serialData = null;

// Индекс текущего прокси (для ротации)
let currentProxyIndex = 0;

// Функция для получения URL изображения через прокси
function getImageUrl(originalUrl) {
    if (!originalUrl || !originalUrl.startsWith('http')) {
        return originalUrl;
    }
    
    // Список публичных CORS-прокси (будем пробовать разные)
    const corsProxies = [
        // Imgproxy - специализированный прокси для изображений
        url => `https://images.weserv.nl/?url=${encodeURIComponent(url)}`,
        // API прокси
        url => `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}`,
        // AllOrigins
        url => `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`,
        // Corsproxy
        url => `https://corsproxy.io/?${encodeURIComponent(url)}`,
        // Thingproxy
        url => `https://thingproxy.freeboard.io/fetch/${url}`
    ];
    
    // Используем текущий прокси из ротации
    const proxyUrl = corsProxies[currentProxyIndex % corsProxies.length](originalUrl);
    return proxyUrl;
}

// DOM Elements
const loadingElement = document.getElementById('loading');
const movieDetailsElement = document.getElementById('movieDetails');
const errorMessageElement = document.getElementById('errorMessage');
const videoPlayerSection = document.getElementById('videoPlayerSection');
const embeddedVideoFrame = document.getElementById('embeddedVideoFrame');
// const loadPlayerBtn = document.getElementById('loadPlayerBtn'); // Removed - auto-loading now
const fullscreenBtn = document.getElementById('fullscreenBtn');
const playerPlaceholder = document.getElementById('playerPlaceholder');
const scrollToPlayerBtn = document.getElementById('scrollToPlayerBtn');

// Initialize page
document.addEventListener('DOMContentLoaded', async function() {
    try {
        // Очищаем старый кэш с неправильными iframe_url (одноразово)
        const cacheVersion = 'v4'; // v4: iframe_url теперь используется как основной источник
        const currentVersion = localStorage.getItem('cache_version');
        if (currentVersion !== cacheVersion) {
            console.log('🧹 Clearing old cache (v4: iframe_url priority)...');
            sessionStorage.clear();
            localStorage.setItem('cache_version', cacheVersion);
        }
        
        await loadMovieDetails();
        setupEventListeners();
    } catch (error) {
        console.error('Error initializing movie details page:', error);
        showError();
    }
});

// Load movie details (ОПТИМИЗИРОВАННАЯ ВЕРСИЯ)
async function loadMovieDetails() {
    const startTime = performance.now();
    showLoading(true);
    
    try {
        // Get movie ID from URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const movieId = urlParams.get('id');
        
        // Try to get movie from localStorage first (from main page)
        const storedMovie = localStorage.getItem('selectedMovie');
        
        if (storedMovie) {
            currentMovie = JSON.parse(storedMovie);
            console.log('⚡ Starting optimized movie load...');
            
            // ШАГ 1: Сразу показываем базовую информацию (мгновенно)
            await displayMovieDetails(currentMovie);
            showLoading(false);
            console.log(`✅ Basic info displayed in ${Math.round(performance.now() - startTime)}ms`);
            
            // ШАГ 2: ПАРАЛЛЕЛЬНО загружаем детальные данные в фоне
            loadDetailedDataInBackground(currentMovie);
            
        } else if (movieId) {
            throw new Error('Movie not found in storage and no API endpoint for direct ID lookup');
        } else {
            throw new Error('No movie ID provided');
        }
        
    } catch (error) {
        console.error('Error loading movie details:', error);
        showError();
        return;
    }
}

// Загрузка детальных данных в фоне (ОПТИМИЗИРОВАННАЯ ВЕРСИЯ)
async function loadDetailedDataInBackground(movie) {
    const startTime = performance.now();
    
    try {
        // БЫСТРАЯ ПРОВЕРКА: Если iframe_url уже есть - сразу загружаем плеер!
        // iframe_url из API - самый надежный источник для всех типов контента
        if (movie.iframe_url || movie.player_url) {
            console.log('⚡ Player URL already available, loading immediately!');
            setupPlayerButtons(movie);
            setTimeout(() => autoLoadPlayer(), 100); // Минимальная задержка
            console.log(`🎉 Fast load completed in ${Math.round(performance.now() - startTime)}ms`);
            return;
        }
        
        // Если нет iframe_url, загружаем детальные данные
        console.log('🔄 No iframe_url in initial data, loading from API...');
        
        // Проверяем кэш детальных данных
        const cacheKey = `movie_details_${movie.kp_id || movie.id || movie.imdb_id}`;
        const cachedData = sessionStorage.getItem(cacheKey);
        
        if (cachedData) {
            const cached = JSON.parse(cachedData);
            if (Date.now() - cached.timestamp < 30 * 60 * 1000) { // 30 минут
                console.log('⚡ Using cached detailed data');
                currentMovie = { ...currentMovie, ...cached.data };
                updateMovieDetailsWithAPI(currentMovie);
                setupPlayerButtons(currentMovie);
                autoLoadPlayer();
                return;
            }
        }
        
        console.log('🔄 Loading detailed data in background...');
        
        // ПРОБЛЕМА: API /publisher/videos/links НЕ возвращает kp_id!
        // Нужно использовать iframe_url напрямую или показать ошибку
        
        console.log('📊 Movie data from localStorage:', movie);
        console.log('📊 Has kp_id?', !!movie.kp_id);
        console.log('📊 Has imdb_id?', !!movie.imdb_id);
        console.log('📊 Has iframe_url?', !!movie.iframe_url);
        
        // Если нет ни kp_id, ни imdb_id, ни iframe_url - показываем ошибку
        if (!movie.kp_id && !movie.imdb_id && !movie.iframe_url) {
            console.error('❌ No valid ID or iframe_url in movie data!');
            console.error('❌ API /publisher/videos/links does not return kp_id');
            console.error('❌ This movie cannot be played without kp_id or iframe_url');
            
            // Показываем сообщение пользователю
            if (playerPlaceholder) {
                playerPlaceholder.innerHTML = `
                    <div class="placeholder-content">
                        <i class="fas fa-exclamation-triangle"></i>
                        <h4>Плеер недоступен</h4>
                        <p>К сожалению, для этого фильма нет доступного плеера</p>
                        <p style="font-size: 12px; color: #888; margin-top: 10px;">
                            API не предоставил необходимые данные (kp_id или iframe_url)
                        </p>
                    </div>
                `;
            }
            
            return; // Прерываем загрузку
        }
        
        // ПАРАЛЛЕЛЬНЫЕ ЗАПРОСЫ вместо последовательных
        const promises = [];
        
        // Запрос 1: По kp_id (если есть)
        if (movie.kp_id) {
            promises.push(
                movieAPI.getMovieByKpId(movie.kp_id)
                    .then(data => ({ source: 'kp_id', data }))
                    .catch(() => null)
            );
        }
        
        // Запрос 2: По imdb_id (параллельно!)
        if (movie.imdb_id) {
            promises.push(
                movieAPI.getMovieByImdbId(movie.imdb_id)
                    .then(data => ({ source: 'imdb_id', data }))
                    .catch(() => null)
            );
        }
        
        // Если нет запросов, но есть iframe_url - используем его
        if (promises.length === 0 && movie.iframe_url) {
            console.log('⚡ Using iframe_url directly (no kp_id/imdb_id available)');
            setupPlayerButtons(movie);
            setTimeout(() => autoLoadPlayer(), 100);
            return;
        }
        
        // Ждем ВСЕ запросы параллельно
        const results = await Promise.all(promises);
        const loadTime = Math.round(performance.now() - startTime);
        console.log(`✅ All API requests completed in ${loadTime}ms`);
        
        // Обрабатываем результаты
        let detailedMovie = null;
        let serialDataResult = null;
        
        for (const result of results) {
            if (!result) continue;
            
            if (result.source === 'serial') {
                serialDataResult = result.data;
            } else if (!detailedMovie && result.data) {
                detailedMovie = result.data;
                console.log(`✅ Got detailed data from ${result.source}`);
            }
        }
        
        // УДАЛЕНО: Медленный fallback на поиск по названию (26 секунд!)
        // Если нет детальных данных - используем то что есть
        
        // Объединяем данные
        if (detailedMovie) {
            const apiData = detailedMovie.data || detailedMovie;
            if (apiData && typeof apiData === 'object') {
                currentMovie = { ...currentMovie, ...apiData };
                
                // Кэшируем детальные данные (включая iframe_url - он нужен!)
                sessionStorage.setItem(cacheKey, JSON.stringify({
                    timestamp: Date.now(),
                    data: apiData
                }));
                
                // Обновляем UI с новыми данными
                updateMovieDetailsWithAPI(currentMovie);
                
                // ТЕПЕРЬ загружаем данные сериала с настоящим kp_id
                if (movie.type === 'serial' && currentMovie.kp_id) {
                    console.log('🔄 Loading serial data with real kp_id:', currentMovie.kp_id);
                    try {
                        serialDataResult = await movieAPI.getSerialByKpId(currentMovie.kp_id);
                    } catch (error) {
                        console.warn('⚠️ Failed to load serial data:', error);
                    }
                }
            }
        }
        
        // Обрабатываем данные сериала
        if (serialDataResult) {
            serialData = serialDataResult;
            displaySerialInfo(serialData);
        }
        
        // Настраиваем плеер и автозагружаем НЕМЕДЛЕННО
        setupPlayerButtons(currentMovie);
        
        // Автозагрузка плеера БЕЗ задержки
        setTimeout(() => {
            autoLoadPlayer();
        }, 100);
        
        console.log(`🎉 Full page load completed in ${Math.round(performance.now() - startTime)}ms`);
        
    } catch (error) {
        console.error('Error loading detailed data:', error);
        // Не показываем ошибку, т.к. базовая информация уже отображена
        // Просто настраиваем плеер с имеющимися данными
        setupPlayerButtons(currentMovie);
        setTimeout(() => autoLoadPlayer(), 500);
    }
}

// Обновление деталей фильма с данными API (НОВАЯ ФУНКЦИЯ)
function updateMovieDetailsWithAPI(movie) {
    console.log('🔄 Updating UI with API data...');
    
    // Обновляем только те поля, которые могли измениться
    if (movie.iframe_url) {
        console.log('✅ Got iframe_url from API:', movie.iframe_url);
    }
    
    // Обновляем рейтинги если они изменились
    if (movie.kp_rating) {
        const kpRating = document.getElementById('kpRating');
        const kpRatingValue = parseFloat(movie.kp_rating);
        kpRating.querySelector('.rating-value').textContent = kpRatingValue ? kpRatingValue.toFixed(1) : movie.kp_rating;
        kpRating.style.display = 'flex';
    }
    
    if (movie.imdb_rating) {
        const imdbRating = document.getElementById('imdbRating');
        const imdbRatingValue = parseFloat(movie.imdb_rating);
        imdbRating.querySelector('.rating-value').textContent = imdbRatingValue ? imdbRatingValue.toFixed(1) : movie.imdb_rating;
        imdbRating.style.display = 'flex';
    }
    
    // Обновляем озвучки если появились
    if (movie.voiceovers && movie.voiceovers.length > 0) {
        const voiceoversTab = document.getElementById('voiceoversTab');
        const voiceoversList = document.getElementById('voiceoversList');
        
        voiceoversTab.style.display = 'block';
        voiceoversList.innerHTML = movie.voiceovers.map(voiceover => 
            `<div class="voiceover-item">${voiceover.name}</div>`
        ).join('');
    }
}

// Display movie details
async function displayMovieDetails(movie) {
    // Update page title
    const title = movie.name_rus || movie.name_eng || movie.name || 'Фильм';
    document.title = `CineHub - ${title}`;
    
    // Backdrop image
    const backdropImage = document.getElementById('backdropImage');
    if (movie.backdrop_url) {
        backdropImage.src = getImageUrl(movie.backdrop_url);
        backdropImage.alt = title;
    } else if (movie.poster_url) {
        backdropImage.src = getImageUrl(movie.poster_url);
        backdropImage.alt = title;
    }
    
    // Poster image
    const posterImage = document.getElementById('posterImage');
    const posterUrl = movie.poster_url || 'https://via.placeholder.com/300x450/1a1a2e/64b5f6?text=Нет+постера';
    posterImage.src = movie.poster_url ? getImageUrl(posterUrl) : posterUrl;
    posterImage.alt = title;
    
    // Добавляем обработчик ошибок для постера
    if (movie.poster_url) {
        posterImage.setAttribute('data-original', movie.poster_url);
        posterImage.onerror = function() {
            handlePosterError(this);
        };
    }
    
    // Movie title
    document.getElementById('movieTitle').textContent = title;
    
    // Original title
    const originalTitle = movie.name_original || movie.name_eng;
    if (originalTitle && originalTitle !== title) {
        document.getElementById('movieOriginalTitle').textContent = originalTitle;
        document.getElementById('movieOriginalTitle').style.display = 'block';
    }
    
    // Meta information
    if (movie.year) {
        document.getElementById('movieYear').textContent = movie.year;
    }
    
    if (movie.duration) {
        document.getElementById('movieDuration').textContent = formatDuration(movie.duration);
    }
    
    document.getElementById('movieType').textContent = movie.type === 'movie' ? 'Фильм' : 'Сериал';
    
    if (movie.quality) {
        document.getElementById('movieQuality').textContent = movie.quality;
    }
    
    // Ratings
    if (movie.kp_rating) {
        const kpRating = document.getElementById('kpRating');
        const kpRatingValue = parseFloat(movie.kp_rating);
        kpRating.querySelector('.rating-value').textContent = kpRatingValue ? kpRatingValue.toFixed(1) : movie.kp_rating;
        kpRating.style.display = 'flex';
    }
    
    if (movie.imdb_rating) {
        const imdbRating = document.getElementById('imdbRating');
        const imdbRatingValue = parseFloat(movie.imdb_rating);
        imdbRating.querySelector('.rating-value').textContent = imdbRatingValue ? imdbRatingValue.toFixed(1) : movie.imdb_rating;
        imdbRating.style.display = 'flex';
    }
    
    // Genres
    if (movie.genre && movie.genre.length > 0) {
        const genresContainer = document.getElementById('movieGenres');
        genresContainer.innerHTML = movie.genre.map(genre => 
            `<span class="genre-tag">${genre}</span>`
        ).join('');
    }
    
    // Countries
    if (movie.country && movie.country.length > 0) {
        const countriesContainer = document.getElementById('movieCountries');
        countriesContainer.innerHTML = movie.country.map(country => 
            `<span class="country-tag">${country}</span>`
        ).join('');
    }
    
    // Description
    const description = movie.description || movie.description_short || 'Описание недоступно';
    document.getElementById('movieDescription').textContent = description;
    
    // SEO: Обновляем title и meta description для Google
    const movieTitle = movie.name_rus || movie.name || 'Фильм';
    const year = movie.year ? ` (${movie.year})` : '';
    document.title = `${movieTitle}${year} - смотреть онлайн на KINO HD PREMIUM`;
    
    // Обновляем meta description
    let metaDescription = document.querySelector('meta[name="description"]');
    if (!metaDescription) {
        metaDescription = document.createElement('meta');
        metaDescription.name = 'description';
        document.head.appendChild(metaDescription);
    }
    metaDescription.content = `${movieTitle}${year} - ${description.substring(0, 150)}... Смотреть онлайн в HD качестве на KINO HD PREMIUM`;
    
    // Добавляем Open Graph для соцсетей
    updateOpenGraph(movieTitle, description, movie.poster_url);
    
    // Добавляем Schema.org разметку для Google
    updateSchemaOrg(movie);
    
    // Details tab (optional - may not exist if removed from HTML)
    const detailYear = document.getElementById('detailYear');
    if (detailYear) detailYear.textContent = movie.year || 'Неизвестно';
    
    const detailCountries = document.getElementById('detailCountries');
    if (detailCountries) detailCountries.textContent = movie.country ? movie.country.join(', ') : 'Неизвестно';
    
    const detailGenres = document.getElementById('detailGenres');
    if (detailGenres) detailGenres.textContent = movie.genre ? movie.genre.join(', ') : 'Неизвестно';
    
    const detailDuration = document.getElementById('detailDuration');
    if (detailDuration) detailDuration.textContent = movie.duration ? formatDuration(movie.duration) : 'Неизвестно';
    
    const detailQuality = document.getElementById('detailQuality');
    if (detailQuality) detailQuality.textContent = movie.quality || 'Неизвестно';
    
    const detailUploadDate = document.getElementById('detailUploadDate');
    if (detailUploadDate) {
        if (movie.uploaded_at) {
            const uploadDate = new Date(movie.uploaded_at).toLocaleDateString('ru-RU');
            detailUploadDate.textContent = uploadDate;
        } else {
            detailUploadDate.textContent = 'Неизвестно';
        }
    }
    
    const fullDescription = document.getElementById('fullDescription');
    if (fullDescription) fullDescription.textContent = description;
    
    // Voiceovers (optional - may not exist if removed from HTML)
    if (movie.voiceovers && movie.voiceovers.length > 0) {
        const voiceoversTab = document.getElementById('voiceoversTab');
        const voiceoversList = document.getElementById('voiceoversList');
        
        if (voiceoversTab && voiceoversList) {
            voiceoversTab.style.display = 'block';
            voiceoversList.innerHTML = movie.voiceovers.map(voiceover => 
                `<div class="voiceover-item">${voiceover.name}</div>`
            ).join('');
        }
    }
    
    // Плеер будет настроен после загрузки детальных данных в фоне
    
    // Show movie details
    movieDetailsElement.style.display = 'block';
}

// Display serial information
function displaySerialInfo(serialData) {
    if (!serialData || !serialData.seasons) return;
    
    const seasonsTab = document.getElementById('seasonsTab');
    const seasonsList = document.getElementById('seasonsList');
    
    // Check if elements exist (may be removed from HTML)
    if (!seasonsTab || !seasonsList) return;
    
    seasonsTab.style.display = 'block';
    
    seasonsList.innerHTML = serialData.seasons.map((season, index) => `
        <div class="season-item">
            <div class="season-header" onclick="toggleSeason(${index})">
                <h3 class="season-title">${season.name}</h3>
                <i class="fas fa-chevron-down"></i>
            </div>
            <div class="season-episodes" id="season-${index}">
                <div class="episodes-grid">
                    ${season.series.map(episode => `
                        <div class="episode-item" onclick="playEpisode(${episode.id})">
                            ${episode.name || `Серия ${episode.id}`}
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');
}

// Setup event listeners
function setupEventListeners() {
    // Tab switching
    const tabButtons = document.querySelectorAll('.info-tab');
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.dataset.tab;
            switchTab(tabName);
        });
    });
    
    // Search from header
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchFromHeader();
            }
        });
    }
    
    // Player control buttons
    // loadPlayerBtn removed - auto-loading now
    
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener('click', toggleFullscreen);
    }
    
    if (scrollToPlayerBtn) {
        scrollToPlayerBtn.addEventListener('click', scrollToPlayer);
    }
}

// Switch tabs
function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.info-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    
    // Update tab content
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    
    if (tabName === 'details') {
        document.getElementById('detailsTab').classList.add('active');
    } else if (tabName === 'voiceovers') {
        document.getElementById('voiceoversTabContent').classList.add('active');
    } else if (tabName === 'seasons') {
        document.getElementById('seasonsTabContent').classList.add('active');
    }
}

// Toggle season episodes
function toggleSeason(seasonIndex) {
    const seasonEpisodes = document.getElementById(`season-${seasonIndex}`);
    const isVisible = seasonEpisodes.classList.contains('show');
    
    // Close all seasons
    document.querySelectorAll('.season-episodes').forEach(episodes => {
        episodes.classList.remove('show');
    });
    
    // Toggle current season
    if (!isVisible) {
        seasonEpisodes.classList.add('show');
    }
}

// Play episode
function playEpisode(episodeId) {
    if (currentMovie && currentMovie.playerUrl) {
        // In a real implementation, you would modify the iframe URL to include episode information
        loadPlayer();
        scrollToPlayer();
    }
}

// Setup player buttons
function setupPlayerButtons(movie) {
    console.log('Setting up player buttons for movie:', movie);
    console.log('Movie data:', movie);
    console.log('Movie type:', movie.type);
    
    let playerUrl = null;
    
    // ПРИОРИТЕТ 1: iframe_url из API (самый надежный для сериалов!)
    if (movie.iframe_url && typeof movie.iframe_url === 'string' && movie.iframe_url.trim()) {
        playerUrl = movie.iframe_url;
        console.log(`✅ Using iframe_url from API for ${movie.type}:`, playerUrl);
    }
    // ПРИОРИТЕТ 2: player_url из API
    else if (movie.player_url && typeof movie.player_url === 'string' && movie.player_url.trim()) {
        playerUrl = movie.player_url;
        console.log(`✅ Using player_url from API for ${movie.type}:`, playerUrl);
    }
    // ПРИОРИТЕТ 3: создаем URL на основе kp_id (fallback)
    else if (movie.kp_id || movie.kinopoisk_id || movie.kpid) {
        const kpId = movie.kp_id || movie.kinopoisk_id || movie.kpid;
        playerUrl = `https://vibix.org/embed/kp/${kpId}`;
        console.log(`✅ Created Vibix URL from kp_id for ${movie.type}:`, playerUrl);
    }
    // ПРИОРИТЕТ 4: imdb_id
    else if (movie.imdb_id || movie.imdbid) {
        const imdbId = movie.imdb_id || movie.imdbid;
        playerUrl = `https://vibix.org/embed/imdb/${imdbId}`;
        console.log(`✅ Created Vibix URL from imdb_id for ${movie.type}:`, playerUrl);
    }
    
    // Если ничего нет - показываем ошибку
    if (!playerUrl) {
        console.error('❌ No valid ID found for player URL (need kp_id or imdb_id)');
        console.log('📊 Available movie fields:', Object.keys(movie).join(', '));
        console.log('📊 Checking all possible ID fields:');
        console.log('  - id:', movie.id);
        console.log('  - kp_id:', movie.kp_id);
        console.log('  - imdb_id:', movie.imdb_id);
        console.log('  - kinopoisk_id:', movie.kinopoisk_id);
        console.log('  - kpid:', movie.kpid);
        console.log('  - imdbid:', movie.imdbid);
        console.log('  - iframe_url:', movie.iframe_url);
        console.log('  - player_url:', movie.player_url);
        console.log('📊 Movie name:', movie.name_rus || movie.name_eng || movie.name);
        console.log('📊 Full movie object:', movie);
    }
    
    if (playerUrl) {
        currentMovie.playerUrl = playerUrl;
        console.log('🎬 Final player URL:', playerUrl);
    } else {
        console.warn('⚠️ No player URL could be determined for this movie');
    }
    
    // Setup button events
    // loadPlayerBtn removed - auto-loading now
    
    if (scrollToPlayerBtn) {
        scrollToPlayerBtn.onclick = () => scrollToPlayer();
    }
}

// Auto-load player
function autoLoadPlayer() {
    if (currentMovie && currentMovie.playerUrl) {
        console.log('Auto-loading player with URL:', currentMovie.playerUrl);
        loadPlayer();
    } else {
        console.log('No player URL available for auto-loading');
        // Show message that player is not available
        if (playerPlaceholder) {
            playerPlaceholder.innerHTML = `
                <div class="placeholder-content">
                    <i class="fas fa-exclamation-triangle"></i>
                    <h4>Плеер недоступен</h4>
                    <p>К сожалению, для этого фильма нет доступного плеера</p>
                </div>
            `;
        }
        
        // loadPlayerBtn removed - showing error in placeholder instead
    }
}

// Load player (МАКСИМАЛЬНО БЫСТРАЯ ВЕРСИЯ)
function loadPlayer() {
    if (!currentMovie || !currentMovie.playerUrl) {
        console.error('No player URL available');
        return;
    }
    
    console.log('⚡ Loading player instantly:', currentMovie.playerUrl);
    
    // МГНОВЕННАЯ ЗАГРУЗКА - убираем все задержки!
    // Сразу загружаем iframe
    if (embeddedVideoFrame) {
        embeddedVideoFrame.style.display = 'block';
        embeddedVideoFrame.src = currentMovie.playerUrl;
    }
    
    // Скрываем placeholder
    if (playerPlaceholder) {
        playerPlaceholder.style.display = 'none';
    }
    
    // Показываем кнопку полноэкранного режима
    if (fullscreenBtn) {
        fullscreenBtn.style.display = 'flex';
    }
    
    // Обновляем текст кнопки прокрутки
    if (scrollToPlayerBtn) {
        scrollToPlayerBtn.innerHTML = '<i class="fas fa-tv"></i> К плееру';
    }
    
    console.log('✅ Player loaded instantly!');
}

// Scroll to player
function scrollToPlayer() {
    videoPlayerSection.scrollIntoView({ 
        behavior: 'smooth', 
        block: 'start' 
    });
}

// Toggle fullscreen
function toggleFullscreen() {
    const iframe = embeddedVideoFrame;
    
    if (iframe.requestFullscreen) {
        iframe.requestFullscreen();
    } else if (iframe.webkitRequestFullscreen) {
        iframe.webkitRequestFullscreen();
    } else if (iframe.msRequestFullscreen) {
        iframe.msRequestFullscreen();
    }
}

// Search from header - перенаправляем на главную страницу
function searchFromHeader() {
    const query = document.getElementById('searchInput').value.trim();
    if (query) {
        // Перенаправляем на главную страницу с параметром поиска
        window.location.href = `index.html?search=${encodeURIComponent(query)}`;
    }
}

// Show/hide loading
function showLoading(show) {
    loadingElement.style.display = show ? 'block' : 'none';
}

// Show error
function showError() {
    loadingElement.style.display = 'none';
    movieDetailsElement.style.display = 'none';
    errorMessageElement.style.display = 'block';
}

// Utility function to format duration
function formatDuration(minutes) {
    if (!minutes) return '';
    
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    
    if (hours > 0) {
        return `${hours}ч ${mins}м`;
    }
    return `${mins}м`;
}

// Счетчик попыток для изображений
const posterRetryCount = new Map();

// Обработка ошибок загрузки постера
function handlePosterError(img) {
    const originalUrl = img.getAttribute('data-original');
    if (!originalUrl) {
        showPosterPlaceholder(img);
        return;
    }
    
    const retries = posterRetryCount.get(originalUrl) || 0;
    
    // Максимум 5 попыток (5 разных прокси)
    if (retries < 5) {
        console.log(`Poster retry ${retries + 1}/5`);
        posterRetryCount.set(originalUrl, retries + 1);
        
        // Переключаемся на следующий прокси
        currentProxyIndex++;
        
        // Пробуем загрузить через другой прокси
        img.src = getImageUrl(originalUrl);
    } else {
        // После 5 попыток пробуем прямую загрузку
        if (retries === 5) {
            console.log('Trying direct URL for poster');
            posterRetryCount.set(originalUrl, retries + 1);
            img.src = originalUrl;
        } else {
            // Показываем placeholder
            console.log('All attempts failed for poster');
            posterRetryCount.delete(originalUrl);
            showPosterPlaceholder(img);
        }
    }
}

// Показать placeholder для постера
function showPosterPlaceholder(img) {
    img.onerror = null;
    img.src = 'https://via.placeholder.com/300x450/1a1a2e/64b5f6?text=Нет+постера';
}

// Update Open Graph meta tags for social sharing
function updateOpenGraph(title, description, imageUrl) {
    const ogTags = {
        'og:title': title,
        'og:description': description.substring(0, 200),
        'og:image': imageUrl,
        'og:type': 'video.movie',
        'og:site_name': 'KINO HD PREMIUM'
    };
    
    for (const [property, content] of Object.entries(ogTags)) {
        let meta = document.querySelector(`meta[property="${property}"]`);
        if (!meta) {
            meta = document.createElement('meta');
            meta.setAttribute('property', property);
            document.head.appendChild(meta);
        }
        meta.content = content;
    }
}

// Update Schema.org structured data for Google
function updateSchemaOrg(movie) {
    const title = movie.name_rus || movie.name_eng || movie.name || 'Фільм';
    const description = movie.description || movie.description_short || 'Описание недоступно';
    
    // Создаем Schema.org разметку для фильма/сериала
    const schemaData = {
        "@context": "https://schema.org",
        "@type": movie.type === 'serial' ? "TVSeries" : "Movie",
        "name": title,
        "alternateName": movie.name_original || movie.name_eng,
        "description": description,
        "image": movie.poster_url || movie.backdrop_url,
        "url": window.location.href,
        "dateCreated": movie.year ? `${movie.year}-01-01` : undefined,
        "genre": movie.genre || [],
        "countryOfOrigin": movie.country ? movie.country.map(c => ({
            "@type": "Country",
            "name": c
        })) : undefined,
        "contentRating": movie.age_rating || undefined,
        "aggregateRating": {}
    };
    
    // Добавляем рейтинги если есть
    const ratings = [];
    if (movie.kp_rating) {
        const kpRating = parseFloat(movie.kp_rating);
        if (kpRating > 0) {
            ratings.push({
                "@type": "Rating",
                "ratingValue": kpRating,
                "bestRating": 10,
                "worstRating": 0,
                "author": {
                    "@type": "Organization",
                    "name": "Кинопоиск"
                }
            });
        }
    }
    
    if (movie.imdb_rating) {
        const imdbRating = parseFloat(movie.imdb_rating);
        if (imdbRating > 0) {
            ratings.push({
                "@type": "Rating",
                "ratingValue": imdbRating,
                "bestRating": 10,
                "worstRating": 0,
                "author": {
                    "@type": "Organization",
                    "name": "IMDb"
                }
            });
        }
    }
    
    // Используем средний рейтинг для aggregateRating
    if (ratings.length > 0) {
        const avgRating = ratings.reduce((sum, r) => sum + r.ratingValue, 0) / ratings.length;
        schemaData.aggregateRating = {
            "@type": "AggregateRating",
            "ratingValue": avgRating.toFixed(1),
            "bestRating": 10,
            "worstRating": 0,
            "ratingCount": ratings.length
        };
    } else {
        delete schemaData.aggregateRating;
    }
    
    // Удаляем undefined значения
    Object.keys(schemaData).forEach(key => {
        if (schemaData[key] === undefined) {
            delete schemaData[key];
        }
    });
    
    // Обновляем или создаем script tag с Schema.org
    let schemaScript = document.getElementById('movieSchema');
    if (!schemaScript) {
        schemaScript = document.createElement('script');
        schemaScript.id = 'movieSchema';
        schemaScript.type = 'application/ld+json';
        document.head.appendChild(schemaScript);
    }
    schemaScript.textContent = JSON.stringify(schemaData, null, 2);
}

// Global functions
window.toggleSeason = toggleSeason;
window.playEpisode = playEpisode;
window.loadPlayer = loadPlayer;
window.scrollToPlayer = scrollToPlayer;
window.toggleFullscreen = toggleFullscreen;
window.searchFromHeader = searchFromHeader;
