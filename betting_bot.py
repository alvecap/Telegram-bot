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
import asyncio

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

from retry import retry

class BettingBot:
    def __init__(self, config: Config):
        print("Initialisation du bot...")
        self.config = config
        
        # Vérification détaillée de la clé Claude
        claude_key = config.CLAUDE_API_KEY.strip()
        print(f"Format de la clé Claude:")
        print(f"- Longueur: {len(claude_key)} caractères")
        print(f"- Début de la clé: {claude_key[:15]}...")
        print(f"- La clé commence-t-elle par 'sk-ant-': {claude_key.startswith('sk-ant-')}")
        
        try:
            self.bot = telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)
            
            # Configuration des headers
            self.claude_client = anthropic.Anthropic(
                api_key=claude_key
            )
            
            # Test avec retry
            self._test_claude_connection()
            print("✅ Connexion Claude OK")
            
        except Exception as e:
            print(f"❌ Erreur d'initialisation détaillée:")
            print(f"Type d'erreur: {type(e)}")
            print(f"Message d'erreur: {str(e)}")
            if hasattr(e, 'response'):
                print(f"Response status: {e.response.status_code}")
                print(f"Response headers: {e.response.headers}")
            raise

        self.immediate_combo_sent = False
        self.last_execution_date = None
        self.available_predictions = ["+1.5 buts", "-3.5 buts", "1X", "X2", "12"]
        print("Bot initialisé avec succès!")

    @retry(tries=5, delay=2, backoff=2, max_delay=30)
    def _test_claude_connection(self):
        print("Test de la connexion Claude (message court)...")
        test_message = self.claude_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": "test"}]
        )
        return test_message

    def _get_region(self, competition: str) -> str:
        regions = {
            "Premier League": "Angleterre 🏴󠁧󠁢󠁥󠁮󠁧󠁿",
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

    def get_match_stats(self, match: Match) -> Optional[str]:
        print(f"\n2️⃣ ANALYSE DE {match.home_team} vs {match.away_team}")
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json"
        }
        
        prompt = (
            f"Recherche approfondie sur {match.home_team} vs {match.away_team}.\n"
            "DONNÉES REQUISES:\n"
            "1. Forme (5 derniers matchs)\n"
            "2. Stats saison\n"
            "3. H2H récents\n"
            "4. Effectif et blessés\n"
            "5. Enjeu du match\n"
            "Format: Points clés uniquement."
        )
        
        try:
            print("Récupération des statistiques...")
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": "llama-3.1-sonar-large-128k-online",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800,
                    "temperature": 0.2
                },
                timeout=20
            )
            response.raise_for_status()
            stats = response.json()["choices"][0]["message"]["content"]
            print("✅ Statistiques récupérées")
            return stats
        except Exception as e:
            print(f"❌ Erreur: {str(e)}")
            return None

    def analyze_match(self, match: Match, stats: Optional[str]) -> Optional[Prediction]:
        if not stats:
            return None

        print("3️⃣ ANALYSE AVEC CLAUDE")
        try:
            odds_info = "ANALYSE DÉTAILLÉE DES COTES:\n\n"
            
            h2h_odds = []
            over_under_odds = []
            draw_no_bet_odds = []
            
            for bm in match.all_odds:
                if 'markets' in bm and bm['markets']:
                    bm_name = bm.get('title', 'Unknown')
                    for market in bm['markets']:
                        if market.get('outcomes'):
                            market_type = market.get('key', '')
                            odds = {outcome['name']: outcome['price'] for outcome in market['outcomes']}
                            
                            if 'h2h' in market_type:
                                h2h_odds.append((bm_name, odds))
                            elif 'totals' in market_type:
                                over_under_odds.append((bm_name, odds))
                            elif 'dnb' in market_type:
                                draw_no_bet_odds.append((bm_name, odds))

            if h2h_odds:
                odds_info += "COTES 1X2:\n"
                for bm_name, odds in h2h_odds:
                    odds_info += f"{bm_name}: {', '.join(f'{k}={v:.2f}' for k, v in odds.items())}\n"
                
            if over_under_odds:
                odds_info += "\nCOTES OVER/UNDER:\n"
                for bm_name, odds in over_under_odds:
                    odds_info += f"{bm_name}: {', '.join(f'{k}={v:.2f}' for k, v in odds.items())}\n"
                
            if draw_no_bet_odds:
                odds_info += "\nCOTES DNB:\n"
                for bm_name, odds in draw_no_bet_odds:
                    odds_info += f"{bm_name}: {', '.join(f'{k}={v:.2f}' for k, v in odds.items())}\n"

            prompt = (
                f"ANALYSE APPROFONDIE: {match.home_team} vs {match.away_team}\n"
                f"Compétition: {match.competition}\n\n"
                "1. DONNÉES STATISTIQUES:\n"
                f"{stats}\n\n"
                f"2. {odds_info}\n\n"
                "INSTRUCTIONS:\n"
                "1. Analyser attentivement la convergence des cotes des différents bookmakers\n"
                "2. Comparer les tendances des cotes avec les statistiques\n"
                "3. Identifier les écarts significatifs entre bookmakers\n"
                "4. Repérer les opportunités basées sur les cotes moyennes\n"
                "5. Évaluer la fiabilité globale des prédictions\n\n"
                "PRÉDICTIONS POSSIBLES (choisir la plus fiable):\n"
                "- +1.5 buts : si forte probabilité de buts\n"
                "- -3.5 buts : si match serré ou défensif\n"
                "- 1X : si favori à domicile ou match serré\n"
                "- X2 : si favori à l'extérieur ou match équilibré\n"
                "- 12 : si faible probabilité de match nul\n\n"
                "FORMAT DE RÉPONSE REQUIS:\n"
                "PREDICTION: [choix le plus fiable]\n"
                "CONFIANCE: [pourcentage, minimum 80%]\n"
                "EXPLICATION: [justification basée sur les cotes ET les stats]"
            )

            print("Analyse en cours...")
            message = self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text
            
            prediction_match = re.search(r"PREDICTION:\s*(.*)", response_text)
            confidence_match = re.search(r"CONFIANCE:\s*(\d+)", response_text)
            explanation_match = re.search(r"EXPLICATION:\s*(.*)", response_text, re.DOTALL)

            if prediction_match and confidence_match and explanation_match:
                prediction = prediction_match.group(1).strip()
                confidence = int(confidence_match.group(1))
                explanation = explanation_match.group(1).strip()

                if confidence >= 80:
                    print(f"✅ Prédiction : {prediction} ({confidence}%)")
                    return Prediction(
                        region=match.region,
                        competition=match.competition,
                        match=f"{match.home_team} vs {match.away_team}",
                        time=match.commence_time.astimezone(timezone(timedelta(hours=1))).strftime("%H:%M"),
                        prediction=prediction,
                        confidence=confidence,
                        explanation=explanation
                    )

            print("❌ Pas de prédiction fiable")
            return None

        except Exception as e:
            print(f"❌ Erreur: {str(e)}")
            return None

    def _format_predictions_message(self, predictions: List[Prediction]) -> str:
        current_date = datetime.now().strftime("%d/%m/%Y")
        
        message = f"🎯 *COMBO DU {current_date}* 🎯\n\n"
        
        for i, pred in enumerate(predictions, 1):
            message += (
                f"🌍 *{pred.region}*\n"
                f"👥 *{pred.match}*\n"
                f"⏰ Heure : {pred.time}\n"
                f"📌 Prédiction : *{pred.prediction}*\n"
                f"🔒 Confiance : *{pred.confidence}%*\n"
                f"{'─' * 20}\n\n"
            )
        
        message += (
            "_⚠️ Rappel important :_\n"
            "_• Pariez de manière responsable_\n"
            "_• Ne dépassez pas 5% de votre capital_"
        )
        
        return message

