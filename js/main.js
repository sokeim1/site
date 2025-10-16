// Global variables
let currentPage = 1;
let currentCategory = 'all';
let isLoading = false;
let hasMorePages = true;
let allGenres = [];
let allCountries = [];
// Используем прямые ссылки на изображения без прокси для лучшей производительности
// Прокси-сервисы могут быть медленными или блокироваться
let totalMoviesLoaded = 0;

// DOM elements
const moviesGrid = document.getElementById('moviesGrid');
const loadingElement = document.getElementById('loading');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const searchInput = document.getElementById('searchInput');
const moviesCounter = document.getElementById('moviesCounter');

// Initialize the application
document.addEventListener('DOMContentLoaded', async function() {
    window.loadStartTime = Date.now();
    console.log('🚀 Page loaded, initializing optimized CineHub...');
    
    // Используем прямые ссылки на изображения для быстрой загрузки
    console.log('Loading images directly from source');
    
    // Test simple API call first
    try {
        console.log('Testing basic API connection...');
        const testResponse = await fetch('https://vibix.org/api/v1/movies?page=1&limit=5', {
            headers: {
                'Authorization': 'Bearer K5S0n92g87qeScnSrtqxOEpx4SswFFPV1sv5C68465469908',
                'Content-Type': 'application/json'
            }
        });
        console.log('Test response status:', testResponse.status);
        
        if (testResponse.ok) {
            const testData = await testResponse.json();
            console.log('Test API data:', testData);
        } else {
            console.error('Test API failed:', testResponse.status);
        }
    } catch (error) {
        console.error('Test API error:', error);
    }
    
    try {
        // Load initial data
        await loadGenresAndCountries();
        
        // Останавливаем любое текущее построение индекса
        movieAPI.stopIndexBuilding();
        
        // Очищаем кэш поиска для применения новых алгоритмов
        movieAPI.clearCache();
        console.log('🧹 Search cache cleared for improved algorithm');
        
        // Проверяем, есть ли кэшированная база данных
        const stats = movieAPI.getSearchStats();
        if (stats.indexSize > 0) {
            console.log('🎉 БАЗА ДАННЫХ УЖЕ ЗАГРУЖЕНА ИЗ КЭША! Поиск готов мгновенно!');
            // Notification removed for cleaner UI
            
            // Counter text removed for cleaner UI
        } else {
            // Если кэша нет, строим индекс
            // Автоматическое построение индекса ОТКЛЮЧЕНО
            // Индекс загружается из предварительно построенного файла js/prebuilt-index.js
            // Для построения индекса используйте: node build-index.js
            
            console.log('📦 Checking for prebuilt index...');
            
            const stats = movieAPI.getSearchStats();
            if (stats.indexSize > 0) {
                console.log('✅ Prebuilt index loaded:', stats.indexSize, 'movies');
                // Counter text removed for cleaner UI
                // Notification removed for cleaner UI
            } else {
                console.log('⚠️ No prebuilt index found. Search will use API.');
                // Counter text removed for cleaner UI
            }
        }
        
        // Проверяем URL параметры для поиска
        const urlParams = new URLSearchParams(window.location.search);
        const searchQuery = urlParams.get('search');
        const hash = window.location.hash;
        
        if (searchQuery) {
            // Если есть параметр поиска, устанавливаем его в поле ввода и выполняем поиск
            searchInput.value = searchQuery;
            await searchMovies();
        } else if (hash === '#popular') {
            // Если есть якорь #popular, показываем популярные фильмы
            await showPopularMovies();
        } else {
            // Иначе загружаем обычные фильмы
            await loadMovies();
        }
        
        // Set up event listeners
        setupEventListeners();
        
        // Load genres for dropdown
        await loadGenresDropdown();
        
        // Показываем прогресс построения индекса каждые 2 секунды
        const progressInterval = setInterval(() => {
            const stats = movieAPI.getSearchStats();
            // Index building progress removed for cleaner UI
            if (!stats.isIndexBuilding && stats.indexSize > 0) {
                clearInterval(progressInterval);
            }
        }, 2000); // 2 секунды
        
    } catch (error) {
        console.error('Error initializing app:', error);
        showError('Ошибка при загрузке данных. Пожалуйста, попробуйте позже.');
    }
});

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

// Load genres and countries for filtering
async function loadGenresAndCountries() {
    try {
        const [genresResponse, countriesResponse] = await Promise.all([
            movieAPI.getGenres(),
            movieAPI.getCountries()
        ]);
        
        allGenres = genresResponse.data || [];
        allCountries = countriesResponse.data || [];
        
    } catch (error) {
        console.error('Error loading genres and countries:', error);
    }
}

// Set up event listeners
function setupEventListeners() {
    // Filter tabs
    const filterTabs = document.querySelectorAll('.filter-tab');
    filterTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const category = this.dataset.category;
            switchCategory(category);
        });
    });

    // Sidebar filters
    const sidebarFilters = document.querySelectorAll('.filter-list a');
    sidebarFilters.forEach(filter => {
        filter.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Remove active class from siblings
            this.parentElement.parentElement.querySelectorAll('a').forEach(a => {
                a.classList.remove('active');
            });
            
            // Add active class to clicked filter
            this.classList.add('active');
            
            // Get filter data
            const filterType = this.dataset.category || this.dataset.year || this.dataset.rating;
            filterMoviesBySidebar('category', filterType);
        });
    });

    // Enhanced search functionality with debouncing
    let searchTimeout;
    searchInput.addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        // Показываем подсказки при вводе
        if (query.length >= 2) {
            searchTimeout = setTimeout(() => {
                // Можно добавить автодополнение здесь в будущем
                console.log('🔍 Search suggestion for:', query);
            }, 500);
        }
    });
    
    searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            clearTimeout(searchTimeout);
            searchMovies();
        }
    });
    
    // Добавляем кнопку очистки поиска
    const clearSearchBtn = document.createElement('button');
    clearSearchBtn.innerHTML = '🗑️';
    clearSearchBtn.className = 'clear-search-btn';
    clearSearchBtn.title = 'Очистить поиск';
    clearSearchBtn.style.cssText = `
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        background: none;
        border: none;
        font-size: 16px;
        cursor: pointer;
        opacity: 0.6;
        transition: opacity 0.2s;
    `;
    
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchInput.focus();
        // Перезагружаем обычные фильмы
        currentPage = 1;
        totalMoviesLoaded = 0;
        hasMorePages = true;
        loadMovies();
    });
    
    clearSearchBtn.addEventListener('mouseenter', () => {
        clearSearchBtn.style.opacity = '1';
    });
    
    clearSearchBtn.addEventListener('mouseleave', () => {
        clearSearchBtn.style.opacity = '0.6';
    });
    
    // Добавляем кнопку к контейнеру поиска
    const searchContainer = searchInput.parentElement;
    if (searchContainer) {
        searchContainer.style.position = 'relative';
        searchContainer.appendChild(clearSearchBtn);
    }

    // Load more button
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', loadMoreMovies);
    }
    
    // Infinite scroll - загружаем больше фильмов при прокрутке вниз
    window.addEventListener('scroll', () => {
        // Проверяем, достиг ли пользователь почти конца страницы
        const scrollPosition = window.innerHeight + window.scrollY;
        const pageHeight = document.documentElement.scrollHeight;
        
        // Загружаем новые фильмы, когда пользователь прокрутил до 80% страницы
        if (scrollPosition >= pageHeight * 0.8 && hasMorePages && !isLoading) {
            console.log('Infinite scroll triggered - loading more movies');
            loadMoreMovies();
        }
    });
}

