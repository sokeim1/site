// Скрипт для построения индекса фильмов
// Запуск: node build-index.js

const fs = require('fs');
const https = require('https');

const API_CONFIG = {
    baseUrl: 'https://vibix.org/api/v1',
    apiKey: 'K5S0n92g87qeScnSrtqxOEpx4SswFFPV1sv5C68465469908',
    headers: {
        'Authorization': 'Bearer K5S0n92g87qeScnSrtqxOEpx4SswFFPV1sv5C68465469908',
        'Content-Type': 'application/json'
    }
};

// Функция для HTTP запроса
function makeRequest(url) {
    return new Promise((resolve, reject) => {
        const options = {
            headers: API_CONFIG.headers
        };

        https.get(url, options, (res) => {
            let data = '';

            res.on('data', (chunk) => {
                data += chunk;
            });

            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (error) {
                    reject(error);
                }
            });
        }).on('error', (error) => {
            reject(error);
        });
    });
}

// Функция для загрузки страницы с повторными попытками
async function loadPage(page, limit = 100, retries = 2) {
    const url = `${API_CONFIG.baseUrl}/publisher/videos/links?page=${page}&limit=${limit}`;
    
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            if (attempt === 0) {
                console.log(`📄 Loading page ${page}...`);
            } else {
                console.log(`🔄 Retry ${attempt}/${retries} for page ${page}...`);
            }
            
            const response = await makeRequest(url);
            
            // Проверяем, что ответ валидный
            if (response && response.data && Array.isArray(response.data)) {
                return response.data;
            }
            
            return [];
        } catch (error) {
            if (attempt === retries) {
                // Только логируем ошибку после всех попыток
                if (!error.message.includes('<!DOCTYPE')) {
                    console.error(`❌ Error loading page ${page} after ${retries} retries:`, error.message);
                }
                return [];
            }
            
            // Небольшая пауза перед повторной попыткой
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }
    
    return [];
}

