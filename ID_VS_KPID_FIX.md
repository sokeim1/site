# 🔧 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: id vs kp_id

## ❌ Проблема

При загрузке фильма "Симпсоны" (id=737587) плеер показывал 404 ошибку:
```
vibix.org/api/v1/publisher/videos/kp/737587:1 Failed to load resource: 404 (Not Found)
737587:1 Failed to load resource: 404 (Not Found)
```

**Причина:** Код использовал `id` из API `/publisher/videos/links` как `kp_id` (Kinopoisk ID), но это **разные вещи**:
- `id` = внутренний ID Vibix (например, 737587)
- `kp_id` = Kinopoisk ID (например, 306084)

## 📚 Структура API Vibix

### 1. Список фильмов
**Endpoint:** `GET /api/v1/publisher/videos/links`

**Возвращает:**
```json
{
  "data": [
    {
      "id": 737587,           // ❌ Внутренний ID Vibix (НЕ kp_id!)
      "name": "Симпсоны",
      "kp_id": 306084,        // ✅ Настоящий Kinopoisk ID
      "type": "serial",
      "poster_url": "...",
      ...
    }
  ]
}
```

**Проблема:** Поле `kp_id` может отсутствовать в списке!

### 2. Детальные данные по внутреннему ID
**Endpoint:** `GET /api/v1/publisher/videos/{id}`

**Возвращает:**
```json
{
  "id": 737587,
  "name": "Симпсоны",
  "kp_id": 306084,           // ✅ Настоящий kp_id всегда есть!
  "imdb_id": "tt0096697",
  "iframe_url": "...",
  ...
}
```

### 3. Детальные данные по Kinopoisk ID
**Endpoint:** `GET /api/v1/publisher/videos/kp/{kpId}`

**Параметр:** `kpId` = Kinopoisk ID (не внутренний ID!)

## ✅ Решение

### 1. Добавлен новый метод API

**Файл:** `js/api.js`

```javascript
// Get movie by internal Vibix ID
async getMovieById(id) {
    const endpoint = `/publisher/videos/${id}`;
    return await this.makeRequest(endpoint);
}
```

### 2. Изменена логика запросов

**Файл:** `js/movie-details.js` → `loadDetailedDataInBackground()`

**БЫЛО:**
```javascript
// Использовали id как kp_id ❌
const kpIdToUse = movie.kp_id || movie.id;
if (kpIdToUse) {
    movieAPI.getMovieByKpId(kpIdToUse); // 404 если id != kp_id
}
```

**СТАЛО:**
```javascript
// Запрос 1: По внутреннему ID Vibix (если нет kp_id)
if (movie.id && !movie.kp_id) {
    movieAPI.getMovieById(movie.id)  // ✅ Получаем настоящий kp_id
        .then(data => ({ source: 'id', data }));
}

// Запрос 2: По kp_id (если есть)
if (movie.kp_id) {
    movieAPI.getMovieByKpId(movie.kp_id);
}
```

### 3. Убрано использование id как kp_id

**Файл:** `js/movie-details.js` → `setupPlayerButtons()`

**БЫЛО:**
```javascript
if (movie.kp_id) {
    playerUrl = `https://vibix.org/embed/kp/${movie.kp_id}`;
}
else if (movie.id) {
    playerUrl = `https://vibix.org/embed/kp/${movie.id}`; // ❌ 404!
}
```

**СТАЛО:**
```javascript
// ПРИОРИТЕТ 1: kp_id (настоящий Kinopoisk ID)
if (movie.kp_id) {
    playerUrl = `https://vibix.org/embed/kp/${movie.kp_id}`; // ✅
}
// ПРИОРИТЕТ 2: imdb_id
else if (movie.imdb_id) {
    playerUrl = `https://vibix.org/embed/imdb/${movie.imdb_id}`;
}
// Fallback: iframe_url
else if (movie.iframe_url) {
    playerUrl = movie.iframe_url;
}
```

### 4. Для сериалов: загрузка данных с настоящим kp_id

```javascript
// ТЕПЕРЬ загружаем данные сериала с настоящим kp_id
if (movie.type === 'serial' && currentMovie.kp_id) {
    console.log('🔄 Loading serial data with real kp_id:', currentMovie.kp_id);
    serialDataResult = await movieAPI.getSerialByKpId(currentMovie.kp_id);
}
```

## 🎯 Как это работает

### Пример: Фильм "Симпсоны"

1. **Главная страница:** Получаем список фильмов
   ```
   GET /api/v1/publisher/videos/links
   → id: 737587, name: "Симпсоны", kp_id: null (может отсутствовать)
   ```

2. **Страница деталей:** Запрашиваем детальные данные
   ```
   GET /api/v1/publisher/videos/737587
   → id: 737587, kp_id: 306084, imdb_id: "tt0096697"
   ```

3. **Создание URL плеера:**
   ```javascript
   playerUrl = `https://vibix.org/embed/kp/306084`  // ✅ Работает!
   ```

4. **Для сериала:** Загружаем сезоны и серии
   ```
   GET /api/v1/serials/kp/306084
   → seasons: [...], series: [...]
   ```

## 📊 Логи для проверки

**Правильные логи:**
```
🧹 Clearing old cache (v3: fixed id vs kp_id)...
⚡ Starting optimized movie load...
✅ Basic info displayed in 1ms
🎬 This is a SERIAL, loading detailed data to get correct player URL...
🔄 Loading detailed data in background...
✅ Got detailed data from id
🔄 Loading serial data with real kp_id: 306084
✅ Created Vibix URL from kp_id for serial: https://vibix.org/embed/kp/306084
🎬 Final player URL: https://vibix.org/embed/kp/306084
✅ Player loaded instantly!
```

**Неправильные логи (старая версия):**
```
❌ Created Vibix URL from id (as kp_id): https://vibix.org/embed/kp/737587
vibix.org/api/v1/publisher/videos/kp/737587:1 404 (Not Found)
737587:1 Failed to load resource: 404
```

## ✅ Результат

- ✅ Плеер загружается с правильным `kp_id`
- ✅ Нет 404 ошибок
- ✅ Работает для всех фильмов и сериалов
- ✅ Правильная загрузка данных сериалов (сезоны/серии)
- ✅ Кэш очищен автоматически (версия v3)

## 🔧 Файлы изменены

1. **js/api.js**
   - Добавлен метод `getMovieById(id)`

2. **js/movie-details.js**
   - Изменена логика запросов в `loadDetailedDataInBackground()`
   - Убрано использование `id` как `kp_id` в `setupPlayerButtons()`
   - Добавлена загрузка данных сериала с настоящим `kp_id`
   - Обновлена версия кэша до v3

## 🎉 Готово!

Теперь плеер работает правильно для всех фильмов и сериалов, используя настоящий Kinopoisk ID вместо внутреннего ID Vibix.
