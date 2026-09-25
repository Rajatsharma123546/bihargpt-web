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
        print("Search error:", e)

    # 2. Build the prompt for Gemini combining internet results
    prompt_text = f"""You are an expert social media analyst. The user wants to find the top Instagram content creators for the niche: '{query}'.
Here are some live internet search results to help you:
{search_context}

You MUST combine the search results above with your own vast knowledge to create a MASSIVE list of the top Instagram creators for this niche.
You MUST return the output ONLY as a valid JSON array of objects containing AS MANY top creators as possible (aim for 15 to 30 creators if possible).
CRITICAL: You MUST sort the array in descending order based on their follower count (highest followers at the top, lowest at the bottom).
Do not write any other text or markdown wrapping outside the JSON array.

Each object must have the following exact keys:
- "name": Creator's real name or display name.
- "handle": Their Instagram handle (e.g. @username).
- "profile_url": Full URL to their Instagram profile (https://www.instagram.com/username/).
- "description": A short, catchy description of what they post.
- "followers": An estimate of their followers if known (e.g., "5.2M", "800K").

Output example:
[
  {{
    "name": "John Doe",
    "handle": "@johndoe",
    "profile_url": "https://www.instagram.com/johndoe/",
    "description": "Reviews the latest smartphones and gadgets.",
    "followers": "2.5M"
  }}
]
"""

    # 3. Send combined payload to Gemini 3.5 Flash Lite
    payload = {
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }

    req = urllib.request.Request(URL, data=json.dumps(payload).encode('utf-8'), method='POST')
    req.add_header("Content-Type", "application/json")

    try:
        response = urllib.request.urlopen(req)
        data = json.loads(response.read().decode('utf-8'))
        
        if 'candidates' in data and len(data['candidates']) > 0:
            candidate = data['candidates'][0]
            text = candidate['content']['parts'][0]['text']
            
            import re
            # Extract JSON block safely
            json_match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
            json_str = json_match.group(0) if json_match else text
            
            # Remove possible markdown ticks if regex missed
            json_str = json_str.strip().strip('```json').strip('```').strip()
            
            # Clean common JSON issues from Gemini
            json_str = json_str.replace('\n', ' ').replace('\r', ' ')
            json_str = json_str.replace(', - "', ', "')  # Fix stray dashes
            json_str = json_str.replace('\\n', ' ').replace('\\r', ' ')
            # Fix trailing commas before ] or }
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            # Fix smart quotes
            json_str = json_str.replace('\u201c', '"').replace('\u201d', '"')
            json_str = json_str.replace('\u2018', "'").replace('\u2019', "'")
            
            try:
                creators_data = json.loads(json_str)
            except json.JSONDecodeError:
                # Last resort: try to extract individual objects
                try:
                    # Try wrapping in array if it's objects without brackets
                    if not json_str.startswith('['):
                        json_str = '[' + json_str + ']'
                    creators_data = json.loads(json_str)
                except:
                    return jsonify({"error": "AI returned invalid data. Please try again."})
            
            return jsonify({
                "creators": creators_data,
                "sources": sources
            })
        else:
            return jsonify({"error": "No response generated from the model."})
            
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'read'):
            error_msg = e.read().decode('utf-8')
        return jsonify({"error": error_msg})

@app.route("/extract_urls", methods=["POST"])
def extract_urls():
    text_data = request.form.get("data", "")
    if not text_data:
        return jsonify({"error": "No data provided"})
        
    import re
    # Extract Instagram URLs
    urls = re.findall(r'https://www\.instagram\.com/[^\s]+', text_data)
    
    # Remove duplicates and clean
    cleaned_urls = list(set([url.strip('"\',') for url in urls]))
    
    return jsonify({"urls": cleaned_urls})

import uuid
import threading
import time

BATCHES = {}

