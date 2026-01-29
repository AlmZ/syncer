# Yandex Music → Tidal Sync

CLI для синхронизации плейлистов из Yandex Music в Tidal.

## Установка

```bash
pip install -r requirements.txt
```

## Использование

```bash
# Первый запуск (токен сохранится)
python sync.py --yandex-token <TOKEN>

# Последующие запуски
python sync.py
```

### Опции

| Флаг | Описание |
|------|----------|
| `--yandex-token` | Токен Yandex Music |
| `--auto` | Только точные совпадения, без подтверждений |
| `--cleanup` | Удалить треки из Tidal, которых нет в Yandex |
| `--workers N` | Количество потоков поиска (по умолчанию: 5) |
| `-v, --verbose` | Подробный вывод для отладки |

## Получение токена Yandex Music

1. Открыть https://music.yandex.ru в браузере
2. DevTools → Application → Cookies
3. Скопировать значение `Session_id`

## Возможности

- Синхронизация любых плейлистов и "Мне нравится"
- Delta sync — добавляет только новые треки
- Fuzzy matching для поиска треков с разным написанием
- Автоматические лайки в Tidal для избранного
- Удаление треков, удалённых из Yandex
