import asyncio

from telegram import Bot, BotCommand

from shared.config import settings


async def main() -> None:
    bot = Bot(token=settings.telegram_bot_token)

    commands = [
        BotCommand("prompt", "Ask questions and generate a coding prompt"),
        BotCommand("brainstorm", "Generate feature ideas and pivots"),
        BotCommand("summary", "Weekly digest grouped by tags"),
        BotCommand("search", "Semantic search across briefs"),
        BotCommand("evolution", "Timeline of how ideas evolved"),
        BotCommand("ideas", "List briefs filtered by tag"),
        BotCommand("add", "Invite a collaborator to your session"),
        BotCommand("challenge", "Probing questions on your latest brief"),
        BotCommand("history", "Your recent briefs"),
        BotCommand("get", "View full details for a prompt id"),
        BotCommand("cancel", "Cancel the /prompt flow"),
    ]

    await bot.set_my_commands(commands)
    print("Telegram commands registered.")


if __name__ == "__main__":
    asyncio.run(main())

