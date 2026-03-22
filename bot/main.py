import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from shared.config import settings
from bot.handlers import voice_handler, challenge_command, history_command, get_command


def main():
    # This uses the token from your .env file
    application = Application.builder().token(settings.telegram_bot_token).build()

    # Register our specialized "Waiters" for different commands
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("get", get_command))

    # Register the "Ear" for voice messages
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))

    # Start polling with 1 second interval and 30 second timeout
    # This means the bot keeps asking Telegram, "Any new messages for me?"
    print("Bot is starting... Press Ctrl+C to stop.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=30
    )


if __name__ == "__main__":
    main()
