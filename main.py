import requests
import anthropic
import logging
import telegram
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import re
import time
from retry import retry
import random
import os
import sys
import schedule
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@dataclass
class Config:
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    ODDS_API_KEY: str
    PERPLEXITY_API_KEY: str
    CLAUDE_API_KEY: str
    MIN_MATCHES: int = 2
    MAX_MATCHES: int = 4
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5


@dataclass
class Match:
    home_team: str
    away_team: str
    competition: str
    region: str
    commence_time: datetime
    bookmakers: List[Dict]
    all_odds: List[Dict]
    last_prediction: str = ""


@dataclass
class Prediction:
    region: str
    competition: str
    match: str
    time: str
    prediction: str
    confidence: int
    explanation: str


class BettingBot:
    def __init__(self, config: Config):
        print("Initialisation du bot...")
        self.config = config
        self.bot = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.claude_client = anthropic.Anthropic(api_key=config.CLAUDE_API_KEY)
        self.immediate_combo_sent = False
        self.last_execution_date = None
        self.available_predictions = ["+1.5 buts", "-3.5 buts", "1X", "X2", "12"]
        print("Bot initialisé avec succès!")

    def _get_region(self, competition: str) -> str:
        regions = {
            "Premier League": "Angleterre 🏴",
            "La Liga": "Espagne 🇪🇸",
            "Bundesliga": "Allemagne 🇩🇪",
            "Serie A": "Italie 🇮🇹",
            "Ligue 1": "France 🇫🇷",
            "Champions League": "Europe 🇪🇺",
            "Europa League": "Europe 🇪🇺",
            "Conference League": "Europe 🇪🇺"
        }
        return regions.get(competition, competition)

    @retry(tries=3, delay=5, backoff=2, logger=logger)
    def fetch_matches(self) -> List[Match]:
        if self.last_execution_date == datetime.now().date():
            print("Un combo a déjà été envoyé aujourd'hui.")
            return []

        print("\n1️⃣ RÉCUPÉRATION DES MATCHS...")
        url = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
        params = {
            "apiKey": self.config.ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        }

        try:
            print("Connexion à l'API des cotes...")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            matches_data = response.json()
            print(f"✅ {len(matches_data)} matchs récupérés")

            current_time = datetime.now(timezone.utc)
            matches = []

            for match_data in matches_data:
                commence_time = datetime.fromisoformat(match_data["commence_time"].replace('Z', '+00:00'))
                time_difference = commence_time - current_time

                if 0 < time_difference.total_seconds() <= 86400:
                    match = Match(
                        home_team=match_data.get("home_team", "Unknown"),
                        away_team=match_data.get("away_team", "Unknown"),
                        competition=match_data.get("sport_title", "Unknown"),
                        region=self._get_region(match_data.get("sport_title", "")),
                        commence_time=commence_time,
                        bookmakers=match_data.get("bookmakers", []),
                        all_odds=match_data.get("bookmakers", [])
                    )
                    matches.append(match)

            print(f"Matchs dans les prochaines 24h: {len(matches)}")

            if not matches:
                print("❌ Aucun match trouvé pour les prochaines 24 heures")
                return []

            num_matches = min(len(matches), random.randint(self.config.MIN_MATCHES, self.config.MAX_MATCHES))
            selected_matches = random.sample(matches, num_matches)

            print(f"✅ Sélection de {len(selected_matches)} matchs:")
            for match in selected_matches:
                print(f"   • {match.home_team} vs {match.away_team} ({len(match.bookmakers)} bookmakers)")

            return selected_matches

        except Exception as e:
            print(f"❌ Erreur lors de la récupération des matchs: {str(e)}")
            raise

    def send_predictions(self, predictions: List[Prediction]) -> None:
        if not predictions:
            print("❌ Aucune prédiction à envoyer")
            return

        print("\n4️⃣ ENVOI DU COMBO")
        message = self._format_predictions_message(predictions)
        try:
            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            print("✅ Combo envoyé avec succès!")
            self.last_execution_date = datetime.now().date()
        except Exception as e:
            print(f"❌ Erreur: {str(e)}")
            raise

    def run(self) -> None:
        try:
            print("\n=== DÉBUT DU PROCESSUS ===")
            matches = self.fetch_matches()
            if not matches:
                return

            predictions = []
            for match in matches:
                # Ajoutez d'autres étapes ici si nécessaire.
                time.sleep(10)

            if predictions:
                self.send_predictions(predictions)
                self.immediate_combo_sent = True
                print("=== PROCESSUS TERMINÉ ===")
            else:
                print("❌ Aucune prédiction fiable")

        except Exception as e:
            print(f"❌ ERREUR: {str(e)}")


def main():
    config = Config(
        TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN'),
        TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID'),
        ODDS_API_KEY=os.getenv('ODDS_API_KEY'),
        PERPLEXITY_API_KEY=os.getenv('PERPLEXITY_API_KEY'),
        CLAUDE_API_KEY=os.getenv('CLAUDE_API_KEY')
    )

    bot = BettingBot(config)

    # Envoi du combo immédiat au démarrage
    print("=== DÉMARRAGE DU BOT ===")
    bot.run()

    # Planification quotidienne
    schedule.every().day.at("08:00").do(bot.run)

    print("=== BOT EN ATTENTE DE TÂCHES ===")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()


from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import os

def start_http_server():
    port = int(os.getenv("PORT", 8080))  # Render spécifie automatiquement le port dans la variable d'environnement PORT
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running!")

    httpd = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"🚀 HTTP server started on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    # Démarrer le bot dans un thread séparé
    bot_thread = threading.Thread(target=main, daemon=True)
    bot_thread.start()

    # Lancer le serveur HTTP
    start_http_server()

