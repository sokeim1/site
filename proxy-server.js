const express = require('express');
const cors = require('cors');
const fetch = require('node-fetch');
const geoip = require('geoip-lite');

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Функция для определения страны по IP
function getCountryFromIP(ip) {
    // Обработка локальных IP адресов
    if (ip === '::1' || ip === '127.0.0.1' || ip.startsWith('192.168.') || ip.startsWith('10.') || ip.startsWith('172.')) {
        return null; // Локальный IP
    }
    
    const geo = geoip.lookup(ip);
    return geo ? geo.country : null;
}

// Прокси для изображений
app.get('/proxy-image', async (req, res) => {
    try {
        const { url } = req.query;
        
        if (!url) {
            return res.status(400).json({ error: 'URL parameter is required' });
        }

        // Получаем IP пользователя
        const clientIP = req.headers['x-forwarded-for'] || 
                        req.connection.remoteAddress || 
                        req.socket.remoteAddress ||
                        (req.connection.socket ? req.connection.socket.remoteAddress : null);

        console.log('Client IP:', clientIP);
        
        // Определяем страну
        const country = getCountryFromIP(clientIP);
        console.log('Detected country:', country);

        // Если пользователь из Украины или IP не определен, используем прокси
        const useProxy = country === 'UA' || !country;
        
        console.log('User country:', country, 'Use proxy:', useProxy);
        
        if (useProxy) {
            console.log('Using proxy for image:', url);
            
            // Загружаем изображение через прокси
            const response = await fetch(url, {
                timeout: 10000,
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/jpeg,image/png,image/*,*/*;q=0.8',
                    'Cache-Control': 'no-cache'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Устанавливаем правильные заголовки
            const contentType = response.headers.get('content-type') || 'image/jpeg';
            res.set('Content-Type', contentType);
            res.set('Cache-Control', 'public, max-age=7200'); // Кэшируем на 2 часа
            res.set('Access-Control-Allow-Origin', '*');
            res.set('Access-Control-Allow-Methods', 'GET');
            res.set('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');

            // Передаем изображение
            response.body.pipe(res);
        } else {
            // Для других стран тоже используем прокси для стабильности
            console.log('Using proxy for stability for country:', country);
            
            try {
                const response = await fetch(url, {
                    timeout: 8000,
                    headers: {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'image/webp,image/apng,image/jpeg,image/png,image/*,*/*;q=0.8'
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const contentType = response.headers.get('content-type') || 'image/jpeg';
                res.set('Content-Type', contentType);
                res.set('Cache-Control', 'public, max-age=3600');
                res.set('Access-Control-Allow-Origin', '*');
                
                response.body.pipe(res);
            } catch (error) {
                console.log('Proxy failed, redirecting to original URL');
                res.redirect(url);
            }
        }

    } catch (error) {
        console.error('Proxy error:', error);
        res.status(500).json({ 
            error: 'Failed to proxy image',
            details: error.message 
        });
    }
});

// Эндпоинт для проверки статуса
app.get('/status', (req, res) => {
    const clientIP = req.headers['x-forwarded-for'] || 
                    req.connection.remoteAddress || 
                    req.socket.remoteAddress ||
                    (req.connection.socket ? req.connection.socket.remoteAddress : null);
    
    const country = getCountryFromIP(clientIP);
    
    res.json({
        status: 'OK',
        ip: clientIP,
        country: country,
        useProxy: country === 'UA' || !country,
        timestamp: new Date().toISOString()
    });
});

// Запуск сервера
app.listen(PORT, () => {
    console.log(`Proxy server running on port ${PORT}`);
    console.log(`Image proxy endpoint: http://localhost:${PORT}/proxy-image?url=<IMAGE_URL>`);
    console.log(`Status endpoint: http://localhost:${PORT}/status`);
});

module.exports = app;