// Switch between categories
async function switchCategory(category) {
    // Update active tab
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelector(`[data-category="${category}"]`).classList.add('active');

    // Reset pagination and reload all movies
    currentPage = 1;
    currentCategory = category;
    hasMorePages = true;
    totalMoviesLoaded = 0;
    
    // Clear current movies
    moviesGrid.innerHTML = '';
    
    console.log(`🎬 Switching to category: ${category}`);
    
    // Load new movies with filters
    await loadMoviesWithFilter(category);
}

// Load movies with category filter (with infinite scroll support)
async function loadMoviesWithFilter(category, append = false) {
    if (isLoading) return;
    
    isLoading = true;
    showLoading(true);
    
    try {
        const limit = 100;
        
        console.log(`⚡ Loading movies with filter: ${category}, page: ${currentPage}, append: ${append}`);
        
        // Загружаем текущую страницу
        const response = await movieAPI.getPageWithCache(currentPage, limit, {});
        
        if (response && response.data && Array.isArray(response.data)) {
            let movies = response.data;
            
            // Фильтруем по категории
            if (category === 'movie') {
                // Только фильмы
                movies = movies.filter(m => m.type === 'movie');
            } else if (category === 'serial') {
                // Только сериалы
                movies = movies.filter(m => m.type === 'serial');
            } else if (category === 'new') {
                // Только новинки 2024-2025
                movies = movies.filter(m => m.year >= 2024);
            }
            // category === 'all' - показываем все
            
            console.log(`✅ Loaded ${movies.length} filtered movies from page ${currentPage}`);
            
            if (movies.length > 0) {
                displayMovies(movies, append);
                totalMoviesLoaded += movies.length;
                
                // Проверяем, есть ли ещё страницы
                if (response.data.length >= limit) {
                    hasMorePages = true;
                } else {
                    hasMorePages = false;
                }
            } else if (!append) {
                // Если на первой странице ничего не нашли, пробуем следующую
                if (response.data.length >= limit) {
                    currentPage++;
                    await loadMoviesWithFilter(category, false);
                    return;
                } else {
                    moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3><p>Попробуйте другую категорию</p></div>';
                    hasMorePages = false;
                }
            }
        } else {
            hasMorePages = false;
        }
        
    } catch (error) {
        console.error('❌ Error loading filtered movies:', error);
        showError('Ошибка при загрузке фильмов. Попробуйте позже.');
    } finally {
        isLoading = false;
        showLoading(false);
        updateLoadMoreButton();
    }
}

// Load movies based on current category (optimized for fast initial load)
async function loadMovies(append = false) {
    if (isLoading) return;
    
    isLoading = true;
    showLoading(true);
    
    try {
        let response;
        // Уменьшаем лимит для первой загрузки чтобы ускорить отображение
        const limit = append ? 100 : 50; // 50 для первой загрузки, 100 для дозагрузки
        
        console.log(`⚡ Loading movies - Category: ${currentCategory}, Page: ${currentPage}, Limit: ${limit}`);
        
        // Используем кэшированный запрос для ускорения
        response = await movieAPI.getPageWithCache(currentPage, limit, {});
        
        console.log(`✅ API Response received in ${Date.now() - (window.loadStartTime || Date.now())}ms:`, response?.data?.length, 'movies');
        
        // Check different possible data structures
        let movies = [];
        if (response && response.data && Array.isArray(response.data)) {
            movies = response.data;
        } else if (response && Array.isArray(response)) {
            movies = response;
        } else if (response && response.results && Array.isArray(response.results)) {
            movies = response.results;
        }
        
        console.log('Extracted movies:', movies);
        
        if (movies && movies.length > 0) {
            console.log(`✅ Loaded ${movies.length} movies successfully`);
            // Логируем первый фильм для проверки структуры данных
            if (movies[0]) {
                console.log('📊 First movie structure:', movies[0]);
                console.log('📊 Has kp_id?', !!movies[0].kp_id);
                console.log('📊 Has iframe_url?', !!movies[0].iframe_url);
            }
            displayMovies(movies, append);
            
            totalMoviesLoaded += movies.length;
            
            // Update movies counter
            updateMoviesCounter();
            
            // Update pagination info - если получили полный лимит фильмов, значит есть ещё страницы
            // API Vibix имеет более 20000 страниц, поэтому всегда есть следующая страница
            hasMorePages = movies.length >= limit;
            
            // Логируем пагинацию только для отладки
            if (window.DEBUG) {
                console.log('Pagination info:', {
                    currentPage,
                    moviesReceived: movies.length,
                    limit,
                    hasMorePages,
                    totalLoaded: totalMoviesLoaded
                });
            }
            
            // Показываем кнопку "Загрузить ещё" если есть ещё фильмы
            updateLoadMoreButton();
        } else {
            console.warn('⚠️ No movies received from API');
            hasMorePages = false;
            updateLoadMoreButton();
            updateMoviesCounter();
        }
        
    } catch (error) {
        console.error('❌ Error loading movies:', error);
        showError('Ошибка при загрузке фильмов. Попробуйте позже.');
    } finally {
        isLoading = false;
        showLoading(false);
        
        // Отмечаем время завершения загрузки
        if (!append) {
            const loadTime = Date.now() - (window.loadStartTime || Date.now());
            console.log(`🏁 Initial load completed in ${loadTime}ms`);
        }
    }
}

