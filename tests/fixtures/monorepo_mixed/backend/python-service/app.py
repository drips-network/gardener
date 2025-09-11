"""
Main application file for Python backend service
Demonstrates imports from manifest dependencies
"""

import flask
import grpc
import psycopg2
import redis
from flask import Flask, jsonify, request

# Cross-language shared dependency
from google.protobuf import message
from sqlalchemy import create_engine

# Create Flask app
app = Flask(__name__)

# Initialize Redis client
redis_client = redis.Redis(host="localhost", port=6379, db=0)

# Database connection
engine = create_engine("postgresql://user:password@localhost/db")


@app.route("/api/health")
def health_check():
    return jsonify({"status": "healthy"})


@app.route("/api/data")
def get_data():
    # Example using Redis
    cached = redis_client.get("data")
    if cached:
        return jsonify({"data": cached.decode("utf-8"), "source": "cache"})
    return jsonify({"data": "fresh", "source": "database"})


if __name__ == "__main__":
    app.run(debug=True)
