// Скрипт для генерації динамічного sitemap з популярними фільмами
// Запуск: node generate-sitemap.js

const fs = require('fs');

console.log('🗺️ Генерація sitemap...');

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

console.log(`📊 Додаємо ${sortedMovies.length} фільмів в sitemap`);

// Генеруємо XML
const currentDate = new Date().toISOString().split('T')[0];
const baseUrl = 'https://kinohdpremium.netlify.app';

let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
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
  
  <!-- Всі фільми з бази даних -->
`;

sortedMovies.forEach(movie => {
    const movieUrl = `${baseUrl}/movie-details.html?id=${movie.id}`;
    const title = (movie.name_rus || movie.name || movie.title || 'Фільм')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    const poster = movie.poster_url || movie.poster || '';
    
    xml += `  <url>
    <loc>${movieUrl}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
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
  </url>
`;
});

xml += `</urlset>`;

// Зберігаємо sitemap
fs.writeFileSync('sitemap.xml', xml, 'utf8');
console.log('✅ sitemap.xml створено успішно!');
console.log(`📄 Всього URL: ${sortedMovies.length + 2}`);

// Створюємо також sitemap-index для майбутнього розширення
const sitemapIndex = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>${baseUrl}/sitemap.xml</loc>
    <lastmod>${currentDate}</lastmod>
  </sitemap>
</sitemapindex>`;

fs.writeFileSync('sitemap-index.xml', sitemapIndex, 'utf8');
console.log('✅ sitemap-index.xml створено!');

console.log('\n🎉 Готово! Тепер:');
console.log('1. Закомітьте зміни: git add sitemap.xml sitemap-index.xml');
console.log('2. Запушьте: git push');
console.log('3. Відправте в Google Search Console: https://kinohdpremium.netlify.app/sitemap.xml');
