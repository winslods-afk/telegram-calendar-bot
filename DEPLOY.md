# Инструкция по деплою на GitHub

## Шаги для публикации проекта на GitHub

### 1. Создайте репозиторий на GitHub

1. Перейдите на [github.com](https://github.com)
2. Нажмите кнопку **"New"** или **"+"** → **"New repository"**
3. Заполните форму:
   - **Repository name**: `telegram-calendar-bot` (или любое другое имя)
   - **Description**: "Telegram bot for monitoring Apple Calendar events"
   - Выберите **Public** или **Private**
   - **НЕ** создавайте README, .gitignore или лицензию (они уже есть)
4. Нажмите **"Create repository"**

### 2. Подключите локальный репозиторий к GitHub

После создания репозитория GitHub покажет инструкции. Выполните следующие команды:

```bash
# Добавьте remote репозиторий (замените YOUR_USERNAME на ваш GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/telegram-calendar-bot.git

# Переименуйте ветку в main (если нужно)
git branch -M main

# Отправьте код на GitHub
git push -u origin main
```

### 3. Альтернативный способ (через SSH)

Если вы используете SSH ключи:

```bash
git remote add origin git@github.com:YOUR_USERNAME/telegram-calendar-bot.git
git branch -M main
git push -u origin main
```

### 4. Проверка

После выполнения команд перейдите на страницу вашего репозитория на GitHub и убедитесь, что все файлы загружены.

## Дополнительные команды Git

### Просмотр статуса
```bash
git status
```

### Просмотр истории коммитов
```bash
git log
```

### Добавление изменений
```bash
git add .
git commit -m "Описание изменений"
git push
```

### Просмотр удаленных репозиториев
```bash
git remote -v
```

## Важные замечания

⚠️ **НЕ коммитьте файл `.env`** - он уже добавлен в `.gitignore`

✅ **Файл `env.example`** должен быть в репозитории - это шаблон для других пользователей

## Что уже готово

- ✅ Git репозиторий инициализирован
- ✅ Все необходимые файлы добавлены
- ✅ Первый коммит создан
- ✅ `.gitignore` настроен правильно

Теперь нужно только подключить remote и запушить код!

