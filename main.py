import os
import logging
import schedule
import time
from dotenv import load_dotenv
from betting_bot import BettingBot, Config

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def main():
    # Chargement des variables d'environnement
    load_dotenv()

    # Configuration du bot
    config = Config(
        TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN'),
        TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID'),
        ODDS_API_KEY=os.getenv('ODDS_API_KEY'),
        PERPLEXITY_API_KEY=os.getenv('PERPLEXITY_API_KEY'),
        CLAUDE_API_KEY=os.getenv('CLAUDE_API_KEY'),
        MIN_MATCHES=2,
        MAX_MATCHES=4
    )

    try:
        # Initialisation du bot
        logger.info("=== DÉMARRAGE DU BOT ===")
        bot = BettingBot(config)
        
        # Envoi du combo immédiat
        logger.info("Lancement du combo immédiat...")
        bot.immediate_combo_sent = False
        bot.last_execution_date = None
        bot.run()

        # Planification quotidienne
        logger.info("Configuration de la tâche quotidienne...")
        schedule.every().day.at("08:00").do(bot.run_daily_task)
        
        # Boucle principale
        logger.info("=== BOT EN ATTENTE (PROCHAIN COMBO À 8H00) ===")
        while True:
            schedule.run_pending()
            time.sleep(120)  # Vérification toutes les 2 minutes
            
    except Exception as e:
        logger.error(f"❌ Erreur principale: {str(e)}")
        logger.exception("Détails de l'erreur:")

if __name__ == "__main__":
    main()