// Основная функция построения индекса
async function buildIndex() {
    console.log('🏗️  BUILDING MOVIE INDEX...\n');
    
    const startTime = Date.now();
    const moviesIndex = new Map();
    let successfulPages = 0;
    let failedPages = 0;
    let emptyPages = 0;
    
    // ФАЗА 1: Загружаем первые 200 страниц (где реально есть данные)
    console.log('🚀 PHASE 1: Loading first 200 pages (all available movies)...');
    const phase1Pages = 200;
    const batchSize = 20;
    
    for (let page = 1; page <= phase1Pages; page += batchSize) {
        const promises = [];
        const endPage = Math.min(page + batchSize - 1, phase1Pages);
        
        for (let p = page; p <= endPage; p++) {
            promises.push(loadPage(p, 100));
        }
        
        try {
            const results = await Promise.all(promises);
            
            results.forEach(movies => {
                if (movies.length === 0) {
                    emptyPages++;
                } else {
                    successfulPages++;
                    movies.forEach(movie => {
                        if (movie && movie.id) {
                            moviesIndex.set(movie.id, movie);
                        }
                    });
                }
            });
            
            const progress = Math.round((page / phase1Pages) * 100);
            console.log(`📊 Progress: ${progress}% (${moviesIndex.size} movies indexed, ${successfulPages} successful, ${emptyPages} empty)`);
            
            // Небольшая пауза между батчами
            await new Promise(resolve => setTimeout(resolve, 100));
            
        } catch (error) {
            console.error(`❌ Error in batch ${page}-${endPage}:`, error.message);
        }
    }
    
    console.log(`\n✅ Indexing complete: ${moviesIndex.size} movies indexed from ${successfulPages} pages`);
    
    // Сохраняем индекс в файл
    console.log('\n💾 Saving index to file...');
    
    const indexData = {
        timestamp: Date.now(),
        version: 3, // v3: добавлены kp_id, imdb_id, iframe_url
        totalMovies: moviesIndex.size,
        moviesIndex: Array.from(moviesIndex.entries())
    };
    
    const jsonData = JSON.stringify(indexData);
    const sizeInMB = (jsonData.length / (1024 * 1024)).toFixed(2);
    
    // Сохраняем в JSON файл
    fs.writeFileSync('movies-index.json', jsonData);
    console.log(`✅ Index saved to movies-index.json (${sizeInMB} MB)`);
    
    // Также создаем минифицированную версию для localStorage
    const minifiedData = {
        timestamp: Date.now(),
        version: 3, // v3: добавлены kp_id, imdb_id, iframe_url
        moviesIndex: Array.from(moviesIndex.entries()).map(([id, movie]) => [
            id,
            {
                id: movie.id,
                name_rus: movie.name_rus,
                name_eng: movie.name_eng,
                name: movie.name,
                name_original: movie.name_original,
                year: movie.year,
                kp_id: movie.kp_id,           // ✅ Добавлено!
                imdb_id: movie.imdb_id,       // ✅ Добавлено!
                kp_rating: movie.kp_rating,
                imdb_rating: movie.imdb_rating,
                poster_url: movie.poster_url,
                backdrop_url: movie.backdrop_url,
                iframe_url: movie.iframe_url, // ✅ Добавлено!
                type: movie.type,
                description_short: movie.description_short,
                quality: movie.quality,       // ✅ Добавлено!
                genre: movie.genre,           // ✅ Добавлено!
                country: movie.country        // ✅ Добавлено!
            }
        ])
    };
    
    const minifiedJson = JSON.stringify(minifiedData);
    const minifiedSizeMB = (minifiedJson.length / (1024 * 1024)).toFixed(2);
    
    fs.writeFileSync('movies-index-minified.json', minifiedJson);
    console.log(`✅ Minified index saved to movies-index-minified.json (${minifiedSizeMB} MB)`);
    
    // Создаем JavaScript файл для прямой загрузки
    const jsContent = `// Auto-generated movie index
// Generated: ${new Date().toISOString()}
// Total movies: ${moviesIndex.size}

window.PREBUILT_MOVIE_INDEX = ${minifiedJson};

console.log('✅ Prebuilt index loaded: ' + window.PREBUILT_MOVIE_INDEX.moviesIndex.length + ' movies');
`;
    
    fs.writeFileSync('js/prebuilt-index.js', jsContent);
    console.log(`✅ JavaScript index saved to js/prebuilt-index.js`);
    
    const totalTime = ((Date.now() - startTime) / 1000).toFixed(2);
    
    console.log('\n' + '='.repeat(60));
    console.log('🎉 INDEX BUILD COMPLETE!');
    console.log('='.repeat(60));
    console.log(`📊 Total movies indexed: ${moviesIndex.size}`);
    console.log(`⏱️  Total time: ${totalTime} seconds`);
    console.log(`📄 Pages statistics:`);
    console.log(`   - Successful: ${successfulPages} pages`);
    console.log(`   - Empty/Failed: ${emptyPages} pages`);
    console.log(`   - Success rate: ${((successfulPages / (successfulPages + emptyPages)) * 100).toFixed(1)}%`);
    console.log(`💾 Files created:`);
    console.log(`   - movies-index.json (${sizeInMB} MB)`);
    console.log(`   - movies-index-minified.json (${minifiedSizeMB} MB)`);
    console.log(`   - js/prebuilt-index.js (${minifiedSizeMB} MB)`);
    console.log('\n📝 Next steps:');
    console.log('   1. Add <script src="js/prebuilt-index.js"></script> to your HTML');
    console.log('   2. Index will be automatically loaded on page load');
    console.log('   3. Search will be INSTANT! ⚡');
    console.log('='.repeat(60));
}

// Генерация умной выборки страниц
function generateSmartSample(startPage, endPage, sampleSize) {
    const totalRange = endPage - startPage + 1;
    const step = Math.floor(totalRange / sampleSize);
    const pages = [];
    
    // Равномерное распределение
    for (let i = 0; i < sampleSize; i++) {
        const page = startPage + (i * step);
        if (page <= endPage) {
            pages.push(page);
        }
    }
    
    // Добавляем случайные страницы (20%)
    const randomPages = Math.floor(sampleSize * 0.2);
    for (let i = 0; i < randomPages; i++) {
        const randomPage = startPage + Math.floor(Math.random() * totalRange);
        if (!pages.includes(randomPage)) {
            pages.push(randomPage);
        }
    }
    
    return pages.sort((a, b) => a - b);
}

// Запуск построения индекса
buildIndex().catch(error => {
    console.error('❌ Fatal error:', error);
    process.exit(1);
});
