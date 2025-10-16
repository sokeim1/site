// API Configuration
const API_CONFIG = {
    baseUrl: 'https://vibix.org/api/v1',
    apiKey: 'K5S0n92g87qeScnSrtqxOEpx4SswFFPV1sv5C68465469908',
    headers: {
        'Authorization': 'Bearer K5S0n92g87qeScnSrtqxOEpx4SswFFPV1sv5C68465469908',
        'Content-Type': 'application/json'
    }
};

// API Service Class
class MovieAPI {
    constructor() {
        this.baseUrl = API_CONFIG.baseUrl;
        this.headers = API_CONFIG.headers;
        
        // Кэш для поиска
        this.searchCache = new Map();
        this.moviesIndex = new Map(); // Индекс фильмов для быстрого поиска
        this.isIndexBuilding = false;
        this.indexProgress = 0;
        this.totalPages = 20000; // Полная база данных
        
        // Кэш страниц
        this.pagesCache = new Map();
        this.maxCacheSize = 1000; // Максимум 1000 страниц в кэше
        
        // Статистика поиска
        this.searchStats = {
            totalSearches: 0,
            cacheHits: 0,
            avgSearchTime: 0
        };
        
        // ЛОКАЛЬНОЕ ХРАНИЛИЩЕ для кэширования базы данных
        this.dbCacheKey = 'cinehub_movies_db_v2';
        this.dbCacheExpiry = 24 * 60 * 60 * 1000; // 24 часа в миллисекундах
        
        // Загружаем предварительно построенный индекс или кэшированную базу
        // НЕ строим индекс автоматически - только загружаем если существует
        this.loadPrebuiltIndex() || this.loadCachedDatabase();
        
        // Автоматическое построение индекса отключено
        // Используйте node build-index.js для построения индекса
    }

    // Generic API request method (с минимальным логированием)
    async makeRequest(endpoint, options = {}) {
        try {
            const url = `${this.baseUrl}${endpoint}`;
            // Логируем только при отладке
            if (window.DEBUG_API) {
                console.log('Making API request to:', url);
            }
            
            const response = await fetch(url, {
                headers: this.headers,
                ...options
            });

            if (!response.ok) {
                const errorText = await response.text();
                console.error('API Error Response:', errorText);
                throw new Error(`HTTP error! status: ${response.status} - ${errorText}`);
            }

            const data = await response.json();
            
            // Логируем только при отладке
            if (window.DEBUG_API) {
                console.log('API Response data:', data);
            }
            
            return data;
        } catch (error) {
            console.error('API Request Error:', error);
            throw error;
        }
    }

    // Get list of movies/serials with pagination
    async getMoviesList(params = {}) {
        const queryParams = new URLSearchParams();
        
        // Add parameters to query string
        Object.keys(params).forEach(key => {
            if (params[key] !== undefined && params[key] !== null) {
                if (Array.isArray(params[key])) {
                    params[key].forEach(value => {
                        queryParams.append(`${key}[]`, value);
                    });
                } else {
                    queryParams.append(key, params[key]);
                }
            }
        });

        const endpoint = `/publisher/videos/links?${queryParams.toString()}`;
        return await this.makeRequest(endpoint);
    }

    // Get movie by internal Vibix ID
    // NOTE: This endpoint may not exist in API, keeping for compatibility
    async getMovieById(id) {
        // Try to get by id, but this might fail
        try {
            const endpoint = `/publisher/videos/${id}`;
            return await this.makeRequest(endpoint);
        } catch (error) {
            console.warn(`⚠️ Failed to get movie by id ${id}, endpoint may not exist`);
            throw error;
        }
    }

    // Get movie by Kinopoisk ID
    async getMovieByKpId(kpId) {
        const endpoint = `/publisher/videos/kp/${kpId}`;
        return await this.makeRequest(endpoint);
    }

    // Get movie by IMDB ID
    async getMovieByImdbId(imdbId) {
        const endpoint = `/publisher/videos/imdb/${imdbId}`;
        return await this.makeRequest(endpoint);
    }

    // Get list of Kinopoisk IDs
    async getKpIds(params = {}) {
        const queryParams = new URLSearchParams();
        
        Object.keys(params).forEach(key => {
            if (params[key] !== undefined && params[key] !== null) {
                if (Array.isArray(params[key])) {
                    params[key].forEach(value => {
                        queryParams.append(`${key}[]`, value);
                    });
                } else {
                    queryParams.append(key, params[key]);
                }
            }
        });

        const endpoint = `/publisher/videos/get_kpids${queryParams.toString() ? '?' + queryParams.toString() : ''}`;
        return await this.makeRequest(endpoint);
    }