def process_batch_thread(batch_id, urls_to_download, language):
    import os
    import datetime
    import subprocess
    import time
    import requests
    import glob
    
    batch = BATCHES[batch_id]
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"Downloads_Batch_{timestamp}"
    os.makedirs(folder_name, exist_ok=True)
    batch["folder"] = os.path.abspath(folder_name)
    
    downloaded_records = []
    request_timestamps = []
    
    for i, url in enumerate(urls_to_download, 1):
        batch["current_video"] = i
        batch["current_status"] = f"Downloading Video {i}..."
        batch["current_progress"] = 20
        
        output_template = os.path.join(folder_name, f"video_{i}_%(id)s.%(ext)s")
        cmd = ["python", "-m", "yt_dlp", url, "-o", output_template, "--quiet", "--no-warnings"]
        
        record = {"url": url, "status": "Pending", "folder": folder_name, "ai_summary": ""}
        try:
            subprocess.run(cmd, check=True)
            record["status"] = "Success"
        except subprocess.CalledProcessError:
            record["status"] = "Failed"
            downloaded_records.append(record)
            batch["records"] = downloaded_records
            continue
            
        video_files = glob.glob(os.path.join(folder_name, f"video_{i}_*"))
        if video_files:
            video_path = video_files[0]
            
            # Rate Limiting
            batch["current_status"] = "Checking Rate Limits..."
            current_time = time.time()
            request_timestamps = [t for t in request_timestamps if current_time - t < 60]
            
            if len(request_timestamps) >= 14:
                wait_time = 60 - (current_time - request_timestamps[0])
                if wait_time > 0:
                    batch["current_status"] = f"Rate Limit Reached. Pausing for {int(wait_time)}s..."
                    time.sleep(wait_time)
                request_timestamps = [t for t in request_timestamps if time.time() - t < 60]
                
            request_timestamps.append(time.time())

            try:
                batch["current_status"] = f"Uploading Video {i} to Gemini..."
                batch["current_progress"] = 50
                
                upload_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={API_KEY}"
                file_size = os.path.getsize(video_path)
                mime_type = "video/mp4"
                
                headers = {
                    "X-Goog-Upload-Protocol": "raw",
                    "X-Goog-Upload-Command": "upload",
                    "X-Goog-Upload-Header-Content-Length": str(file_size),
                    "X-Goog-Upload-Header-Content-Type": mime_type,
                    "Content-Type": mime_type
                }
                
                with open(video_path, 'rb') as f:
                    upload_res = requests.post(upload_url, headers=headers, data=f)
                
                upload_data = upload_res.json()
                
                if 'error' in upload_data:
                    record["ai_summary"] = f"Upload failed: {upload_data['error']}"
                else:
                    file_name = upload_data['file']['name']
                    file_uri = upload_data['file']['uri']
                    
                    batch["current_status"] = f"Processing Video {i} on Gemini..."
                    batch["current_progress"] = 70
                    
                    while True:
                        status_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={API_KEY}"
                        status_res = requests.get(status_url)
                        status_data = status_res.json()
                        state = status_data.get('state', '')
                        
                        if state == 'ACTIVE':
                            break
                        elif state == 'FAILED':
                            record["ai_summary"] = "AI failed to process the video on Google's servers."
                            break
                        time.sleep(3)
                    
                    if not record["ai_summary"]:
                        batch["current_status"] = f"Generating Summary for Video {i}..."
                        batch["current_progress"] = 90
                        
                        detailed_prompt = f"""You are an expert video analyst. Watch this video and provide a HIGHLY DETAILED analysis.
I need the final output STRICTLY in the following language: {language}.

Include the following sections in your analysis:
1. Scene-by-Scene Breakdown: Explain exactly what is happening visually.
2. Audio & Music: Describe background music, sound effects, or spoken words.
3. Why it's Engaging: Explain the psychology or "hook". Why is it viral?
4. Overall Summary: A short conclusive paragraph.

Ensure tone is natural and fully translated."""
                        
                        gen_url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL}:generateContent?key={API_KEY}"
                        payload = {
                            "contents": [{"parts": [{"fileData": {"mimeType": mime_type, "fileUri": file_uri}}, {"text": detailed_prompt}]}]
                        }
                        gen_res = requests.post(gen_url, json=payload)
                        gen_data = gen_res.json()
                        
                        if 'error' in gen_data:
                            record["ai_summary"] = f"Generate Error: {gen_data['error']}"
                        else:
                            record["ai_summary"] = gen_data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                record["ai_summary"] = f"Error: {str(e)}"
        
        batch["current_progress"] = 100
        downloaded_records.append(record)
        batch["records"] = downloaded_records
        batch["completed"] += 1

    log_file_path = os.path.join(folder_name, "download_log.txt")
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write(f"Download Batch Completed\nTotal Attempted: {len(urls_to_download)}\n\n")
        for rec in downloaded_records:
            f.write(f"URL: {rec['url']}\nStatus: {rec['status']}\nSaved In: {os.path.abspath(rec['folder'])}\n\n")
            
    batch["log_file"] = os.path.abspath(log_file_path)
    batch["done"] = True
    batch["current_status"] = "All videos processed successfully!"


@app.route("/start_batch", methods=["POST"])
def start_batch():
    urls = request.json.get("urls", [])
    count = int(request.json.get("count", 1))
    language = request.json.get("language", "Hindi")
    
    if not urls:
        return jsonify({"error": "No URLs provided"})
        
    urls_to_download = urls[:count]
    batch_id = str(uuid.uuid4())
    
    BATCHES[batch_id] = {
        "total": len(urls_to_download),
        "completed": 0,
        "current_video": 0,
        "current_status": "Starting...",
        "current_progress": 0,
        "records": [],
        "done": False,
        "folder": "",
        "log_file": ""
    }
    
    thread = threading.Thread(target=process_batch_thread, args=(batch_id, urls_to_download, language))
    thread.daemon = True
    thread.start()
    
    return jsonify({"batch_id": batch_id})


