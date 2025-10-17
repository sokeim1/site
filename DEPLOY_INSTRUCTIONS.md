# 🚀 Инструкция по деплою на Vercel

## Быстрый деплой через Git

```bash
# 1. Добавить все изменения
git add .

# 2. Сделать коммит
git commit -m "Fix sitemap.xml"

# 3. Отправить на GitHub/Vercel
git push
```

## Или через Vercel CLI

```bash
# 1. Установить Vercel CLI (если еще не установлен)
npm install -g vercel

# 2. Задеплоить
vercel --prod
```

## После деплоя

1. Подождите 1-2 минуты пока Vercel обновит сайт
2. Проверьте: https://kinohd-premium.vercel.app/sitemap.xml
3. В Google Search Console нажмите "Повторити спробу" (Повторить попытку)
4. Или удалите старый sitemap и добавьте заново

## Проверка

Откройте в браузере:
- https://kinohd-premium.vercel.app/sitemap.xml
- https://kinohd-premium.vercel.app/robots.txt

Оба файла должны открываться без ошибок.
