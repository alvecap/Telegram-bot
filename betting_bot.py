import requests
import anthropic
import logging
from logging.handlers import RotatingFileHandler
import telegram
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import re
import time
from retry import retry
import random
import os
from dotenv import load_dotenv
import sys

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
                
                if 0 < time_difference.total_seconds() <= 86400:  # 24 heures
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
            # Préparation détaillée des cotes
            odds_info = "ANALYSE DÉTAILLÉE DES COTES:\n\n"
            
            # Analyse par type de pari
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

            # Formatage des cotes pour le prompt
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

if predictions:
                self.send_predictions(predictions)
                self.immediate_combo_sent = True
                print("=== PROCESSUS TERMINÉ ===")
            else:
                print("❌ Aucune prédiction fiable")

        except Exception as e:
            print(f"❌ ERREUR: {str(e)}")

if __name__ == "__main__":
    # Pour tester le bot localement
    from dotenv import load_dotenv
    load_dotenv()
    
    config = Config(
        TELEGRAM_BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN'),
        TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID'),
        ODDS_API_KEY=os.getenv('ODDS_API_KEY'),
        PERPLEXITY_API_KEY=os.getenv('PERPLEXITY_API_KEY'),
        CLAUDE_API_KEY=os.getenv('CLAUDE_API_KEY')
    )
    
    bot = BettingBot(config)
    bot.run()
