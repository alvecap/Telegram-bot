from flask import Flask
import os
from betting_bot import main as bot_main
import threading

app = Flask(__name__)

@app.route('/health')
def health_check():
    return 'OK', 200

def run_bot():
    bot_main()

if __name__ == "__main__":
    # Démarrer le bot dans un thread séparé
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Démarrer le serveur Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