@app.route("/batch_status/<batch_id>")
def batch_status(batch_id):
    if batch_id in BATCHES:
        return jsonify(BATCHES[batch_id])
    return jsonify({"error": "Batch not found"}), 404


@app.route("/chat_agent", methods=["POST"])
def chat_agent():
    user_msg = request.json.get("message")
    summaries = request.json.get("summaries", [])
    
    if not user_msg:
        return jsonify({"error": "Message cannot be empty."})
        
    import requests
    context_text = "\n\n--- VIDEO SUMMARY ---\n\n".join(summaries)
    
    prompt = f"""You are an exclusive Content Strategist & Video Analyst Agent. 
YOUR SOLE PURPOSE is to analyze the provided video summaries. 

RULES:
1. You MUST answer the user's questions STRICTLY based on the "AVAILABLE VIDEO SUMMARIES" below.
2. If the user asks something completely unrelated to the provided summaries, you MUST politely refuse and state that you can only analyze the downloaded videos. 
3. DO NOT use outside knowledge, DO NOT hallucinate, and DO NOT give generic advice that isn't backed by the provided summaries.
4. If there is only 1 summary provided, answer based on that 1. As more summaries are added in future prompts, adapt your answers to the combined dataset.
5. Reply in the same language the summaries are written in.

AVAILABLE VIDEO SUMMARIES (Context):
{context_text}

USER QUESTION: {user_msg}

Answer the question strictly based on the context:"""

    gen_url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        res = requests.post(gen_url, json=payload)
        data = res.json()
        if 'error' in data:
            return jsonify({"error": data['error']})
        answer = data['candidates'][0]['content']['parts'][0]['text']
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/chat_general", methods=["POST"])
def chat_general():
    user_msg = request.json.get("message")
    context = request.json.get("context", "")
    
    if not user_msg:
        return jsonify({"error": "Message cannot be empty."})
        
    import requests
    
    prompt = f"""You are a helpful AI assistant built into an Instagram Creator Analysis tool.
You can answer general questions, help with content strategy, give advice, and more.

{f"CONTEXT FROM PREVIOUS RESULTS:{chr(10)}{context}" if context else ""}

USER: {user_msg}

Provide a helpful, detailed, and friendly answer."""

    gen_url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        res = requests.post(gen_url, json=payload)
        data = res.json()
        if 'error' in data:
            return jsonify({"error": data['error']})
        answer = data['candidates'][0]['content']['parts'][0]['text']
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)})



@app.route("/agent/route", methods=["POST"])
def agent_route():
    data = request.json
    prompt = data.get("prompt", "").strip()
    
    if not prompt:
        return jsonify({"error": "Prompt is empty."})
        
    import re
    import os
    import requests
    # Fast path: If the prompt contains clear Instagram video URLs, they want to analyze them.
    # No need to route to Gemini, just execute directly.
    ig_video_urls = re.findall(r'instagram\.com/(?:reel|p|tv|share)/[^\s]+', prompt, re.IGNORECASE)
    
    if ig_video_urls or (re.findall(r'https?://[^\s]+', prompt) and len(prompt.split()) < len(re.findall(r'https?://[^\s]+', prompt)) * 15):
        return jsonify({
            "action": "execute",
            "tool": "analyze_videos",
            "extracted_query": prompt
        })
        
    api_key = API_KEY # use global API_KEY
    url = URL # use global URL
    
    system_instruction = '''You are an intelligent AI assistant. Route the user's prompt to the correct tool.
Available Tools:
1. "search_creators": For finding, discovering, or researching Instagram influencers, creators, or content based on a niche or location.
2. "analyze_videos": For analyzing specific Instagram video URLs to extract content strategies. CRITICAL: If the user pastes a large block of text containing multiple Instagram URLs, tables, or raw data, their intent is to ANALYZE those URLs. Always choose "analyze_videos" for this.

Return ONLY a valid JSON object with NO markdown or backticks:
{
  "tool": "search_creators" | "analyze_videos",
  "extracted_query": "Cleaned search query or raw URLs",
  "human_confirmation_message": "A polite 1-sentence message asking to confirm the action. E.g., 'I will search the web for Top Fitness Influencers in Mumbai. Should I proceed?'"
}'''

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.1}
    }
    
    try:
        resp = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
        result = resp.json()
        text_resp = result['candidates'][0]['content']['parts'][0]['text']
        
        # Clean JSON
        text_resp = text_resp.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(text_resp)
        
        return jsonify({
            "action": "confirm",
            "tool": parsed.get("tool", "search_creators"),
            "extracted_query": parsed.get("extracted_query", prompt),
            "message": parsed.get("human_confirmation_message", "Should I proceed with this task?")
        })
    except Exception as e:
        print("Router Error:", e)
        return jsonify({"action": "execute", "tool": "search_creators", "extracted_query": prompt})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