    // Get categories
    async getCategories() {
        const endpoint = '/publisher/videos/categories';
        return await this.makeRequest(endpoint);
    }

    // Get genres
    async getGenres() {
        const endpoint = '/publisher/videos/genres';
        return await this.makeRequest(endpoint);
    }

    // Get countries
    async getCountries() {
        const endpoint = '/publisher/videos/countries';
        return await this.makeRequest(endpoint);
    }

    // Get tags
    async getTags() {
        const endpoint = '/publisher/videos/tags';
        return await this.makeRequest(endpoint);
    }

    // Get voiceovers
    async getVoiceovers() {
        const endpoint = '/publisher/videos/voiceovers';
        return await this.makeRequest(endpoint);
    }

    // Get serial seasons and episodes by Kinopoisk ID
    async getSerialByKpId(kpId) {
        const endpoint = `/serials/kp/${kpId}`;
        return await this.makeRequest(endpoint);
    }

    // Get serial seasons and episodes by IMDB ID
    async getSerialByImdbId(imdbId) {
        const endpoint = `/serials/imdb/${imdbId}`;
        return await this.makeRequest(endpoint);
    }

    // Helper method to filter movies by search query (УЛУЧШЕННЫЙ АЛГОРИТМ С ПОИСКОМ ПО СЛОВАМ)
    filterMoviesByQuery(movies, searchQuery) {
        const normalizeText = (text) => {
            return (text || '')
                .toLowerCase()
                .replace(/ё/g, 'е')
                // Удаляем ВСЕ знаки препинания (двоеточия, запятые, тире и т.д.)
                .replace(/[^\wа-яa-z0-9\s]/gi, ' ')
                .replace(/\s+/g, ' ')
                .trim();
        };

        const q = normalizeText(searchQuery);
        
        if (!q) {
            return movies; // Если запрос пустой, возвращаем все фильмы
        }
        
        // Разбиваем запрос на слова для более гибкого поиска
        const searchWords = q.split(' ').filter(word => word.length > 1);
        
        console.log(`🔍 ENHANCED SEARCH for: "${searchQuery}" -> words: [${searchWords.join(', ')}]`);
        
        const results = movies.filter(movie => {
            // Получаем все названия фильма
            const nameRus = normalizeText(movie.name_rus || '');
            const nameEng = normalizeText(movie.name_eng || '');
            const name = normalizeText(movie.name || '');
            const nameOriginal = normalizeText(movie.name_original || '');
            
            // Объединяем все названия для поиска
            const allTitles = [nameRus, nameEng, name, nameOriginal].join(' ');
            
            // Сначала проверяем точное совпадение подстроки (приоритет)
            const exactMatch = nameRus.includes(q) || 
                              nameEng.includes(q) || 
                              name.includes(q) ||
                              nameOriginal.includes(q);
            
            if (exactMatch) {
                return true;
            }
            
            // Затем проверяем совпадение по словам (БОЛЕЕ ГИБКО)
            if (searchWords.length > 1) {
                // Для многословных запросов проверяем, что хотя бы 70% слов найдены
                const foundWords = searchWords.filter(word => allTitles.includes(word));
                const wordMatchRatio = foundWords.length / searchWords.length;
                
                if (wordMatchRatio >= 0.7) {
                    return true;
                }
            } else if (searchWords.length === 1) {
                // Для одного слова - простая проверка
                if (allTitles.includes(searchWords[0])) {
                    return true;
                }
            }
            
            // Дополнительный поиск в описании
            const description = normalizeText(movie.description || '');
            const descriptionShort = normalizeText(movie.description_short || '');
            const allDescriptions = [description, descriptionShort].join(' ');
            
            // Проверяем точное совпадение в описании
            const descriptionExactMatch = description.includes(q) || descriptionShort.includes(q);
            
            if (descriptionExactMatch) {
                return true;
            }
            
            // Проверяем совпадение по словам в описании (БОЛЕЕ ГИБКО)
            if (searchWords.length > 1) {
                const foundWordsInDesc = searchWords.filter(word => allDescriptions.includes(word));
                const descWordMatchRatio = foundWordsInDesc.length / searchWords.length;
                
                if (descWordMatchRatio >= 0.5) {
                    return true;
                }
            } else if (searchWords.length === 1) {
                if (allDescriptions.includes(searchWords[0])) {
                    return true;
                }
            }
            
            // ДОПОЛНИТЕЛЬНЫЙ ПОИСК: проверяем частичные совпадения
            for (const word of searchWords) {
                if (word.length >= 4) { // Только для слов длиннее 3 символов
                    const partialMatch = [nameRus, nameEng, name, nameOriginal].some(title => 
                        title && title.toLowerCase().includes(word)
                    );
                    if (partialMatch) {
                        return true;
                    }
                }
            }
            
            return false;
        });
        
        console.log(`🎯 Enhanced search "${searchQuery}": found ${results.length} results from ${movies.length} movies (words: [${searchWords.join(', ')}])`);
        
        if (results.length > 0) {
            console.log('📋 Sample found movies:', results.slice(0, 3).map(m => ({
                title: m.name_rus || m.name || 'Unknown',
                year: m.year
            })));
        }
        
        return results;
    }

