from flask import Flask, render_template, request, jsonify
import urllib.request
import json
from duckduckgo_search import DDGS


app = Flask(__name__)


import os
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "models/gemini-3.5-flash-lite"
URL = f"https://generativelanguage.googleapis.com/v1beta/{MODEL}:generateContent?key={API_KEY}"


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    query = request.form.get("query")
    if not query:
        return jsonify({"error": "Query cannot be empty"})


    # 1. Perform live search using DuckDuckGo specifically for Instagram creators
    sources = []
    search_context = ""
    try:
        # Appending keywords to strictly find Instagram influencers
        search_query = f"top {query} instagram influencers creators accounts"
        results = DDGS().text(search_query, max_results=10)
        for idx, res in enumerate(results):
            sources.append({
                'title': res.get('title', ''),
                'url': res.get('href', '')
            })
            search_context += f"Source {idx+1}: {res.get('body', '')}\n"
    except Exception as e:
