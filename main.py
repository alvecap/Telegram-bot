import requests
import random
import asyncio
import nest_asyncio
import telegram
from datetime import datetime, timedelta
import pytz
from openai import OpenAI

nest_asyncio.apply()

class FootballPredictor:
    def __init__(self):
        self.api_key = 'd73cb48b3658c3508a75b907d52529d4'
        self.telegram_token = '7859048967:AAGtkGTwIUDN44PZB76EyvD1zogyJPCMOmw'
        self.chat_id = '-1002421926748'
        self.nebius_key = "eyJhbGciOiJIUzI1NiIsImtpZCI6IlV6SXJWd1h0dnprLVRvdzlLZWstc0M1akptWXBvX1VaVkxUZlpnMDRlOFUiLCJ0eXAiOiJKV1QifQ."
            "eyJzdWIiOiJnb29nbGUtb2F1dGgyfDEwODMxNDA0MDg1NDgyMzQ4NzI0MCIsInNjb3BlIjoib3BlbmlkIG9mZmxpbmVfYWNjZXNzIiwiaXNz"
            "IjoiYXBpX2tleV9pc3N1ZXIiLCJhdWQiOlsiaHR0cHM6Ly9uZWJpdXMtaW5mZXJlbmNlLmV1LmF1dGgwLmNvbS9hcGkvdjIvIl0sImV4cCI6"
            "MTg5MTA4OTU1MSwidXVpZCI6IjFmMWFiNjVjLWQ4ZDktNDc1OC04OWUzLTRhOGNkNWM0NGQyZiIsIm5hbWUiOiJBTCBWRSBDQVBJVEFMIiwi"
            "ZXhwaXJlc19hdCI6IjIwMjktMTItMDRUMTQ6Mzk6MTErMDAwMCJ9.QzzRrQXss4nG_QqeNBz2W47zyBFterzDn70_Tr0DBPw"
        
        self.bot = telegram.Bot(token=self.telegram_token)
        self.ai_client = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=self.nebius_key)
        
        # Fuseau horaire Afrique centrale
        self.timezone = pytz.timezone('Africa/Lagos')  # UTC+1

    def get_matches(self):
        response = requests.get(
            'https://api.the-odds-api.com/v4/sports/soccer/odds',
            params={
                'apiKey': self.api_key,
                'regions': 'eu',
                'markets': 'h2h,totals'
            }
        )
        matches = response.json()
        
        now = datetime.now(self.timezone)
        today_end = now.replace(hour=23, minute=59, second=59)
        
        valid_matches = []
        for match in matches:
            match_time = datetime.fromisoformat(match['commence_time'].replace('Z', '+00:00')).astimezone(self.timezone)
            
            # Vérifier si le match est aujourd'hui et n'est pas en live
            if (match_time.date() == now.date() and 
                match_time > now and 
                any(b['key'] == 'onexbet' for b in match['bookmakers'])):
                match['local_time'] = match_time
                valid_matches.append(match)
        
        return valid_matches

    def get_ai_prediction(self, match):
        bookmaker = next(b for b in match['bookmakers'] if b['key'] == 'onexbet')
        h2h = next(m for m in bookmaker['markets'] if m['key'] == 'h2h')
        
        home = next(o['price'] for o in h2h['outcomes'] if o['name'] == match['home_team'])
        draw = next(o['price'] for o in h2h['outcomes'] if o['name'] == 'Draw')
        away = next(o['price'] for o in h2h['outcomes'] if o['name'] == match['away_team'])

        prompt = f"""ANALYSTE PARIS SPORTIF:
{match['home_team']} vs {match['away_team']}
Heure: {match['local_time'].strftime('%H:%M')}
Côte 1: {home:.2f}
Côte X: {draw:.2f}
Côte 2: {away:.2f}

DONNER UNE SEULE PRÉDICTION PARMI:
Double chance: 1X
Double chance: X2
Double chance: 12
Total buts: Over 2.5
Total buts: Under 2.5
Total buts: Under 3.5

RÉPONDRE UNIQUEMENT AVEC LA PRÉDICTION."""

        completion = self.ai_client.chat.completions.create(
            model="meta-llama/Meta-Llama-3.1-70B-Instruct-fast",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=10
        )
        prediction = completion.choices[0].message.content.strip()

        valid_predictions = [
            "Double chance: 1X", "Double chance: X2", "Double chance: 12",
            "Total buts: Over 2.5", "Total buts: Under 2.5", "Total buts: Under 3.5"
        ]
        
        if prediction in valid_predictions:
            print(f"Prediction for {match['home_team']} vs {match['away_team']} ({match['local_time'].strftime('%H:%M')}): {prediction}")
            return prediction
        return None

    def get_real_odds(self, match, prediction):
        bookmaker = next(b for b in match['bookmakers'] if b['key'] == 'onexbet')
        h2h = next(m for m in bookmaker['markets'] if m['key'] == 'h2h')

        home = float(next(o['price'] for o in h2h['outcomes'] if o['name'] == match['home_team']))
        draw = float(next(o['price'] for o in h2h['outcomes'] if o['name'] == 'Draw'))
        away = float(next(o['price'] for o in h2h['outcomes'] if o['name'] == match['away_team']))

        if prediction == "Double chance: 1X":
            odds = 1 / (1/home + 1/draw)
        elif prediction == "Double chance: X2":
            odds = 1 / (1/away + 1/draw)
        elif prediction == "Double chance: 12":
            odds = 1 / (1/home + 1/away)
        elif "Total buts" in prediction:
            value = prediction.split(': ')[1]
            totals = next(m for m in bookmaker['markets'] if m['key'] == 'totals')
            for outcome in totals['outcomes']:
                if value in outcome['name']:
                    odds = float(outcome['price'])
                    break

        odds = round(odds, 2)
        return odds

    def format_competition(self, competition):
        parts = competition.split()
        if len(parts) > 1:
            country = parts[0]
            league = ' '.join(parts[1:])
            return f"⚽️ *{country}*: {league}"
        return f"⚽️ *{competition}*"

    async def prepare_and_send_predictions(self):
        matches = self.get_matches()
        print(f"Matches disponibles aujourd'hui: {len(matches)}")
        
        if not matches:
            return False

        predictions = []
        random.shuffle(matches)
        
        # On prend entre 3 et 5 matches si disponible
        target_matches = min(random.randint(3, 5), len(matches))
        print(f"Tentative de trouver {target_matches} matches...")

        for match in matches:
            if len(predictions) >= target_matches:
                break

            prediction = self.get_ai_prediction(match)
            if prediction:
                odds = self.get_real_odds(match, prediction)
                if odds:
                    predictions.append({
                        'competition': match['sport_title'],
                        'match': f"{match['home_team']} vs {match['away_team']}",
                        'time': match['local_time'].strftime('%H:%M'),
                        'prediction': prediction,
                        'odds': odds
                    })

        if len(predictions) >= 3:
            total_odds = 1.0
            message = "🎯 *COMBO VIP DU JOUR* 🎯\n\n"

            for pred in predictions:
                total_odds *= pred['odds']
                message += (
                    f"{self.format_competition(pred['competition'])}\n"
                    f"⏰ *{pred['time']}*\n"
                    f"👥 *{pred['match']}*\n"
                    f"🎯 *{pred['prediction']}*\n"
                    f"💰 *{pred['odds']:.2f}*\n\n"
                    f"{'─' * 15}\n\n"
                )

            message += f"📈 *COTE TOTALE*: *{total_odds:.2f}*"

            requests.post(
                f'https://api.telegram.org/bot{self.telegram_token}/sendMessage',
                json={
                    'chat_id': self.chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }
            )
            print(f"Combo de {len(predictions)} matches envoyé avec succès")
            return True
            
        print(f"Pas assez de matches valides trouvés ({len(predictions)})")
        return False

    async def run(self):
        # Message de démarrage
        requests.post(
            f'https://api.telegram.org/bot{self.telegram_token}/sendMessage',
            json={
                'chat_id': self.chat_id,
                'text': "🚀 Service démarré",
                'parse_mode': 'Markdown'
            }
        )

        # Premier envoi
        for _ in range(5):
            if await self.prepare_and_send_predictions():
                break
            await asyncio.sleep(5)

        # Envois quotidiens
        while True:
            now = datetime.now()
            next_run = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now.hour >= 8:
                next_run += timedelta(days=1)
            
            wait_time = (next_run - now).total_seconds()
            print(f"Prochain envoi prévu à {next_run}")
            await asyncio.sleep(wait_time)
            await self.prepare_and_send_predictions()

if __name__ == "__main__":
    print(f"Service démarré le {datetime.now()}")
    print("Premier envoi immédiat puis chaque jour à 8h00")
    asyncio.run(FootballPredictor().run())
