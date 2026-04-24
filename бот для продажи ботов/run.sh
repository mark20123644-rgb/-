#!/bin/bash
# Переход в директорию скрипта (работает с пробелами)
cd "$(dirname "$0")" || exit

# Флаг, нужно ли обновлять зависимости (по умолчанию false)
NEED_INSTALL=false

# Если venv нет — создаём и помечаем, что зависимости нужно установить
if [ ! -d "venv" ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv venv
    NEED_INSTALL=true
else
    echo "Виртуальное окружение уже существует."
fi

# Активируем окружение
source venv/bin/activate

# Если зависимости нужно установить (или если мы просто хотим их проверить)
if [ "$NEED_INSTALL" = true ] || [ ! -f "venv/.installed" ]; then
    if [ -f "requirements.txt" ]; then
        echo "Устанавливаю зависимости из requirements.txt..."
        pip install -r requirements.txt
        # Создаём служебный файл, чтобы при следующем запуске не переустанавливать всё заново
        touch venv/.installed
    else
        echo "Ошибка: Файл requirements.txt не найден. Запуск бота невозможен."
        exit 1
    fi
else
    echo "Зависимости уже установлены."
fi

# Запуск бота
echo "Запуск бота..."
python bot.py
