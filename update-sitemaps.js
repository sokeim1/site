const fs = require('fs');
const path = require('path');

// Старый и новый домены
const OLD_DOMAIN = 'kinohdpremium.netlify.app';
const NEW_DOMAIN = 'kinohd-premium.vercel.app';

// Список файлов для обновления
const files = [
    'sitemap.xml',
    'sitemap-index.xml',
    'sitemap-movies-1.xml',
    'sitemap-movies-2.xml',
    'sitemap-movies-3.xml'
];

console.log('🔄 Обновление sitemap файлов...\n');

files.forEach(filename => {
    const filepath = path.join(__dirname, filename);
    
    if (!fs.existsSync(filepath)) {
        console.log(`⚠️  Файл не найден: ${filename}`);
        return;
    }
    
    try {
        // Читаем файл
        let content = fs.readFileSync(filepath, 'utf8');
        
        // Удаляем Git конфликты (все варианты)
        content = content.replace(/<<<<<<< HEAD\r?\n/g, '');
        content = content.replace(/=======\r?\n/g, '');
        content = content.replace(/>>>>>>> [^\r\n]+\r?\n/g, '');
        
        // Удаляем дублирующиеся заголовки xmlns после конфликтов
        content = content.replace(
            /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9"\s+xmlns:image="http:\/\/www\.google\.com\/schemas\/sitemap-image\/1\.1">\s*<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/g,
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
        );
        
        // Добавляем xmlns:image к urlset без него, если в файле используются image: теги
        if (content.includes('<image:image>') || content.includes('<image:loc>')) {
            content = content.replace(
                /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">(?!\s*xmlns:image)/g,
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            );
        }
        
        // Заменяем старый домен на новый
        const oldCount = (content.match(new RegExp(OLD_DOMAIN, 'g')) || []).length;
        content = content.replace(new RegExp(OLD_DOMAIN, 'g'), NEW_DOMAIN);
        
        // Исправляем дублирующиеся строки xmlns
        content = content.replace(
            /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9"\s+xmlns:image="http:\/\/www\.google\.com\/schemas\/sitemap-image\/1\.1">\s+<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/g,
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        );
        
        // Сохраняем файл
        fs.writeFileSync(filepath, content, 'utf8');
        
        console.log(`✅ ${filename}`);
        if (oldCount > 0) {
            console.log(`   Заменено доменов: ${oldCount}`);
        }
        
    } catch (error) {
        console.log(`❌ Ошибка при обработке ${filename}:`, error.message);
    }
});

console.log('\n✅ Готово! Все sitemap файлы обновлены.');
console.log('\n📝 Следующие шаги:');
console.log('1. Проверьте файлы');
console.log('2. Загрузите на Vercel (git push)');
console.log('3. В Google Search Console введите: sitemap-index.xml');
