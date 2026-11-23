"""Avvio alternativo del bot: `python bot.py` equivale a `python -m app.main`.

Utile se sul server è impostato come comando di avvio `python bot.py`.
"""

from app.main import main

if __name__ == "__main__":
    main()
