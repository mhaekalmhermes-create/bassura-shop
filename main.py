"""Minimal test: just serves a page, no bot."""
import os
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "OK — Bassura Shop is alive!"

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    print(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port)
