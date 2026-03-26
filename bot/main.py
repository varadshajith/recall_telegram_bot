from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)
from shared.config import settings
from bot.handlers import (
    # v1
    voice_handler,
    challenge_command,
    history_command,
    get_command,
    # v2
    brainstorm_command,
    summary_command,
    search_command,
    evolution_command,
    ideas_command,
    add_command,
    invite_callback,
    # /prompt conversation
    prompt_start,
    prompt_receive_answer,
    prompt_cancel,
    PROMPT_AWAITING_ANSWER,
)


def main():
    application = Application.builder().token(settings.telegram_bot_token).build()

    # /prompt multi-turn conversation
    prompt_conv = ConversationHandler(
        entry_points=[CommandHandler("prompt", prompt_start)],
        states={
            PROMPT_AWAITING_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_receive_answer)],
        },
        fallbacks=[CommandHandler("cancel", prompt_cancel)],
    )
    application.add_handler(prompt_conv)

    # v1 commands
    application.add_handler(CommandHandler("challenge", challenge_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("get", get_command))

    # v2 commands
    application.add_handler(CommandHandler("brainstorm", brainstorm_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("evolution", evolution_command))
    application.add_handler(CommandHandler("ideas", ideas_command))
    application.add_handler(CommandHandler("add", add_command))

    # Inline keyboard callbacks (invite accept/decline)
    application.add_handler(CallbackQueryHandler(invite_callback, pattern=r"^invite_"))

    # Voice messages
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))

    print("Recall v2 bot starting... Press Ctrl+C to stop.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    main()
