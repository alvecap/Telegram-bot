from flask import Flask
import os
import threading

app = Flask(__name__)

@app.route('/health')
def health_check():
    return 'OK', 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
