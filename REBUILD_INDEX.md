# 🔄 Перестроение индекса с большим количеством фильмов

## 📊 Что изменилось

Скрипт `build-index.js` был улучшен:

### ✅ Улучшения:

1. **Больше страниц в Фазе 1**: 1000 вместо 500 (до 100,000 фильмов)
2. **Больше выборки в Фазе 2**: 1000 страниц вместо 500
3. **Фокус на рабочих страницах**: 1001-13000 (где меньше ошибок)
4. **Повторные попытки**: 2 попытки при ошибках загрузки
5. **Детальная статистика**: показывает успешные/пустые страницы

### 📈 Ожидаемый результат:

- **Было**: ~14,000 фильмов (из первых 500 страниц)
- **Будет**: ~50,000-80,000 фильмов (из 2000 страниц)
- **Время**: ~2-5 минут (вместо 50 секунд)

## 🚀 Как перестроить индекс

### Вариант 1: Двойной клик
```
Двойной клик на BUILD_INDEX.bat
```

### Вариант 2: PowerShell
```powershell
cd "C:\Users\sokeim лучший\CascadeProjects\movie-site"
node build-index.js
```

## 📊 Что вы увидите

```
🏗️  BUILDING MOVIE INDEX...

🚀 PHASE 1: Loading first 1000 pages (100,000 movies)...
📊 Progress: 10% (5000 movies indexed, 100 successful, 0 empty)
📊 Progress: 20% (10000 movies indexed, 200 successful, 0 empty)
...
✅ Phase 1 complete: 50000 movies indexed from 800 pages

🌐 PHASE 2: Sampling remaining database (pages 1001-13000)...
📊 Phase 2 Progress: 50% (70000 movies total)
...
✅ Phase 2 complete: 80000 movies indexed

💾 Saving index to file...
✅ Index saved to movies-index.json
✅ Minified index saved to movies-index-minified.json
✅ JavaScript index saved to js/prebuilt-index.js

============================================================
🎉 INDEX BUILD COMPLETE!
============================================================
📊 Total movies indexed: 80000
⏱️  Total time: 180 seconds (3 minutes)
📄 Pages statistics:
   - Successful: 1600 pages
   - Empty/Failed: 400 pages
   - Success rate: 80.0%
💾 Files created:
   - movies-index.json (450 MB)
   - movies-index-minified.json (25 MB)
   - js/prebuilt-index.js (25 MB)
============================================================
```

## ⚠️ Важно

- **Размер файла увеличится**: с 5 MB до ~25 MB
- **Время загрузки**: первая загрузка страницы будет ~2-3 секунды
- **Но поиск будет мгновенным** для 80,000+ фильмов!

## 🎯 Рекомендации

### Если нужно еще больше фильмов:

Измените в `build-index.js`:
```javascript
const phase1Pages = 1000;  // увеличьте до 2000
const phase2Sample = generateSmartSample(1001, 13000, 1000); // увеличьте 1000 до 2000
```

### Если файл слишком большой:

Уменьшите:
```javascript
const phase1Pages = 500;   // уменьшите до 500
const phase2Sample = generateSmartSample(501, 13000, 500); // уменьшите до 500
```

## 📝 После перестроения

1. Старый файл `js/prebuilt-index.js` будет заменен
2. Обновите страницу в браузере (Ctrl+F5)
3. Проверьте консоль:
   ```
   ✅ PREBUILT INDEX LOADED: 80000+ movies!
   ```

---

**Готово!** Теперь у вас будет индекс с гораздо большим количеством фильмов! 🎬
