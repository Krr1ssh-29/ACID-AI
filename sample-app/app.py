"""
Sample Flask application for CI/CD pipeline demo.
"""
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "version": "1.0.0"})


@app.route("/")
def index():
    return jsonify({"message": "Self-Healing CI/CD Demo App"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