    // Быстрый поиск с кэшированием и индексированием
    async searchMovies(query, params = {}) {
        const startTime = Date.now();
        this.searchStats.totalSearches++;
        
        console.log('🔍 API searchMovies called with:', { query, params });
        
        if (!query) {
            console.log('🔍 Empty query, returning all movies');
            return await this.getMoviesList(params);
        }

        console.log('🔍 Fast search for:', query);
        
        // Нормализуем поисковый запрос
        const searchQuery = this.normalizeSearchQuery(query);
        const cacheKey = `${searchQuery}_${JSON.stringify(params)}`;
        
        // Проверяем кэш
        if (this.searchCache.has(cacheKey)) {
            console.log('✅ Cache hit for:', searchQuery);
            this.searchStats.cacheHits++;
            return this.searchCache.get(cacheKey);
        }
        
        try {
            let results;
            
            // Приоритет: сначала индекс, потом batch search
            if (this.moviesIndex.size > 1000) {
                console.log('🚀 Using fast search index (' + this.moviesIndex.size + ' movies)');
                results = await this.searchInIndex(searchQuery, params);
            } else {
                console.log('⚡ Using optimized batch search (index not ready: ' + this.moviesIndex.size + ' movies)');
                results = await this.optimizedBatchSearch(searchQuery, params);
            }
            
            // Кэшируем результат
            this.searchCache.set(cacheKey, results);
            
            // Ограничиваем размер кэша
            if (this.searchCache.size > 100) {
                const firstKey = this.searchCache.keys().next().value;
                this.searchCache.delete(firstKey);
            }
            
            const searchTime = Date.now() - startTime;
            this.searchStats.avgSearchTime = (this.searchStats.avgSearchTime + searchTime) / 2;
            
            console.log(`🎯 Search completed in ${searchTime}ms: ${results.data.length} results`);
            console.log('📊 Search stats:', this.searchStats);
            
            return results;
            
        } catch (error) {
            console.error('❌ Search error:', error);
            throw error;
        }
    }
    
    // Попытка прямого поиска через API
    async tryDirectAPISearch(searchQuery, params = {}) {
        try {
            // Пробуем разные варианты search endpoints
            const searchEndpoints = [
                `/publisher/videos/search?q=${encodeURIComponent(searchQuery)}`,
                `/movies/search?query=${encodeURIComponent(searchQuery)}`,
                `/search?q=${encodeURIComponent(searchQuery)}`,
                `/publisher/videos/links?search=${encodeURIComponent(searchQuery)}`
            ];
            
            for (const endpoint of searchEndpoints) {
                try {
                    console.log(`🔍 Trying endpoint: ${endpoint}`);
                    const response = await this.makeRequest(endpoint);
                    
                    if (response && response.data && Array.isArray(response.data) && response.data.length > 0) {
                        console.log(`✅ Direct API search successful via ${endpoint}: ${response.data.length} results`);
                        return {
                            data: response.data,
                            meta: {
                                total: response.data.length,
                                current_page: 1,
                                last_page: 1,
                                search_method: 'direct_api'
                            }
                        };
                    }
                } catch (endpointError) {
                    console.log(`⚠️ Endpoint ${endpoint} failed:`, endpointError.message);
                    continue;
                }
            }
            
            console.log('⚠️ All direct API search endpoints failed');
            return null;
            
        } catch (error) {
            console.error('❌ Direct API search error:', error);
            return null;
        }
    }
    
