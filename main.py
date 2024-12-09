import os
import schedule
import time
from betting_bot import BettingBot, Config

def main():
    config = Config(
        TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN'),
        TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID'),
        ODDS_API_KEY=os.getenv('ODDS_API_KEY'),
        PERPLEXITY_API_KEY=os.getenv('PERPLEXITY_API_KEY'),
        CLAUDE_API_KEY=os.getenv('CLAUDE_API_KEY')
    )
    
    bot = BettingBot(config)
    bot.run()
    
    schedule.every().day.at("08:00").do(bot.run_daily_task)
    
    while True:
        schedule.run_pending()
        time.sleep(120)

if __name__ == "__main__":
    main()