// Display movies in the grid (с отладкой)
function displayMovies(movies, append = false) {
    console.log('🎬 displayMovies called with:', movies.length, 'movies, append:', append);
    
    if (!movies || !Array.isArray(movies) || movies.length === 0) {
        console.log('⚠️ No movies to display');
        if (!append) {
            moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3></div>';
        }
        return;
    }
    
    if (!append) {
        moviesGrid.innerHTML = '';
        console.log('🧹 Cleared movies grid');
    }
    
    // Сортируем фильмы: сначала с постерами, потом без
    const sortedMovies = [...movies].sort((a, b) => {
        const hasPosterA = !!(a.poster_url || a.poster || a.image_url || a.backdrop_url);
        const hasPosterB = !!(b.poster_url || b.poster || b.image_url || b.backdrop_url);
        
        // Фильмы с постерами идут первыми
        if (hasPosterA && !hasPosterB) return -1;
        if (!hasPosterA && hasPosterB) return 1;
        return 0;
    });
    
    console.log('🎬 Creating', sortedMovies.length, 'movie cards');
    
    let cardsCreated = 0;
    sortedMovies.forEach((movie, index) => {
        try {
            const movieCard = createMovieCard(movie);
            if (movieCard) {
                moviesGrid.appendChild(movieCard);
                cardsCreated++;
            }
        } catch (error) {
            console.error(`❌ Error creating card for movie ${index}:`, error, movie);
        }
    });
    
    console.log(`✅ Successfully created ${cardsCreated} movie cards`);
}