    // Нормализация поискового запроса
    normalizeSearchQuery(query) {
        return query.toLowerCase().trim()
            .replace(/ё/g, 'е')
            .replace(/[^\wа-яa-z\s]/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }
    
    // РЕВОЛЮЦИОННЫЙ ПОИСК: Распределенная выборка по всей базе 20000 страниц
    async optimizedBatchSearch(searchQuery, params = {}) {
        console.log(`🔍 ULTRA SEARCH: Starting distributed search across 20K pages for "${searchQuery}"`);
        
        const totalPages = 20000; // Полная база данных
        const limit = 100;
        const targetResults = 30; // Целевое количество результатов
        const minResults = 10; // Минимум результатов перед расширением поиска
        
        let foundResults = [];
        let processedPages = 0;
        let totalProcessed = 0;
        let emptyPages = 0;
        
        // ФАЗА 1: Быстрый поиск в популярных диапазонах (первые 500 страниц)
        console.log('🚀 PHASE 1: Quick search in popular range (1-500)');
        const phase1Pages = this.generateSmartSample(1, 500, 50); // 50 страниц из первых 500
        const phase1Results = await this.searchInPages(phase1Pages, searchQuery, limit, params);
        foundResults.push(...phase1Results.results);
        processedPages += phase1Results.processed;
        totalProcessed += phase1Results.totalMovies;
        emptyPages += phase1Results.empty;
        
        console.log(`📊 Phase 1: ${foundResults.length} results from ${phase1Results.processed} pages`);
        
        // ФАЗА 2: Если мало результатов, расширяем поиск на средний диапазон (500-5000)
        if (foundResults.length < minResults) {
            console.log('🔍 PHASE 2: Expanding to medium range (500-5000)');
            const phase2Pages = this.generateSmartSample(500, 5000, 100); // 100 страниц из 500-5000
            const phase2Results = await this.searchInPages(phase2Pages, searchQuery, limit, params);
            foundResults.push(...phase2Results.results);
            processedPages += phase2Results.processed;
            totalProcessed += phase2Results.totalMovies;
            emptyPages += phase2Results.empty;
            
            console.log(`📊 Phase 2: ${foundResults.length} total results from ${processedPages} pages`);
        }
        
        // ФАЗА 3: Если все еще мало результатов, сканируем всю базу распределенной выборкой
        if (foundResults.length < minResults) {
            console.log('🌐 PHASE 3: Full database distributed search (1-20000)');
            const phase3Pages = this.generateSmartSample(1, totalPages, 200); // 200 страниц по всей базе
            const phase3Results = await this.searchInPages(phase3Pages, searchQuery, limit, params);
            foundResults.push(...phase3Results.results);
            processedPages += phase3Results.processed;
            totalProcessed += phase3Results.totalMovies;
            emptyPages += phase3Results.empty;
            
            console.log(`📊 Phase 3: ${foundResults.length} total results from ${processedPages} pages`);
        }
        
        console.log(`🎯 SEARCH COMPLETE: Found ${foundResults.length} results from ${totalProcessed} movies (${processedPages} pages, ${emptyPages} empty)`);
        
        // Показываем примеры найденных фильмов
        if (foundResults.length > 0) {
            console.log('🎬 Sample found movies:');
            foundResults.slice(0, 5).forEach((movie, i) => {
                console.log(`${i+1}. ${movie.name_rus || movie.name || 'Без названия'} (${movie.year || '?'})`);
            });
        } else {
            console.log('❌ No movies found matching the search query');
        }
        
        // Удаляем дубликаты по ID
        const uniqueResults = this.removeDuplicates(foundResults);
        
        // Сортируем по релевантности
        const sortedResults = this.sortByRelevance(uniqueResults, searchQuery);
        
        const result = {
            data: sortedResults.slice(0, 50),
            meta: {
                total: sortedResults.length,
                current_page: 1,
                last_page: Math.ceil(sortedResults.length / 20),
                search_stats: {
                    processed_pages: processedPages,
                    processed_movies: totalProcessed,
                    found_results: sortedResults.length,
                    empty_pages: emptyPages,
                    database_coverage: `${((processedPages / totalPages) * 100).toFixed(2)}%`
                }
            }
        };
        
        return result;
    }
    
    // Генерация умной выборки страниц (равномерно распределенных)
    generateSmartSample(startPage, endPage, sampleSize) {
        const totalRange = endPage - startPage + 1;
        const step = Math.floor(totalRange / sampleSize);
        const pages = [];
        
        // Равномерное распределение по диапазону
        for (let i = 0; i < sampleSize; i++) {
            const page = startPage + (i * step);
            if (page <= endPage) {
                pages.push(page);
            }
        }
        
        // Добавляем случайные страницы для лучшего покрытия
        const randomPages = Math.floor(sampleSize * 0.2); // 20% случайных
        for (let i = 0; i < randomPages; i++) {
            const randomPage = startPage + Math.floor(Math.random() * totalRange);
            if (!pages.includes(randomPage)) {
                pages.push(randomPage);
            }
        }
        
        return pages.sort((a, b) => a - b);
    }
    
    // Поиск в указанных страницах с параллельной обработкой
    async searchInPages(pages, searchQuery, limit, params) {
        const batchSize = 20; // Обрабатываем по 20 страниц одновременно
        let results = [];
        let processed = 0;
        let totalMovies = 0;
        let empty = 0;
        
        // Разбиваем на батчи
        for (let i = 0; i < pages.length; i += batchSize) {
            const batch = pages.slice(i, i + batchSize);
            const promises = batch.map(page => this.getPageWithCache(page, limit, params));
            
            try {
                const responses = await Promise.all(promises);
                
                for (const response of responses) {
                    if (response && response.data && Array.isArray(response.data)) {
                        if (response.data.length === 0) {
                            empty++;
                            continue;
                        }
                        
                        const filtered = this.filterMoviesByQuery(response.data, searchQuery);
                        results.push(...filtered);
                        totalMovies += response.data.length;
                        processed++;
                    }
                }
                
                // Маленькая пауза между батчами для стабильности
                if (i + batchSize < pages.length) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                
            } catch (error) {
                console.error('❌ Batch error:', error);
                continue;
            }
        }
        
        return {
            results,
            processed,
            totalMovies,
            empty
        };
    }
    
    // Удаление дубликатов по ID
    removeDuplicates(movies) {
        const seen = new Set();
        return movies.filter(movie => {
            if (seen.has(movie.id)) {
                return false;
            }
            seen.add(movie.id);
            return true;
        });
    }
    
    // Получение страницы с кэшированием
    async getPageWithCache(page, limit, params) {
        const cacheKey = `page_${page}_${limit}_${JSON.stringify(params)}`;
        
        if (this.pagesCache.has(cacheKey)) {
            return this.pagesCache.get(cacheKey);
        }
        
        try {
            const response = await this.getMoviesList({
                ...params,
                page: page,
                limit: limit
            });
            
            // Кэшируем страницу
            this.pagesCache.set(cacheKey, response);
            
            // Ограничиваем размер кэша страниц
            if (this.pagesCache.size > this.maxCacheSize) {
                const firstKey = this.pagesCache.keys().next().value;
                this.pagesCache.delete(firstKey);
            }
            
            return response;
        } catch (error) {
            console.error(`❌ Error loading page ${page}:`, error);
            return null;
        }
    }
    
    // Умная стратегия поиска (устаревшая, оставлена для совместимости)
    getSearchStrategy(searchQuery) {
        // Простая стратегия: только первые страницы где есть данные
        return [
            { start: 1, end: 50, priority: 'high' },
            { start: 51, end: 100, priority: 'medium' },
            { start: 101, end: 140, priority: 'low' }
        ];
    }
    
    // Поиск в индексе (если построен)
    async searchInIndex(searchQuery, params) {
        const results = [];
        
        // Нормализуем поисковый запрос и разбиваем на слова
        const normalizedQuery = searchQuery.toLowerCase()
            .replace(/ё/g, 'е')
            .replace(/[^\wа-яa-z\s]/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim();
            
        const searchWords = normalizedQuery.split(' ').filter(word => word.length > 1);
        
        console.log(`🔍 Index search for: "${searchQuery}" -> normalized: "${normalizedQuery}" -> words: [${searchWords.join(', ')}]`);
        
        // Поиск по индексу
        for (const [movieId, movieData] of this.moviesIndex) {
            if (this.matchesQuery(movieData, normalizedQuery, searchWords)) {
                results.push(movieData);
            }
            
            // Ограничиваем количество результатов
            if (results.length >= 100) break;
        }
        
        console.log(`🎯 Index search found ${results.length} results`);
        
        const sortedResults = this.sortByRelevance(results, searchQuery);
        
        return {
            data: sortedResults.slice(0, 50),
            meta: {
                total: sortedResults.length,
                current_page: 1,
                last_page: 1,
                search_method: 'index'
            }
        };
    }
    
    // Проверка соответствия запросу (УЛУЧШЕННАЯ С НОРМАЛИЗАЦИЕЙ)
    matchesQuery(movie, searchQuery, searchWords) {
        if (!movie || !searchQuery) return false;
        
        const normalizeText = (text) => {
            return (text || '')
                .toLowerCase()
                .replace(/ё/g, 'е')
                // Удаляем ВСЕ знаки препинания
                .replace(/[^\wа-яa-z0-9\s]/gi, ' ')
                .replace(/\s+/g, ' ')
                .trim();
        };
        
        const query = normalizeText(searchQuery);
        
        // Собираем ВСЕ возможные поля для поиска
        const searchableFields = [
            movie.name_rus,
            movie.name_eng, 
            movie.name,
            movie.name_original,
            movie.title,
            movie.original_title,
            movie.description,
            movie.description_short,
            movie.overview
        ];
        
        // Проверяем каждое поле с нормализацией
        for (const field of searchableFields) {
            if (field && typeof field === 'string') {
                const normalizedField = normalizeText(field);
                if (normalizedField.includes(query)) {
                    return true;
                }
            }
        }
        
        return false;
    }
    
    // Получение текста для поиска
    getSearchableText(movie) {
        const texts = [
            movie.name_rus,
            movie.name_eng,
            movie.name,
            movie.name_original,
            movie.description_short
        ];
        
        return texts
            .filter(text => text)
            .join(' ')
            .toLowerCase()
            .replace(/ё/g, 'е')
            // Удаляем ВСЕ знаки препинания
            .replace(/[^\wа-яa-z0-9\s]/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }
    
    // Сортировка по релевантности
    sortByRelevance(movies, searchQuery) {
        return movies.sort((a, b) => {
            const aText = this.getSearchableText(a);
            const bText = this.getSearchableText(b);
            
            // Точное совпадение названия
            const aExact = this.isExactTitleMatch(a, searchQuery);
            const bExact = this.isExactTitleMatch(b, searchQuery);
            
            if (aExact && !bExact) return -1;
            if (!aExact && bExact) return 1;
            
            // Начинается с запроса
            const aStarts = this.titleStartsWith(a, searchQuery);
            const bStarts = this.titleStartsWith(b, searchQuery);
            
            if (aStarts && !bStarts) return -1;
            if (!aStarts && bStarts) return 1;
            
            // По рейтингу
            const aRating = parseFloat(a.kp_rating) || parseFloat(a.imdb_rating) || 0;
            const bRating = parseFloat(b.kp_rating) || parseFloat(b.imdb_rating) || 0;
            
            return bRating - aRating;
        });
    }
    
    // Проверка точного совпадения названия
    isExactTitleMatch(movie, searchQuery) {
        const titles = [movie.name_rus, movie.name_eng, movie.name, movie.name_original]
            .filter(title => title)
            .map(title => this.normalizeSearchQuery(title));
            
        return titles.some(title => title === searchQuery);
    }
    
    // Проверка начала названия
    titleStartsWith(movie, searchQuery) {
        const titles = [movie.name_rus, movie.name_eng, movie.name, movie.name_original]
            .filter(title => title)
            .map(title => this.normalizeSearchQuery(title));
            
        return titles.some(title => title.startsWith(searchQuery));
    }
    
    // ПРОГРЕССИВНОЕ построение индекса: сначала быстро популярные, потом фоном вся база
    async buildSearchIndex() {
        if (this.isIndexBuilding) {
            console.log('🔄 Index is already being built');
            return;
        }
        
        console.log('🏗️ Building progressive search index...');
        this.isIndexBuilding = true;
        this.indexProgress = 0;
        
        const limit = 100;
        
        try {
            // ФАЗА 1: Быстрая индексация первых 500 страниц (50000 фильмов)
            console.log('🚀 Phase 1: Fast indexing first 500 pages...');
            const phase1Pages = 500;
            const phase1BatchSize = 50;
            
            for (let page = 1; page <= phase1Pages; page += phase1BatchSize) {
                const batchPromises = [];
                const endPage = Math.min(page + phase1BatchSize - 1, phase1Pages);
                
                for (let p = page; p <= endPage; p++) {
                    batchPromises.push(this.getPageWithCache(p, limit, {}));
                }
                
                const responses = await Promise.all(batchPromises);
                
                responses.forEach(response => {
                    if (response && response.data && Array.isArray(response.data)) {
                        response.data.forEach(movie => {
                            if (movie.id) {
                                this.moviesIndex.set(movie.id, movie);
                            }
                        });
                    }
                });
                
                this.indexProgress = Math.round((page / phase1Pages) * 50); // 50% прогресса
                console.log(`📊 Phase 1 progress: ${this.indexProgress}% (${this.moviesIndex.size} movies)`);
                
                // Маленькая пауза
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            
            console.log(`✅ Phase 1 complete: ${this.moviesIndex.size} movies indexed`);
            
            // СОХРАНЯЕМ промежуточный результат
            this.saveDatabaseToCache();
            
            // ФАЗА 2: Фоновая индексация остальной базы (выборочно)
            console.log('🌐 Phase 2: Background indexing of remaining database (sampling)...');
            const phase2Sample = this.generateSmartSample(501, 20000, 500); // 500 страниц из оставшихся
            
            let phase2Processed = 0;
            const phase2Total = phase2Sample.length;
            
            for (let i = 0; i < phase2Sample.length; i += 20) {
                const batch = phase2Sample.slice(i, i + 20);
                const promises = batch.map(page => this.getPageWithCache(page, limit, {}));
                
                try {
                    const responses = await Promise.all(promises);
                    
                    responses.forEach(response => {
                        if (response && response.data && Array.isArray(response.data)) {
                            response.data.forEach(movie => {
                                if (movie.id) {
                                    this.moviesIndex.set(movie.id, movie);
                                }
                            });
                        }
                    });
                    
                    phase2Processed += batch.length;
                    this.indexProgress = 50 + Math.round((phase2Processed / phase2Total) * 50);
                    
                    if (phase2Processed % 100 === 0) {
                        console.log(`📊 Phase 2 progress: ${this.indexProgress}% (${this.moviesIndex.size} movies)`);
                    }
                    
                    await new Promise(resolve => setTimeout(resolve, 100));
                    
                } catch (error) {
                    console.error('❌ Phase 2 batch error:', error);
                    continue;
                }
            }
            
            this.indexProgress = 100;
            console.log(`✅ FULL INDEX READY! ${this.moviesIndex.size} movies indexed`);
            
            // СОХРАНЯЕМ полную базу
            this.saveDatabaseToCache();
            
        } catch (error) {
            console.error('❌ Error building index:', error);
        } finally {
            this.isIndexBuilding = false;
        }
    }
    
    // Остановка построения индекса
    stopIndexBuilding() {
        this.isIndexBuilding = false;
        console.log('🚫 Search index building stopped');
    }
    
    // Получить статистику поиска
    getSearchStats() {
        return {
            ...this.searchStats,
            cacheSize: this.searchCache.size,
            pagesCacheSize: this.pagesCache.size,
            indexSize: this.moviesIndex.size,
            indexProgress: this.indexProgress,
            isIndexBuilding: this.isIndexBuilding
        };
    }
    
    // Получить все фильмы из индекса
    getAllMoviesFromIndex() {
        return Array.from(this.moviesIndex.values());
    }
    
    // Очистка кэша
    clearCache() {
        this.searchCache.clear();
        this.pagesCache.clear();
        console.log('🧹 Cache cleared');
    }
    
    // ЗАГРУЗКА предварительно построенного индекса (если существует)
    loadPrebuiltIndex() {
        try {
            if (typeof window.PREBUILT_MOVIE_INDEX !== 'undefined') {
                const data = window.PREBUILT_MOVIE_INDEX;
                
                console.log('🚀 LOADING PREBUILT INDEX...');
                
                // Восстанавливаем индекс фильмов
                this.moviesIndex = new Map(data.moviesIndex);
                this.indexProgress = 100;
                
                const ageMinutes = Math.round((Date.now() - data.timestamp) / (60 * 1000));
                
                console.log(`✅ PREBUILT INDEX LOADED: ${this.moviesIndex.size} movies!`);
                console.log(`⚡ Index age: ${ageMinutes} minutes`);
                console.log(`🎯 Search will be INSTANT!`);
                
                return true;
            }
            
            return false;
            
        } catch (error) {
            console.error('❌ Error loading prebuilt index:', error);
            return false;
        }
    }
    
    // ЗАГРУЗКА кэшированной базы данных из localStorage
    loadCachedDatabase() {
        try {
            const cached = localStorage.getItem(this.dbCacheKey);
            if (!cached) {
                console.log('📦 No cached database found');
                return false;
            }
            
            const data = JSON.parse(cached);
            const now = Date.now();
            
            // Проверяем, не истек ли кэш
            if (now - data.timestamp > this.dbCacheExpiry) {
                console.log('⏰ Cached database expired, removing...');
                localStorage.removeItem(this.dbCacheKey);
                return false;
            }
            
            // Восстанавливаем индекс фильмов
            this.moviesIndex = new Map(data.moviesIndex);
            this.indexProgress = 100;
            
            console.log(`✅ LOADED CACHED DATABASE: ${this.moviesIndex.size} movies from localStorage!`);
            console.log(`⚡ Cache age: ${Math.round((now - data.timestamp) / (60 * 1000))} minutes`);
            
            return true;
            
        } catch (error) {
            console.error('❌ Error loading cached database:', error);
            localStorage.removeItem(this.dbCacheKey);
            return false;
        }
    }
    
    // СОХРАНЕНИЕ базы данных в localStorage
    saveDatabaseToCache() {
        try {
            if (this.moviesIndex.size === 0) {
                console.log('⚠️ No movies to cache');
                return false;
            }
            
            const data = {
                timestamp: Date.now(),
                moviesIndex: Array.from(this.moviesIndex.entries()),
                version: 2
            };
            
            const jsonData = JSON.stringify(data);
            const sizeInMB = (jsonData.length / (1024 * 1024)).toFixed(2);
            
            // Проверяем размер (localStorage обычно ограничен 5-10MB)
            if (jsonData.length > 8 * 1024 * 1024) { // 8MB лимит
                console.warn('⚠️ Database too large for localStorage cache');
                return false;
            }
            
            localStorage.setItem(this.dbCacheKey, jsonData);
            console.log(`💾 DATABASE SAVED TO CACHE: ${this.moviesIndex.size} movies (${sizeInMB}MB)`);
            
            return true;
            
        } catch (error) {
            console.error('❌ Error saving database to cache:', error);
            return false;
        }
    }
    
    // ОЧИСТКА кэшированной базы данных
    clearDatabaseCache() {
        localStorage.removeItem(this.dbCacheKey);
        console.log('🗑️ Cached database cleared from localStorage');
    }

    // Get movies by type (movie or serial)
    async getMoviesByType(type, page = 1, limit = 20) {
        return await this.getMoviesList({
            type: type,
            page: page,
            limit: limit
        });
    }

    // Get movies by year
    async getMoviesByYear(year, page = 1, limit = 20) {
        return await this.getMoviesList({
            year: [year],
            page: page,
            limit: limit
        });
    }

    // Get movies by genre
    async getMoviesByGenre(genreIds, page = 1, limit = 20) {
        return await this.getMoviesList({
            genre: Array.isArray(genreIds) ? genreIds : [genreIds],
            page: page,
            limit: limit
        });
    }

    // Get movies by country
    async getMoviesByCountry(countryIds, page = 1, limit = 20) {
        return await this.getMoviesList({
            country: Array.isArray(countryIds) ? countryIds : [countryIds],
            page: page,
            limit: limit
        });
    }
}

// Create global API instance
const movieAPI = new MovieAPI();

// Export for use in other files
window.movieAPI = movieAPI;

// ФУНКЦИЯ ДЛЯ ТЕСТИРОВАНИЯ ПОИСКА "ИГРА В КАЛЬМАРА"
window.testSquidGame = async function() {
    console.log('🧪 TESTING SQUID GAME SEARCH...');
    
    // Тестируем разные варианты запроса
    const queries = [
        'игра в кальмара',
        'игра кальмара',
        'squid game',
        'squid',
        'кальмар'
    ];
    
    for (const query of queries) {
        console.log(`\n🔍 Testing query: "${query}"`);
        try {
            const result = await movieAPI.searchMovies(query);
            console.log(`✅ Results: ${result.data.length} movies found`);
            if (result.data.length > 0) {
                console.log('📋 Found movies:', result.data.slice(0, 5).map(m => ({
                    title: m.name_rus || m.name || 'Unknown',
                    year: m.year,
                    id: m.id
                })));
            }
        } catch (error) {
            console.error(`❌ Error:`, error);
        }
    }
    
    console.log('\n🧪 TEST COMPLETE');
};

// ФУНКЦИЯ ДЛЯ ПРОВЕРКИ КОНКРЕТНОЙ СТРАНИЦЫ
window.checkPage = async function(pageNum) {
    console.log(`📄 Checking page ${pageNum}...`);
    try {
        const result = await movieAPI.getMoviesList({ page: pageNum, limit: 100 });
        console.log(`✅ Page ${pageNum}: ${result.data.length} movies`);
        
        // Ищем "Игра в кальмара" на этой странице
        const squidGames = result.data.filter(m => {
            const title = (m.name_rus || m.name || '').toLowerCase();
            return title.includes('игра') || title.includes('кальмар') || title.includes('squid');
        });
        
        if (squidGames.length > 0) {
            console.log('🎯 FOUND SQUID GAME ON THIS PAGE:');
            squidGames.forEach(m => {
                console.log(`  - ${m.name_rus || m.name} (${m.year})`);
            });
        }
        
        return result.data;
    } catch (error) {
        console.error(`❌ Error:`, error);
    }
};

// ФУНКЦИЯ ДЛЯ БЫСТРОГО СКАНИРОВАНИЯ ПЕРВЫХ 100 СТРАНИЦ
window.scanForSquidGame = async function() {
    console.log('🔍 SCANNING FIRST 100 PAGES FOR SQUID GAME...');
    
    for (let page = 1; page <= 100; page++) {
        const movies = await window.checkPage(page);
        await new Promise(resolve => setTimeout(resolve, 100)); // Пауза между запросами
    }
    
    console.log('✅ SCAN COMPLETE');
};
