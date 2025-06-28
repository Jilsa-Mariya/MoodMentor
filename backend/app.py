import os
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_pymongo import PyMongo
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from flask import send_from_directory


# Load environment variables
load_dotenv()
cohere_api_key = os.getenv("COHERE_API_KEY")
print("Loaded Cohere API key:", cohere_api_key[:10], "********")

# Initialize app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:8000"}})

# MongoDB config
app.config["MONGO_URI"] = "mongodb://localhost:27017/moodmentor"
mongo = PyMongo(app)
users_collection = mongo.db.users
todo_collection = mongo.db.todos
journal_collection = mongo.db.journal
chat_collection = mongo.db.chat_logs
mood_collection = mongo.db.moods

# ------------------------
# AUTH ROUTES
# ------------------------

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'message': 'Email and password are required'}), 400
    if users_collection.find_one({'email': email}):
        return jsonify({'message': 'User already exists'}), 400
    users_collection.insert_one({'email': email, 'password': password})
    return jsonify({'message': 'User registered successfully'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'message': 'Email and password are required'}), 400
    user = users_collection.find_one({'email': email, 'password': password})
    if user:
        return jsonify({'message': 'Login successful', 'email': email}), 200
    else:
        return jsonify({'message': 'Invalid credentials'}), 401

# ------------------------
# TO-DO ROUTES
# ------------------------

@app.route('/tasks/<email>/<date>', methods=['GET'])
def get_tasks(email, date):
    tasks = list(todo_collection.find({'email': email, 'date': date}))
    for task in tasks:
        task['_id'] = str(task['_id'])
    return jsonify(tasks)

@app.route('/tasks', methods=['POST'])
def add_task():
    data = request.get_json()
    task = {
        'email': data['email'],
        'title': data['title'],
        'date': data['date'],
        'time': data.get('time', ''),
        'completed': False,
        'createdAt': datetime.now()
    }
    result = todo_collection.insert_one(task)
    task['_id'] = str(result.inserted_id)
    return jsonify(task), 201

@app.route('/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    data = request.get_json()
    todo_collection.update_one({'_id': ObjectId(task_id)}, {'$set': data})
    updated_task = todo_collection.find_one({'_id': ObjectId(task_id)})
    updated_task['_id'] = str(updated_task['_id'])
    return jsonify(updated_task), 200

@app.route('/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    todo_collection.delete_one({'_id': ObjectId(task_id)})
    return jsonify({'message': 'Task deleted'}), 200

@app.route('/tasks/overdue/<email>', methods=['GET'])
def get_overdue_tasks(email):
    now = datetime.now()
    overdue_threshold = now - timedelta(days=1)
    overdue_tasks = todo_collection.find({
        'email': email,
        'completed': False,
        'createdAt': {'$lt': overdue_threshold}
    })
    results = [{'_id': str(task['_id']), **task} for task in overdue_tasks]
    for r in results:
        r['_id'] = str(r['_id'])
    return jsonify(results)

# ------------------------
# JOURNAL ROUTES
# ------------------------

@app.route('/journal/<email>/<date>', methods=['GET'])
def get_journal_entries(email, date):
    entries = list(journal_collection.find({'email': email, 'date': date}))
    for entry in entries:
        entry['_id'] = str(entry['_id'])
    return jsonify(entries)

@app.route('/journal/<email>', methods=['GET'])
def get_all_journal_entries(email):
    entries = list(journal_collection.find({'email': email}))
    for entry in entries:
        entry['_id'] = str(entry['_id'])
    return jsonify(entries)

@app.route('/journal', methods=['POST'])
def add_journal_entry():
    data = request.get_json()
    existing = journal_collection.find_one({'email': data['email'], 'date': data['date']})
    if existing:
        journal_collection.update_one(
            {'_id': existing['_id']},
            {'$set': {'content': data['content'], 'updatedAt': datetime.now()}}
        )
        return jsonify({'message': 'Entry updated'}), 200
    else:
        entry = {
            'email': data['email'],
            'date': data['date'],
            'content': data['content'],
            'createdAt': datetime.now()
        }
        result = journal_collection.insert_one(entry)
        entry['_id'] = str(result.inserted_id)
        return jsonify(entry), 201

@app.route('/journal/<email>/<date>', methods=['PUT'])
def update_journal(email, date):
    data = request.get_json()
    result = journal_collection.update_one(
        {'email': email, 'date': date},
        {'$set': {'content': data['content'], 'updatedAt': datetime.now()}}
    )
    if result.matched_count:
        return jsonify({'message': 'Journal updated'}), 200
    else:
        return jsonify({'message': 'Entry not found'}), 404

# ------------------------
# MOOD ROUTES
# ------------------------

@app.route('/mood', methods=['POST'])
def save_mood():
    data = request.get_json()
    entry = {
        'email': data['email'],
        'mood': data['mood'],
        'intensity': data['intensity'],
        'note': data['note'],
        'date': datetime.now().strftime("%Y-%m-%d"),
        'createdAt': datetime.now()
    }
    result = mood_collection.insert_one(entry)
    entry['_id'] = str(result.inserted_id)
    return jsonify(entry), 201

# ------------------------
# CHAT HISTORY ROUTE
# ------------------------

@app.route('/chat-history', methods=['GET'])
def get_chat_history():
    user_id = request.args.get("user_id")
    date = request.args.get("date")
    logs = list(chat_collection.find({
        "user_id": user_id,
        "date": date
    }, {'_id': 0}).sort("timestamp", 1))
    return jsonify(logs)

# ------------------------
# CHATBOT ROUTE (Cohere)
# ------------------------

@app.route('/chatbot', methods=['POST'])
def chatbot_response():
    data = request.get_json()
    user_message = data.get("message")
    user_id = data.get("user_id", "anonymous")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        headers = {
            "Authorization": f"Bearer {cohere_api_key}",
            "Content-Type": "application/json"
        }

        # Enhanced prompt to make Luna aware of app features
        body = {
            "model": "command-r-plus",
            "prompt": f"""You are Luna, a friendly and emotionally supportive chatbot helping people through tough times. A user says: '{user_message}'.
If it fits, suggest exploring their journal, to-do list, exercises, or games within the Mood Mentor app. Be warm and concise.""",
            "max_tokens": 180,
            "temperature": 0.7
        }

        response = requests.post("https://api.cohere.ai/v1/generate", headers=headers, json=body)
        result = response.json()
        print("Cohere response:", result)

        reply = result.get("generations", [{}])[0].get("text", "Sorry, I couldn't respond.")

        chat_collection.insert_one({
            "user_id": user_id,
            "message": user_message,
            "reply": reply,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({"reply": reply.strip()})

    except Exception as e:
        print("Error in /chatbot route:", e)
        return jsonify({"reply": "Sorry, I couldn’t respond."}), 500

@app.route('/models/<path:filename>')
def serve_models(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'models'), filename)

@app.route('/moods/<email>', methods=['GET'])
def get_all_moods(email):
    moods = list(mood_collection.find({'email': email}))
    for mood in moods:
        mood['_id'] = str(mood['_id'])
    return jsonify(moods)
@app.route('/mood-summary/<email>', methods=['GET'])
def get_mood_summary(email):
    pipeline = [
        { "$match": { "email": email } },
        { "$group": { "_id": "$mood", "count": { "$sum": 1 } } }
    ]
    results = list(mood_collection.aggregate(pipeline))
    mood_counts = {r['_id']: r['count'] for r in results}
    return jsonify({"counts": mood_counts})


# ------------------------
# RUN APP
# ------------------------

if __name__ == '__main__':
    app.run(debug=True)