// Create movie card element (с проверками)
function createMovieCard(movie) {
    if (!movie) {
        console.warn('⚠️ Cannot create card for null/undefined movie');
        return null;
    }
    
    const card = document.createElement('div');
    card.className = 'movie-card';
    card.onclick = () => openMovieDetails(movie);
    
    // Get poster URL or use placeholder
    let posterUrl = movie.poster_url;
    
    // Try different poster URL fields
    if (!posterUrl) {
        posterUrl = movie.poster || movie.image_url || movie.backdrop_url;
    }
    
    // If still no poster URL, use placeholder
    if (!posterUrl) {
        posterUrl = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjQ1MCIgdmlld0JveD0iMCAwIDMwMCA0NTAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIzMDAiIGhlaWdodD0iNDUwIiBmaWxsPSIjMWExYTJlIi8+Cjx0ZXh0IHg9IjE1MCIgeT0iMjI1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjNjRiNWY2IiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTgiPk5ldCDQv9C+0YHRgtC10YDQsDwvdGV4dD4KPC9zdmc+';
    }
    // Используем прямые ссылки на изображения
    if (posterUrl && posterUrl.startsWith('http')) {
        posterUrl = getImageUrl(posterUrl);
    }
    
    console.log('Movie poster URL:', posterUrl, 'for movie:', movie.name_rus || movie.name);
    
    // Get rating (try different possible field names)
    const rating = parseFloat(movie.kp_rating) || parseFloat(movie.imdb_rating) || parseFloat(movie.rating) || parseFloat(movie.vote_average) || 0;
    
    // Get year from movie data (try different field names)
    const year = movie.year || movie.release_date?.substring(0, 4) || movie.first_air_date?.substring(0, 4) || 'Неизвестно';
    
    // Get movie title (try different field names)
    const title = movie.name_rus || movie.name_eng || movie.name || movie.title || movie.original_title || movie.original_name || 'Без названия';
    
    console.log('Movie data for card:', { title, year, rating, poster: movie.poster_url });
    
    // Сохраняем оригинальный URL для fallback
    const originalPosterUrl = movie.poster_url || movie.poster || movie.image_url || movie.backdrop_url;
    
    card.innerHTML = `
        <div class="movie-poster">
            <img src="${posterUrl}" alt="${title}" 
                 loading="lazy"
                 data-original="${originalPosterUrl || ''}"
                 onerror="handleImageError(this, '${title}')">
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

// Open movie details page
async function openMovieDetails(movie) {
    console.log('🎬 Opening movie details for:', movie.name_rus || movie.name);
    console.log('📊 Movie data:', movie);
    
    // ВАЖНО: Если фильм из индекса, у него может не быть kp_id и iframe_url
    // Делаем быстрый API запрос для получения полных данных
    let fullMovieData = movie;
    
    // Если нет kp_id и iframe_url, пытаемся получить их через API
    if (!movie.kp_id && !movie.iframe_url) {
        console.log('⚡ Movie from index, fetching full data from API...');
        
        try {
            // Пробуем получить данные по imdb_id (если есть)
            if (movie.imdb_id) {
                const response = await movieAPI.getMovieByImdbId(movie.imdb_id);
                if (response && response.data) {
                    fullMovieData = { ...movie, ...response.data };
                    console.log('✅ Got full data from IMDB ID');
                }
            }
        } catch (error) {
            console.warn('⚠️ Could not fetch full movie data, using index data');
        }
    }
    
    // Store movie data in localStorage for the details page
    localStorage.setItem('selectedMovie', JSON.stringify(fullMovieData));
    
    // Navigate to details page
    window.location.href = `movie-details.html?id=${fullMovieData.id}`;
}

// Load more movies
async function loadMoreMovies() {
    if (!hasMorePages || isLoading) return;
    
    currentPage++;
    
    // Проверяем, какой фильтр активен
    if (currentCategory === 'year' && currentFilterYear) {
        // Фильтрация по году
        await loadMoviesByYear(currentFilterYear, true);
    } else if (currentCategory && currentCategory !== 'all') {
        // Фильтрация по категории
        await loadMoviesWithFilter(currentCategory, true);
    } else {
        // Обычная загрузка
        await loadMovies(true);
    }
}

// Filter movies by sidebar filters
function filterMoviesBySidebar(filterType, filterValue) {
    console.log(`Filtering by ${filterType}:`, filterValue);
    
    // Get all movie cards
    const movieCards = document.querySelectorAll('.movie-card');
    
    movieCards.forEach(card => {
        let shouldShow = true;
        
        // Here you would implement filtering logic based on movie data
        // For now, we'll show all movies
        
        if (shouldShow) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}

// Search movies with enhanced UI feedback
async function searchMovies() {
    const query = searchInput.value.trim();
    
    if (!query) {
        // If search is empty, reload current category
        currentPage = 1;
        totalMoviesLoaded = 0;
        hasMorePages = true;
        await loadMovies();
        return;
    }
    
    console.log('🔍 Starting enhanced search for:', query);
    
    isLoading = true;
    showLoading(true);
    
    // Показываем детальное сообщение о поиске
    const stats = movieAPI.getSearchStats();
    if (moviesCounter) {
        if (stats.indexSize > 0) {
            moviesCounter.textContent = `🚀 Быстрый поиск "${query}" по индексу из ${stats.indexSize.toLocaleString()} фильмов...`;
        } else {
            moviesCounter.textContent = `🔍 Поиск "${query}" в базе данных 20k+ фильмов...`;
        }
    }
    
    const startTime = Date.now();
    
    try {
        console.log('🔍 Calling movieAPI.searchMovies with query:', query);
        const response = await movieAPI.searchMovies(query, {
            limit: 100
        });
        
        const searchTime = Date.now() - startTime;
        console.log(`⚡ Search completed in ${searchTime}ms:`, response);
        console.log('🔍 Response structure check:', {
            hasResponse: !!response,
            hasData: !!(response && response.data),
            isDataArray: !!(response && response.data && Array.isArray(response.data)),
            dataLength: response && response.data ? response.data.length : 0
        });
        
        if (response && response.data && Array.isArray(response.data)) {
            console.log('✅ Search response received:', response.data.length, 'movies');
            
            // Очищаем текущие фильмы
            moviesGrid.innerHTML = '';
            
            // Проверяем, что есть фильмы для отображения
            if (response.data.length > 0) {
                console.log('✅ Displaying', response.data.length, 'search results');
                displayMovies(response.data, false);
            } else {
                console.log('⚠️ No movies to display');
                moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3><p>Попробуйте изменить запрос</p></div>';
            }
            
            // Обновляем счетчик с подробной статистикой
            totalMoviesLoaded = response.data.length;
            if (moviesCounter) {
                if (response.data.length === 0) {
                    moviesCounter.textContent = `❌ По запросу "${query}" ничего не найдено`;
                } else {
                    let counterText = `✅ Найдено: ${response.data.length} фильмов по запросу "${query}" за ${searchTime}ms`;
                    
                    // Добавляем статистику поиска если есть
                    if (response.meta && response.meta.search_stats) {
                        const searchStats = response.meta.search_stats;
                        counterText += ` (просмотрено ${searchStats.processed_movies} из ${searchStats.processed_pages} страниц)`;
                    }
                    
                    // Показываем метод поиска
                    if (response.meta && response.meta.search_method === 'index') {
                        counterText += ' 🚀 через индекс';
                    }
                    
                    moviesCounter.textContent = counterText;
                }
            }
            
            // Notification removed for cleaner UI
            
            // Отключаем кнопку "Загрузить ещё" для результатов поиска
            hasMorePages = false;
            updateLoadMoreButton();
            
        } else {
            console.log('❌ Invalid search response:', response);
            if (moviesCounter) {
                moviesCounter.textContent = `❌ По запросу "${query}" ничего не найдено`;
            }
            moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3><p>Попробуйте изменить запрос</p></div>';
            showNotification(`По запросу "${query}" ничего не найдено`, 'warning');
        }
        
    } catch (error) {
        console.error('❌ Error searching movies:', error);
        showError('Ошибка при поиске фильмов. Попробуйте еще раз.');
        if (moviesCounter) {
            moviesCounter.textContent = '❌ Ошибка поиска';
        }
    } finally {
        isLoading = false;
        showLoading(false);
    }
}

// Show/hide loading indicator
function showLoading(show) {
    if (loadingElement) {
        loadingElement.classList.toggle('show', show);
    }
}

// Update load more button state
function updateLoadMoreButton() {
    if (loadMoreBtn) {
        loadMoreBtn.style.display = hasMorePages ? 'block' : 'none';
        loadMoreBtn.disabled = isLoading;
    }
}

// Update movies counter
function updateMoviesCounter() {
    if (moviesCounter) {
        if (totalMoviesLoaded === 0) {
            moviesCounter.textContent = 'Загружаем...';
        } else {
            moviesCounter.textContent = `Загружено: ${totalMoviesLoaded} фильмов`;
            
            if (hasMorePages) {
                moviesCounter.textContent += ' (есть ещё)';
            } else {
                moviesCounter.textContent += ' (все загружены)';
            }
        }
    }
}

// Show notification message
function showNotification(message, type = 'info') {
    const colors = {
        info: 'rgba(23, 162, 184, 0.95)',
        success: 'rgba(40, 167, 69, 0.95)',
        warning: 'rgba(255, 193, 7, 0.95)',
        error: 'rgba(220, 53, 69, 0.95)'
    };
    
    const icons = {
        info: 'fas fa-info-circle',
        success: 'fas fa-check-circle',
        warning: 'fas fa-exclamation-triangle',
        error: 'fas fa-exclamation-triangle'
    };
    
    const notificationDiv = document.createElement('div');
    notificationDiv.className = `${type}-notification`;
    notificationDiv.innerHTML = `
        <div class="notification-content">
            <i class="${icons[type]}"></i>
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    notificationDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${colors[type]};
        color: white;
        padding: 1rem;
        border-radius: 8px;
        z-index: 10000;
        max-width: 400px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        animation: slideIn 0.3s ease-out;
    `;
    
    document.body.appendChild(notificationDiv);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notificationDiv.parentElement) {
            notificationDiv.style.animation = 'slideOut 0.3s ease-in';
            setTimeout(() => notificationDiv.remove(), 300);
        }
    }, 5000);
}

// Show error message
function showError(message) {
    showNotification(message, 'error');
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

// Utility function to format genres
function formatGenres(genres) {
    if (!genres || !Array.isArray(genres)) return '';
    return genres.slice(0, 3).join(', ');
}

// Счетчик попыток для каждого изображения
const imageRetryCount = new Map();

// Обработка ошибок загрузки изображений
function handleImageError(img, title) {
    console.log('Image failed to load for:', title);
    
    // Получаем оригинальный URL из data-атрибута
    const originalUrl = img.getAttribute('data-original');
    if (!originalUrl) {
        showPlaceholder(img);
        return;
    }
    
    // Получаем количество попыток для этого изображения
    const retries = imageRetryCount.get(originalUrl) || 0;
    
    // Максимум 5 попыток (5 разных прокси)
    if (retries < 5) {
        console.log(`Retry ${retries + 1}/5 for:`, title);
        imageRetryCount.set(originalUrl, retries + 1);
        
        // Переключаемся на следующий прокси
        currentProxyIndex++;
        
        // Пробуем загрузить через другой прокси
        img.src = getImageUrl(originalUrl);
    } else {
        // После 5 попыток пробуем прямую загрузку
        if (retries === 5) {
            console.log('Trying direct URL after all proxies failed:', originalUrl);
            imageRetryCount.set(originalUrl, retries + 1);
            img.src = originalUrl;
        } else {
            // Если и прямая загрузка не сработала, показываем placeholder
            console.log('All attempts failed, showing placeholder for:', title);
            imageRetryCount.delete(originalUrl);
            showPlaceholder(img);
        }
    }
}

// Показать placeholder
function showPlaceholder(img) {
    img.onerror = null;
    img.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzAwIiBoZWlnaHQ9IjQ1MCIgdmlld0JveD0iMCAwIDMwMCA0NTAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIzMDAiIGhlaWdodD0iNDUwIiBmaWxsPSIjMWExYTJlIi8+Cjx0ZXh0IHg9IjE1MCIgeT0iMjI1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjNjRiNWY2IiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTgiPk5ldCDQv9C+0YHRgtC10YDQsDwvdGV4dD4KPC9zdmc+';
}

// Добавляем функцию для очистки кэша поиска
function clearSearchCache() {
    movieAPI.clearCache();
    showNotification('Кэш поиска очищен', 'info');
}

// Функция для тестирования API и поиска
async function testSearchAPI() {
    console.log('🧪 Testing search API...');
    
    try {
        // Тестируем загрузку первых страниц
        const testResponse = await movieAPI.getPageWithCache(1, 20, {});
        console.log('📊 Test API response:', testResponse);
        
        if (testResponse && testResponse.data && testResponse.data.length > 0) {
            console.log('✅ API working. Sample movies:');
            testResponse.data.slice(0, 5).forEach((movie, index) => {
                console.log(`${index + 1}.`, {
                    name_rus: movie.name_rus,
                    name_eng: movie.name_eng,
                    name: movie.name,
                    name_original: movie.name_original
                });
            });
            
            // Тестируем поиск "игра"
            console.log('🔍 Testing search for "игра"...');
            const searchResults = movieAPI.filterMoviesByQuery(testResponse.data, 'игра');
            console.log('🎯 Search results for "игра":', searchResults.length, 'movies');
            if (searchResults.length > 0) {
                console.log('Found movies:', searchResults.slice(0, 3).map(m => m.name_rus || m.name));
            }
            
            // Тестируем поиск "кальмар"
            console.log('🔍 Testing search for "кальмар"...');
            const searchResults2 = movieAPI.filterMoviesByQuery(testResponse.data, 'кальмар');
            console.log('🎯 Search results for "кальмар":', searchResults2.length, 'movies');
            if (searchResults2.length > 0) {
                console.log('Found movies:', searchResults2.slice(0, 3).map(m => m.name_rus || m.name));
            }
            
            // Тестируем комбинированный поиск
            console.log('🔍 Testing search for "игра в кальмара"...');
            const searchResults3 = movieAPI.filterMoviesByQuery(testResponse.data, 'игра в кальмара');
            console.log('🎯 Search results for "игра в кальмара":', searchResults3.length, 'movies');
            if (searchResults3.length > 0) {
                console.log('Found movies:', searchResults3.slice(0, 3).map(m => m.name_rus || m.name));
            }
            
            showNotification(`Тест API: найдено ${testResponse.data.length} фильмов на первой странице`, 'info');
        } else {
            console.error('❌ API test failed - no data received');
            showNotification('Тест API не удался - нет данных', 'error');
        }
        
    } catch (error) {
        console.error('❌ API test error:', error);
        showNotification('Ошибка при тестировании API', 'error');
    }
}

// Делаем функцию доступной глобально для тестирования из консоли
window.testSearchAPI = testSearchAPI;

// ЭКСТРЕННАЯ ФУНКЦИЯ - проверяем что вообще есть в базе
window.debugFirstMovies = async function() {
    console.log('🔍 DEBUG: Checking first movies in database...');
    
    try {
        const result = await movieAPI.getPageWithCache(1, 20, {});
        console.log('📊 First page result:', result);
        
        if (result && result.data && result.data.length > 0) {
            console.log(`✅ Found ${result.data.length} movies on first page:`);
            
            result.data.forEach((movie, i) => {
                console.log(`${i+1}. Movie object:`, {
                    id: movie.id,
                    name_rus: movie.name_rus,
                    name_eng: movie.name_eng,
                    name: movie.name,
                    name_original: movie.name_original,
                    title: movie.title,
                    original_title: movie.original_title
                });
            });
            
            // Тестируем поиск на первых фильмах
            console.log('🧪 Testing search on first movies...');
            const testResult = movieAPI.filterMoviesByQuery(result.data, 'игра');
            console.log('🎯 Test search result:', testResult);
            
        } else {
            console.error('❌ No movies found on first page!');
        }
        
        return result;
    } catch (error) {
        console.error('❌ Error checking first movies:', error);
        return null;
    }
};

// Функция для быстрого тестирования поиска из консоли
window.quickSearch = async function(query) {
    console.log(`🔍 Quick search for: "${query}"`);
    try {
        const result = await movieAPI.searchMovies(query);
        console.log('Search result:', result);
        if (result && result.data) {
            console.log(`Found ${result.data.length} movies:`);
            result.data.slice(0, 5).forEach((movie, i) => {
                console.log(`${i+1}. ${movie.name_rus || movie.name || 'Без названия'}`);
            });
        }
        return result;
    } catch (error) {
        console.error('Search error:', error);
        return null;
    }
};

// Функция для проверки данных на странице
window.checkPageData = async function(page = 1) {
    console.log(`📄 Checking page ${page} data...`);
    try {
        const result = await movieAPI.getPageWithCache(page, 20, {});
        console.log('Page data:', result);
        if (result && result.data) {
            console.log(`Page ${page} has ${result.data.length} movies:`);
            result.data.slice(0, 5).forEach((movie, i) => {
                console.log(`${i+1}. ${movie.name_rus || movie.name || 'Без названия'} (ID: ${movie.id})`);
            });
        }
        return result;
    } catch (error) {
        console.error('Page check error:', error);
        return null;
    }
};

// Функция для проверки, какие фильмы вообще есть в базе
window.checkMovieTitles = async function(pages = 5) {
    console.log(`📋 Проверяем названия фильмов на первых ${pages} страницах...`);
    
    const allTitles = [];
    for (let page = 1; page <= pages; page++) {
        try {
            const result = await movieAPI.getPageWithCache(page, 100, {});
            if (result && result.data) {
                result.data.forEach(movie => {
                    const titles = [
                        movie.name_rus,
                        movie.name_eng,
                        movie.name,
                        movie.name_original
                    ].filter(Boolean);
                    
                    allTitles.push({
                        id: movie.id,
                        titles: titles,
                        mainTitle: movie.name_rus || movie.name || 'Без названия'
                    });
                });
            }
        } catch (error) {
            console.error(`Ошибка загрузки страницы ${page}:`, error);
        }
    }
    
    console.log(`📊 Найдено ${allTitles.length} фильмов`);
    
    // Ищем фильмы со словами "игра", "кальмар", "squid", "game"
    const keywords = ['игра', 'кальмар', 'squid', 'game'];
    
    keywords.forEach(keyword => {
        const matches = allTitles.filter(movie => 
            movie.titles.some(title => 
                title.toLowerCase().includes(keyword.toLowerCase())
            )
        );
        
        console.log(`🔍 Фильмы с "${keyword}": ${matches.length}`);
        matches.slice(0, 5).forEach(movie => {
            console.log(`  - ${movie.mainTitle}`);
        });
    });
    
    return allTitles;
};

// Функция для поиска конкретного фильма "Игра в кальмара"
window.findSquidGame = async function() {
    console.log('🦑 Searching for "Squid Game" / "Игра в кальмара"...');
    
    const queries = [
        'игра в кальмара',
        'squid game', 
        'игра кальмара',
        'кальмар',
        'squid'
    ];
    
    for (const query of queries) {
        console.log(`🔍 Trying query: "${query}"`);
        try {
            const result = await movieAPI.searchMovies(query);
            if (result && result.data && result.data.length > 0) {
                console.log(`✅ Found ${result.data.length} results for "${query}":`);
                result.data.slice(0, 3).forEach((movie, i) => {
                    console.log(`${i+1}. ${movie.name_rus || movie.name || 'Без названия'}`);
                });
                
                // Проверяем, есть ли точное совпадение
                const exactMatch = result.data.find(movie => {
                    const titles = [
                        movie.name_rus,
                        movie.name_eng, 
                        movie.name,
                        movie.name_original
                    ].filter(Boolean).map(t => t.toLowerCase());
                    
                    return titles.some(title => 
                        title.includes('игра') && title.includes('кальмар') ||
                        title.includes('squid') && title.includes('game')
                    );
                });
                
                if (exactMatch) {
                    console.log(`🎯 FOUND SQUID GAME: ${exactMatch.name_rus || exactMatch.name}`);
                    return exactMatch;
                }
            } else {
                console.log(`❌ No results for "${query}"`);
            }
        } catch (error) {
            console.error(`Error searching "${query}":`, error);
        }
    }
    
    console.log('❌ Squid Game not found with any query');
    return null;
};

// ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ КЭШЕМ БАЗЫ ДАННЫХ
window.saveDatabaseCache = function() {
    const result = movieAPI.saveDatabaseToCache();
    if (result) {
        showNotification('💾 База данных сохранена в кэш!', 'success');
    } else {
        showNotification('❌ Ошибка сохранения базы данных', 'error');
    }
    return result;
};

window.clearDatabaseCache = function() {
    movieAPI.clearDatabaseCache();
    showNotification('🗑️ Кэш базы данных очищен', 'info');
};

window.checkCacheStatus = function() {
    const stats = movieAPI.getSearchStats();
    console.log('📊 Cache status:', {
        indexSize: stats.indexSize,
        cacheSize: stats.cacheSize,
        pagesCacheSize: stats.pagesCacheSize
    });
    
    // Проверяем localStorage
    try {
        const cached = localStorage.getItem('cinehub_movies_db_v2');
        if (cached) {
            const data = JSON.parse(cached);
            const sizeInMB = (cached.length / (1024 * 1024)).toFixed(2);
            const ageInMinutes = Math.round((Date.now() - data.timestamp) / (60 * 1000));
            
            console.log('💾 LocalStorage cache:', {
                size: sizeInMB + 'MB',
                movies: data.moviesIndex.length,
                age: ageInMinutes + ' minutes'
            });
            
            showNotification(`💾 Кэш: ${data.moviesIndex.length} фильмов (${sizeInMB}MB, ${ageInMinutes}мин)`, 'info');
        } else {
            console.log('📦 No cache in localStorage');
            showNotification('📦 Кэш в localStorage отсутствует', 'warning');
        }
    } catch (error) {
        console.error('❌ Cache check error:', error);
    }
};

// Функция для получения статистики поиска
function getSearchStats() {
    const stats = movieAPI.getSearchStats();
    console.log('📊 Detailed search stats:', stats);
    
    let message = `Статистика поиска:\n`;
    message += `• Всего поисков: ${stats.totalSearches}\n`;
    
    if (stats.totalSearches > 0) {
        message += `• Попаданий в кэш: ${stats.cacheHits} (${Math.round(stats.cacheHits/stats.totalSearches*100)}%)\n`;
        message += `• Среднее время поиска: ${Math.round(stats.avgSearchTime)}ms\n`;
    }
    
    message += `• Размер кэша: ${stats.cacheSize} запросов\n`;
    message += `• Кэш страниц: ${stats.pagesCacheSize} страниц\n`;
    message += `• Индекс: ${stats.indexSize.toLocaleString()} фильмов`;
    
    if (stats.isIndexBuilding) {
        message += ` (строится: ${stats.indexProgress}%)\n\nНажмите OK чтобы остановить построение индекса`;
        
        const shouldStop = confirm(message);
        if (shouldStop) {
            movieAPI.stopIndexBuilding();
            showNotification('Построение индекса остановлено', 'info');
        }
    } else {
        alert(message);
    }
    
    return stats;
}

// Остановка построения индекса
function stopIndexBuilding() {
    movieAPI.stopIndexBuilding();
    showNotification('Построение индекса остановлено', 'warning');
}

// Clear search cache function
function clearSearchCache() {
    movieAPI.clearCache();
    console.log('🧹 Search cache manually cleared');
    showNotification('Кэш поиска очищен', 'success');
}

// Load genres for dropdown menu
async function loadGenresDropdown() {
    try {
        const genresDropdown = document.getElementById('genresDropdown');
        if (!genresDropdown) return;
        
        console.log('📋 Loading genres for dropdown...');
        
        // Получаем жанры из API
        const response = await movieAPI.getGenres();
        
        if (response && response.data && Array.isArray(response.data)) {
            const genres = response.data;
            console.log(`✅ Loaded ${genres.length} genres`);
            
            // Создаем элементы жанров
            genresDropdown.innerHTML = genres.map(genre => 
                `<a href="#" class="genre-item" data-genre="${genre.name}" onclick="filterByGenre('${genre.name}'); return false;">
                    ${genre.name}
                </a>`
            ).join('');
        } else {
            genresDropdown.innerHTML = '<div class="dropdown-loading">Жанры недоступны</div>';
        }
    } catch (error) {
        console.error('❌ Error loading genres:', error);
        const genresDropdown = document.getElementById('genresDropdown');
        if (genresDropdown) {
            genresDropdown.innerHTML = '<div class="dropdown-loading">Ошибка загрузки</div>';
        }
    }
}

// Filter movies by genre
async function filterByGenre(genreName) {
    console.log(`🎭 Filtering by genre: ${genreName}`);
    
    // Обновляем активную вкладку
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Reset pagination
    currentPage = 1;
    currentCategory = 'all';
    hasMorePages = true;
    totalMoviesLoaded = 0;
    
    // Clear current movies
    moviesGrid.innerHTML = '';
    showLoading(true);
    
    try {
        // Проверяем, есть ли индекс для быстрой фильтрации
        const stats = movieAPI.getSearchStats();
        
        if (stats.indexSize > 0) {
            // БЫСТРАЯ ФИЛЬТРАЦИЯ через индекс
            console.log('⚡ Using index for fast genre filtering...');
            
            const allMoviesFromIndex = movieAPI.getAllMoviesFromIndex();
            const filteredMovies = allMoviesFromIndex.filter(m => 
                m.genre && Array.isArray(m.genre) && m.genre.includes(genreName)
            );
            
            console.log(`✅ Found ${filteredMovies.length} movies in genre: ${genreName} (from index)`);
            
            if (filteredMovies.length > 0) {
                // Показываем первые 100
                displayMovies(filteredMovies.slice(0, 100), false);
                totalMoviesLoaded = filteredMovies.length;
            } else {
                moviesGrid.innerHTML = `<div class="no-results"><h3>Ничего не найдено</h3><p>В жанре "${genreName}" пока нет фильмов</p></div>`;
            }
        } else {
            // МЕДЛЕННАЯ ФИЛЬТРАЦИЯ через API (только первые 10 страниц)
            console.log('🔄 Using API for genre filtering (limited to 10 pages)...');
            
            let allMovies = [];
            const limit = 100;
            const maxPages = 10; // Ограничиваем 10 страницами для скорости
            
            for (let page = 1; page <= maxPages; page++) {
                const response = await movieAPI.getPageWithCache(page, limit, {});
                
                if (response && response.data && Array.isArray(response.data)) {
                    const movies = response.data.filter(m => 
                        m.genre && Array.isArray(m.genre) && m.genre.includes(genreName)
                    );
                    
                    allMovies = allMovies.concat(movies);
                    
                    // Если набрали достаточно, останавливаемся
                    if (allMovies.length >= 50) break;
                    
                    if (response.data.length < limit) break;
                } else {
                    break;
                }
            }
            
            console.log(`✅ Found ${allMovies.length} movies in genre: ${genreName}`);
            
            if (allMovies.length > 0) {
                displayMovies(allMovies, false);
                totalMoviesLoaded = allMovies.length;
            } else {
                moviesGrid.innerHTML = `<div class="no-results"><h3>Ничего не найдено</h3><p>В жанре "${genreName}" пока нет фильмов</p></div>`;
            }
        }
        
    } catch (error) {
        console.error('❌ Error filtering by genre:', error);
        showError('Ошибка при фильтрации по жанру');
    } finally {
        showLoading(false);
    }
}

// Make filterByGenre global
window.filterByGenre = filterByGenre;

// Show popular movies (sorted by rating)
async function showPopularMovies() {
    console.log('⭐ Loading popular movies...');
    
    // Обновляем активную вкладку
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Reset pagination
    currentPage = 1;
    currentCategory = 'all';
    hasMorePages = false;
    totalMoviesLoaded = 0;
    
    // Clear current movies
    moviesGrid.innerHTML = '';
    showLoading(true);
    
    try {
        // Проверяем, есть ли индекс для быстрой сортировки
        const stats = movieAPI.getSearchStats();
        
        if (stats.indexSize > 0) {
            // БЫСТРАЯ СОРТИРОВКА через индекс
            console.log('⚡ Using index for fast popular movies...');
            
            const allMoviesFromIndex = movieAPI.getAllMoviesFromIndex();
            
            // Сортируем по рейтингу (KP или IMDB)
            const sortedMovies = allMoviesFromIndex
                .filter(m => {
                    const rating = parseFloat(m.kp_rating) || parseFloat(m.imdb_rating) || 0;
                    return rating >= 7.0; // Только фильмы с рейтингом 7+
                })
                .sort((a, b) => {
                    const ratingA = parseFloat(a.kp_rating) || parseFloat(a.imdb_rating) || 0;
                    const ratingB = parseFloat(b.kp_rating) || parseFloat(b.imdb_rating) || 0;
                    return ratingB - ratingA; // От большего к меньшему
                });
            
            console.log(`✅ Found ${sortedMovies.length} popular movies (rating 7.0+)`);
            
            if (sortedMovies.length > 0) {
                // Показываем первые 100
                displayMovies(sortedMovies.slice(0, 100), false);
                totalMoviesLoaded = sortedMovies.length;
            } else {
                moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3><p>Популярные фильмы не найдены</p></div>';
            }
        } else {
            // МЕДЛЕННАЯ СОРТИРОВКА через API
            console.log('🔄 Using API for popular movies...');
            
            let allMovies = [];
            const limit = 100;
            const maxPages = 20;
            
            for (let page = 1; page <= maxPages; page++) {
                const response = await movieAPI.getPageWithCache(page, limit, {});
                
                if (response && response.data && Array.isArray(response.data)) {
                    allMovies = allMovies.concat(response.data);
                    
                    if (response.data.length < limit) break;
                } else {
                    break;
                }
            }
            
            // Сортируем по рейтингу
            const sortedMovies = allMovies
                .filter(m => {
                    const rating = parseFloat(m.kp_rating) || parseFloat(m.imdb_rating) || 0;
                    return rating >= 7.0;
                })
                .sort((a, b) => {
                    const ratingA = parseFloat(a.kp_rating) || parseFloat(a.imdb_rating) || 0;
                    const ratingB = parseFloat(b.kp_rating) || parseFloat(b.imdb_rating) || 0;
                    return ratingB - ratingA;
                });
            
            console.log(`✅ Found ${sortedMovies.length} popular movies`);
            
            if (sortedMovies.length > 0) {
                displayMovies(sortedMovies.slice(0, 100), false);
                totalMoviesLoaded = sortedMovies.length;
            } else {
                moviesGrid.innerHTML = '<div class="no-results"><h3>Ничего не найдено</h3><p>Популярные фильмы не найдены</p></div>';
            }
        }
        
    } catch (error) {
        console.error('❌ Error loading popular movies:', error);
        showError('Ошибка при загрузке популярных фильмов');
    } finally {
        showLoading(false);
    }
}

// Make showPopularMovies global
window.showPopularMovies = showPopularMovies;

// Filter movies by year (with infinite scroll support)
let currentFilterYear = null;

async function filterByYear(year) {
    console.log(`📅 Filtering by year: ${year}`);
    
    // Сохраняем текущий год для пагинации
    currentFilterYear = year;
    
    // Обновляем активную вкладку
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Reset pagination
    currentPage = 1;
    currentCategory = 'year';
    hasMorePages = true;
    totalMoviesLoaded = 0;
    
    // Clear current movies
    moviesGrid.innerHTML = '';
    showLoading(true);
    
    try {
        await loadMoviesByYear(year, false);
    } catch (error) {
        console.error('❌ Error filtering by year:', error);
        showError('Ошибка при фильтрации по году');
    }
}

// Load movies by year with pagination
async function loadMoviesByYear(year, append = false) {
    if (isLoading) return;
    
    isLoading = true;
    if (!append) showLoading(true);
    
    try {
        // Проверяем, есть ли индекс
        const stats = movieAPI.getSearchStats();
        
        if (stats.indexSize > 0 && !append) {
            // БЫСТРАЯ ФИЛЬТРАЦИЯ через индекс (только для первой загрузки)
            console.log('⚡ Using index for fast year filtering...');
            
            const allMoviesFromIndex = movieAPI.getAllMoviesFromIndex();
            // Сравниваем как числа, так как year может быть строкой или числом
            const filteredMovies = allMoviesFromIndex.filter(m => parseInt(m.year) === parseInt(year));
            
            console.log(`✅ Found ${filteredMovies.length} movies from ${year} (from index)`);
            
            if (filteredMovies.length > 0) {
                displayMovies(filteredMovies.slice(0, 50), false);
                totalMoviesLoaded = filteredMovies.length;
                hasMorePages = filteredMovies.length > 50;
            } else {
                moviesGrid.innerHTML = `<div class="no-results"><h3>Ничего не найдено</h3><p>В ${year} году нет фильмов</p></div>`;
                hasMorePages = false;
            }
        } else {
            // ЗАГРУЗКА через API с пагинацией
            console.log(`🔄 Loading movies from ${year}, page: ${currentPage}`);
            
            const limit = 100;
            const response = await movieAPI.getPageWithCache(currentPage, limit, {});
            
            if (response && response.data && Array.isArray(response.data)) {
                // Сравниваем как числа
                const movies = response.data.filter(m => parseInt(m.year) === parseInt(year));
                
                console.log(`✅ Found ${movies.length} movies from ${year} on page ${currentPage}`);
                
                if (movies.length > 0) {
                    displayMovies(movies, append);
                    totalMoviesLoaded += movies.length;
                }
                
                // Проверяем, есть ли ещё страницы
                hasMorePages = response.data.length >= limit;
            } else {
                hasMorePages = false;
            }
        }
        
    } catch (error) {
        console.error('❌ Error loading movies by year:', error);
        showError('Ошибка при загрузке фильмов');
        hasMorePages = false;
    } finally {
        isLoading = false;
        showLoading(false);
        updateLoadMoreButton();
    }
}

// Make filterByYear global
window.filterByYear = filterByYear;

// Global functions
window.searchMovies = searchMovies;
window.loadMoreMovies = loadMoreMovies;
window.handleImageError = handleImageError;
window.clearSearchCache = clearSearchCache;
window.getSearchStats = getSearchStats;
window.stopIndexBuilding = stopIndexBuilding;
window.testSearchAPI = testSearchAPI;
