// Скрипт для генерації розділеного sitemap (для великої кількості фільмів)
// Розбиває на кілька файлів по 5000 URL кожен
// Запуск: node generate-sitemap-split.js

const fs = require('fs');

console.log('🗺️ Генерація розділеного sitemap...');

// Читаємо індекс фільмів
let movies = [];
try {
    const indexData = fs.readFileSync('movies-index-minified.json', 'utf8');
    const parsed = JSON.parse(indexData);
    
    // Формат: {timestamp, version, moviesIndex: [[id, movieData], ...]}
    if (parsed.moviesIndex && Array.isArray(parsed.moviesIndex)) {
        movies = parsed.moviesIndex.map(item => {
            if (Array.isArray(item) && item.length >= 2) {
                return item[1]; // Беремо об'єкт фільму
            }
            return item;
        }).filter(m => m && m.id);
    } else if (Array.isArray(parsed)) {
        movies = parsed.map(item => {
            if (Array.isArray(item) && item.length >= 2) {
                return item[1];
            }
            return item;
        }).filter(m => m && m.id);
    } else if (parsed.movies) {
        movies = parsed.movies;
    }
    
    console.log(`✅ Завантажено ${movies.length} фільмів`);
} catch (error) {
    console.error('❌ Помилка читання індексу:', error.message);
    process.exit(1);
}

// Використовуємо ВСІ фільми з бази даних
const allMovies = movies.filter(m => m && m.id); // Тільки валідні фільми з ID

// Сортуємо за рейтингом (найкращі будуть першими в sitemap)
const sortedMovies = allMovies.sort((a, b) => {
    const ratingA = parseFloat(a.kp_rating || a.kpRating || a.imdb_rating || a.imdbRating || 0);
    const ratingB = parseFloat(b.kp_rating || b.kpRating || b.imdb_rating || b.imdbRating || 0);
    return ratingB - ratingA;
});

console.log(`📊 Додаємо ${sortedMovies.length} фільмів`);

// Генеруємо XML
const currentDate = new Date().toISOString().split('T')[0];
const baseUrl = 'https://kinohdpremium.netlify.app';

// Розбиваємо на частини по 5000 URL
const URLS_PER_SITEMAP = 5000;
const chunks = [];
for (let i = 0; i < sortedMovies.length; i += URLS_PER_SITEMAP) {
    chunks.push(sortedMovies.slice(i, i + URLS_PER_SITEMAP));
}

console.log(`📦 Створюємо ${chunks.length} файлів sitemap`);

// Створюємо головний sitemap з основними сторінками
let mainSitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- Головна сторінка -->
  <url>
    <loc>${baseUrl}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <lastmod>${currentDate}</lastmod>
  </url>
  
  <!-- Сторінка пошуку -->
  <url>
    <loc>${baseUrl}/search.html</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
    <lastmod>${currentDate}</lastmod>
  </url>
</urlset>`;

fs.writeFileSync('sitemap.xml', mainSitemap, 'utf8');
console.log('✅ sitemap.xml (головний) створено');

// Створюємо окремі sitemap для фільмів
chunks.forEach((chunk, index) => {
    const sitemapNumber = index + 1;
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<<<<<<< HEAD
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
=======
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
>>>>>>> b190e62 (Fix sitemap headers)
`;

    chunk.forEach(movie => {
        const movieUrl = `${baseUrl}/movie-details.html?id=${movie.id}`;
<<<<<<< HEAD
        const title = (movie.name_rus || movie.name || movie.title || 'Фільм')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
=======
        
        // Правильне екранування для XML
        const escapeXml = (str) => {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&apos;')
                .replace(/[\x00-\x1F\x7F]/g, ''); // Видаляємо контрольні символи
        };
        
        const title = escapeXml(movie.name_rus || movie.name || movie.title || 'Фільм');
>>>>>>> b190e62 (Fix sitemap headers)
        const poster = movie.poster_url || movie.poster || '';
        
        // Визначаємо пріоритет на основі рейтингу
        const rating = parseFloat(movie.kp_rating || movie.imdb_rating || 0);
        let priority = 0.5;
        if (rating >= 8.0) priority = 0.9;
        else if (rating >= 7.0) priority = 0.8;
        else if (rating >= 6.0) priority = 0.7;
        else if (rating >= 5.0) priority = 0.6;
        
        xml += `  <url>
    <loc>${movieUrl}</loc>
    <changefreq>monthly</changefreq>
    <priority>${priority}</priority>
<<<<<<< HEAD
    <lastmod>${currentDate}</lastmod>`;
        
        // Додаємо постер якщо є
        if (poster) {
            xml += `
    <image:image>
      <image:loc>${poster}</image:loc>
      <image:title>${title}</image:title>
    </image:image>`;
        }
        
        xml += `
=======
    <lastmod>${currentDate}</lastmod>
>>>>>>> b190e62 (Fix sitemap headers)
  </url>
`;
    });

    xml += `</urlset>`;
    
    const filename = `sitemap-movies-${sitemapNumber}.xml`;
    fs.writeFileSync(filename, xml, 'utf8');
    console.log(`✅ ${filename} створено (${chunk.length} фільмів)`);
});

// Створюємо sitemap index
let sitemapIndex = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>${baseUrl}/sitemap.xml</loc>
    <lastmod>${currentDate}</lastmod>
  </sitemap>
`;

chunks.forEach((chunk, index) => {
    const sitemapNumber = index + 1;
    sitemapIndex += `  <sitemap>
    <loc>${baseUrl}/sitemap-movies-${sitemapNumber}.xml</loc>
    <lastmod>${currentDate}</lastmod>
  </sitemap>
`;
});

sitemapIndex += `</sitemapindex>`;

fs.writeFileSync('sitemap-index.xml', sitemapIndex, 'utf8');
console.log('✅ sitemap-index.xml створено!');

console.log('\n📊 Статистика:');
console.log(`- Головний sitemap: 2 URL (головна + пошук)`);
console.log(`- Sitemap з фільмами: ${chunks.length} файлів`);
console.log(`- Всього фільмів: ${sortedMovies.length}`);
console.log(`- Загальна кількість URL: ${sortedMovies.length + 2}`);

console.log('\n🎉 Готово! Тепер:');
console.log('1. Закомітьте зміни: git add sitemap*.xml');
console.log('2. Запушьте: git push');
console.log('3. Відправте в Google Search Console:');
console.log('   https://kinohdpremium.netlify.app/sitemap-index.xml');