class BettingBot:
    # ... autres méthodes ...

    def send_predictions(self, predictions: List[Prediction]) -> None:
        if not predictions:
            print("❌ Aucune prédiction à envoyer")
            return

        print("\n4️⃣ ENVOI DU COMBO")
        message = self._format_predictions_message(predictions)
        try:
            # Créer une nouvelle boucle d'événements
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Envoyer le message de manière asynchrone
            loop.run_until_complete(
                self.bot.send_message(
                    chat_id=self.config.TELEGRAM_CHAT_ID,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            )
            
            # Fermer la boucle
            loop.close()
            
            print("✅ Combo envoyé avec succès!")
            self.last_execution_date = datetime.now().date()
            
        except Exception as e:
            print(f"❌ Erreur lors de l'envoi: {str(e)}")
            raise

    def run_daily_task(self):
        print("\n=== TÂCHE QUOTIDIENNE ===")
        self.immediate_combo_sent = False
        self.run()

    def run(self) -> None:
        try:
            print("\n=== DÉBUT DU PROCESSUS ===")
            matches = self.fetch_matches()
            if not matches:
                return

            predictions = []
            for i, match in enumerate(matches, 1):
                stats = self.get_match_stats(match)
                if stats:
                    prediction = self.analyze_match(match, stats)
                    if prediction:
                        predictions.append(prediction)
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
    print("\n=== DÉMARRAGE DU BOT ===")
    
    # Chargement des variables d'environnement
    load_dotenv()
    
    # Vérification des clés API
    print("Vérification des variables d'environnement:")
    api_keys = {
        'TELEGRAM_BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN'),
        'TELEGRAM_CHAT_ID': os.getenv('TELEGRAM_CHAT_ID'),
        'ODDS_API_KEY': os.getenv('ODDS_API_KEY'),
        'PERPLEXITY_API_KEY': os.getenv('PERPLEXITY_API_KEY'),
        'CLAUDE_API_KEY': os.getenv('CLAUDE_API_KEY')
    }
    
    config = Config(
        TELEGRAM_BOT_TOKEN=api_keys['TELEGRAM_BOT_TOKEN'],
        TELEGRAM_CHAT_ID=api_keys['TELEGRAM_CHAT_ID'],
        ODDS_API_KEY=api_keys['ODDS_API_KEY'],
        PERPLEXITY_API_KEY=api_keys['PERPLEXITY_API_KEY'],
        CLAUDE_API_KEY=api_keys['CLAUDE_API_KEY']
    )
    
    bot = BettingBot(config)

    # Combo immédiat
    print("Lancement du combo immédiat...")
    bot.immediate_combo_sent = False
    bot.last_execution_date = None
    bot.run()

    return bot  # Pour pouvoir l'utiliser dans le serveur web si nécessaire
    
    # Initialisation et démarrage du bot
    bot = BettingBot(config)
    
    # Envoi du combo immédiat
    print("=== DÉMARRAGE DU BOT - ENVOI DU COMBO IMMÉDIAT ===")
    bot.immediate_combo_sent = False
    bot.last_execution_date = None
    bot.run()

    # Planification du combo quotidien
    schedule.every().day.at("08:00").do(bot.run_daily_task)
    
    # Boucle principale
    print("=== BOT EN ATTENTE DU PROCHAIN COMBO À 8H00 ===")
    while True:
        try:
            schedule.run_pending()
            time.sleep(120)  # Vérification toutes les 2 minutes
        except Exception as e:
            print(f"❌ Erreur dans la boucle principale : {str(e)}")
            time.sleep(120)

if __name__ == "__main__":
    main()
