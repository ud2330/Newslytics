from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, timezone
from bson.objectid import ObjectId
from newspaper import Article
import spacy
import io
import re
import os
import numpy as np

# PDF generation imports
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

# File processing imports
from PIL import Image
import pytesseract
from docx import Document
import PyPDF2

# ML imports for semantic similarity
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['MONGO_URI'] = 'mongodb://localhost:27017/newslytics'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png'}

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize MongoDB
mongo = PyMongo(app)

# Load SpaCy English model
try:
    nlp = spacy.load("en_core_web_sm")
except:
    print("SpaCy model not found. Run: python -m spacy download en_core_web_sm")
    nlp = None

# Load Sentence Transformer model for semantic similarity
try:
    semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
    print("✓ Sentence Transformer model loaded successfully")
except Exception as e:
    print(f"Warning: Could not load Sentence Transformer model: {e}")
    semantic_model = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath):
    """Extract text from various file formats"""
    ext = filepath.rsplit('.', 1)[1].lower()
    
    try:
        if ext == 'txt':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        
        elif ext == 'pdf':
            text = ''
            with open(filepath, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text() + '\n'
            return text
        
        elif ext in ['docx', 'doc']:
            doc = Document(filepath)
            return '\n'.join([para.text for para in doc.paragraphs])
        
        elif ext in ['jpg', 'jpeg', 'png']:
            img = Image.open(filepath)
            return pytesseract.image_to_string(img)
        
    except Exception as e:
        print(f"Error extracting text from {filepath}: {e}")
        return ""
    
    return ""

# Decorator to check if user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')

        if not name or not email or not password:
            return jsonify({'success': False, 'message': 'All fields are required'}), 400

        existing_user = mongo.db.users.find_one({'email': email})
        if existing_user:
            return jsonify({'success': False, 'message': 'Email already registered'}), 400

        hashed_password = generate_password_hash(password)

        user_doc = {
            'name': name,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.now(timezone.utc),
            'last_login': None
        }

        result = mongo.db.users.insert_one(user_doc)

        session['user_id'] = str(result.inserted_id)
        session['user_name'] = name
        session['user_email'] = email

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'redirect': url_for('dashboard')
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password are required'}), 400

        user = mongo.db.users.find_one({'email': email})
        if not user or not check_password_hash(user['password'], password):
            return jsonify({'success': False, 'message': 'Invalid email or password'}), 401

        mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {'last_login': datetime.now(timezone.utc)}}
        )

        session['user_id'] = str(user['_id'])
        session['user_name'] = user['name']
        session['user_email'] = user['email']

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'redirect': url_for('dashboard')
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400

        user = mongo.db.users.find_one({'email': email})
        return jsonify({
            'success': True,
            'message': 'If the email exists, a reset link has been sent'
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html',
                           user_name=session.get('user_name'),
                           user_email=session.get('user_email'))

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    try:
        data = request.get_json()
        analysis_type = data.get('type')

        if analysis_type == 'url':
            url = data.get('url', '').strip()
            if not url:
                return jsonify({'success': False, 'message': 'URL is required'}), 400
            
            content = extract_article_content(url)
            if not content or len(content) < 100:
                return jsonify({'success': False, 'message': 'Failed to extract meaningful article content from URL'}), 400
            source = url
            
        elif analysis_type == 'text':
            text = data.get('text', '').strip()
            if not text or len(text) < 100:
                return jsonify({'success': False, 'message': 'Article text must be at least 100 characters'}), 400
            content = text
            source = 'Manual Input'
            
        else:
            return jsonify({'success': False, 'message': 'Invalid analysis type'}), 400

        title = generate_title_from_content(content)
        summary_short = generate_summary(content, 'short')
        summary_medium = generate_summary(content, 'medium')
        summary_long = generate_summary(content, 'long')
        keywords = extract_keywords(content)
        key_points = generate_key_points(content)
        sentiment = calculate_sentiment(content)
        crisis_level, crisis_description = determine_crisis_level(content, title)
        named_entities = extract_named_entities(content)

        summary_doc = {
            'user_id': session['user_id'],
            'type': analysis_type,
            'title': title,
            'summary': summary_medium,
            'summary_short': summary_short,
            'summary_medium': summary_medium,
            'summary_long': summary_long,
            'full_content': content,
            'source': source,
            'created_at': datetime.now(timezone.utc),
            'sentiment': sentiment,
            'key_points': key_points,
            'keywords': keywords,
            'named_entities': named_entities,
            'crisis_level': crisis_level,
            'crisis_description': crisis_description
        }

        result = mongo.db.summaries.insert_one(summary_doc)

        return jsonify({
            'success': True,
            'message': 'Article analyzed successfully',
            'summary_id': str(result.inserted_id),
            'redirect': url_for('analysis_page', summary_id=str(result.inserted_id))
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/compare-articles', methods=['POST'])
@login_required
def compare_articles():
    """Handle article comparison from both URLs and file uploads"""
    try:
        articles_data = []
        
        # Handle URL inputs
        urls = request.form.getlist('urls')
        for idx, url in enumerate(urls):
            url = url.strip()
            if not url:
                continue
                
            try:
                content = extract_article_content(url)
                if not content or len(content) < 100:
                    continue
                
                # Analyze the article
                title = generate_title_from_content(content)
                summary = generate_summary(content, 'medium')
                keywords = extract_keywords(content)
                key_points = generate_key_points(content)
                sentiment = calculate_sentiment(content)
                named_entities = extract_named_entities(content)
                word_count = len(content.split())
                
                articles_data.append({
                    'source': url,
                    'title': title,
                    'summary': summary,
                    'keywords': keywords,
                    'key_points': key_points,
                    'sentiment': sentiment,
                    'named_entities': named_entities,
                    'word_count': word_count,
                    'content': content[:500]
                })
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
                continue
        
        # Handle file uploads
        if 'files' in request.files:
            files = request.files.getlist('files')
            
            for idx, file in enumerate(files):
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{idx}_{filename}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    file.save(filepath)
                    
                    # Extract text from file
                    content = extract_text_from_file(filepath)
                    
                    # Clean up uploaded file
                    try:
                        os.remove(filepath)
                    except:
                        pass
                    
                    if not content or len(content) < 100:
                        continue
                    
                    # Analyze the article
                    title = generate_title_from_content(content)
                    summary = generate_summary(content, 'medium')
                    keywords = extract_keywords(content)
                    key_points = generate_key_points(content)
                    sentiment = calculate_sentiment(content)
                    named_entities = extract_named_entities(content)
                    word_count = len(content.split())
                    
                    articles_data.append({
                        'filename': filename,
                        'title': title,
                        'summary': summary,
                        'keywords': keywords,
                        'key_points': key_points,
                        'sentiment': sentiment,
                        'named_entities': named_entities,
                        'word_count': word_count,
                        'content': content[:500]
                    })
        
        if len(articles_data) < 2:
            return jsonify({'success': False, 'message': 'Please provide at least 2 valid articles to compare'}), 400
        
        if len(articles_data) > 5:
            articles_data = articles_data[:5]
        
        # Find common themes
        common_keywords = find_common_keywords(articles_data)
        common_entities = find_common_entities(articles_data)
        similarity_score = calculate_similarity_score(articles_data)
        sentiment_comparison = compare_sentiments(articles_data)
        
        # Save comparison to database
        comparison_doc = {
            'user_id': session['user_id'],
            'articles': articles_data,
            'common_keywords': common_keywords,
            'common_entities': common_entities,
            'similarity_score': similarity_score,
            'sentiment_comparison': sentiment_comparison,
            'article_count': len(articles_data),
            'created_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.comparisons.insert_one(comparison_doc)
        
        return jsonify({
            'success': True,
            'message': 'Articles compared successfully',
            'comparison_id': str(result.inserted_id),
            'redirect': url_for('comparison_page', comparison_id=str(result.inserted_id))
        }), 200
        
    except Exception as e:
        print(f"Error comparing articles: {e}")
        return jsonify({'success': False, 'message': f'Error processing articles: {str(e)}'}), 500

def find_common_keywords(articles_data):
    """Find keywords that appear in multiple articles"""
    keyword_map = {}
    
    for article in articles_data:
        for kw in article['keywords']:
            word = kw['word'].lower()
            if word in keyword_map:
                keyword_map[word]['count'] += 1
                keyword_map[word]['total'] += kw['count']
            else:
                keyword_map[word] = {
                    'word': kw['word'],
                    'count': 1,
                    'total': kw['count']
                }
    
    # Return keywords appearing in at least 2 articles
    common = [v for v in keyword_map.values() if v['count'] >= 2]
    return sorted(common, key=lambda x: (x['count'], x['total']), reverse=True)[:10]

def find_common_entities(articles_data):
    """Find named entities that appear in multiple articles"""
    entity_map = {'People': {}, 'Organizations': {}, 'Locations': {}}
    
    for article in articles_data:
        entities = article.get('named_entities', {})
        for category in entity_map.keys():
            for entity in entities.get(category, []):
                entity_lower = entity.lower()
                if entity_lower in entity_map[category]:
                    entity_map[category][entity_lower]['count'] += 1
                else:
                    entity_map[category][entity_lower] = {'name': entity, 'count': 1}
    
    common_entities = {}
    for category, entities in entity_map.items():
        common = [v for v in entities.values() if v['count'] >= 2]
        if common:
            common_entities[category] = sorted(common, key=lambda x: x['count'], reverse=True)
    
    return common_entities

def calculate_similarity_score(articles_data):
    """Calculate semantic similarity between articles using sentence transformers"""
    if len(articles_data) < 2:
        return 0
    
    # Try semantic similarity first (most accurate)
    if semantic_model is not None:
        try:
            # Combine title and summary for each article to get semantic meaning
            texts = []
            for article in articles_data:
                text = f"{article.get('title', '')} {article.get('summary', '')}"
                texts.append(text)
            
            # Generate embeddings
            embeddings = semantic_model.encode(texts)
            
            # Calculate pairwise cosine similarities
            similarities = []
            for i in range(len(embeddings)):
                for j in range(i + 1, len(embeddings)):
                    similarity = cosine_similarity(
                        embeddings[i].reshape(1, -1),
                        embeddings[j].reshape(1, -1)
                    )[0][0]
                    similarities.append(similarity)
            
            if similarities:
                # Average similarity across all pairs, convert to percentage
                avg_similarity = np.mean(similarities) * 100
                return min(100, int(avg_similarity))
        
        except Exception as e:
            print(f"Semantic similarity error: {e}")
            # Fall back to keyword-based method
    
    # Fallback: Keyword-based Jaccard similarity
    keyword_sets = []
    for article in articles_data:
        keywords = set(kw['word'].lower() for kw in article['keywords'])
        keyword_sets.append(keywords)
    
    keyword_similarity = 0
    pair_count = 0
    
    for i in range(len(keyword_sets)):
        for j in range(i + 1, len(keyword_sets)):
            intersection = len(keyword_sets[i] & keyword_sets[j])
            union = len(keyword_sets[i] | keyword_sets[j])
            
            if union > 0:
                jaccard = (intersection / union) * 100
                keyword_similarity += jaccard
                pair_count += 1
    
    if pair_count == 0:
        return 0
    
    avg_keyword_sim = keyword_similarity / pair_count
    
    # Entity overlap
    entity_sets = []
    for article in articles_data:
        entities = set()
        ne = article.get('named_entities', {})
        for category in ['People', 'Organizations', 'Locations']:
            for entity in ne.get(category, []):
                entities.add(entity.lower())
        entity_sets.append(entities)
    
    entity_similarity = 0
    entity_pairs = 0
    
    for i in range(len(entity_sets)):
        for j in range(i + 1, len(entity_sets)):
            intersection = len(entity_sets[i] & entity_sets[j])
            union = len(entity_sets[i] | entity_sets[j])
            
            if union > 0:
                entity_jaccard = (intersection / union) * 100
                entity_similarity += entity_jaccard
                entity_pairs += 1
    
    avg_entity_sim = (entity_similarity / entity_pairs) if entity_pairs > 0 else 0
    
    # Weighted combination
    final_similarity = (avg_keyword_sim * 0.65) + (avg_entity_sim * 0.35)
    
    return min(100, int(final_similarity))

def compare_sentiments(articles_data):
    """Compare sentiment across articles"""
    avg_positive = sum(a['sentiment']['positive'] for a in articles_data) / len(articles_data)
    avg_neutral = sum(a['sentiment']['neutral'] for a in articles_data) / len(articles_data)
    avg_negative = sum(a['sentiment']['negative'] for a in articles_data) / len(articles_data)
    
    return {
        'average': {
            'positive': int(avg_positive),
            'neutral': int(avg_neutral),
            'negative': int(avg_negative)
        },
        'most_positive': max(articles_data, key=lambda x: x['sentiment']['positive'])['title'],
        'most_negative': max(articles_data, key=lambda x: x['sentiment']['negative'])['title']
    }

# Helper functions for analysis

def extract_article_content(url):
    """Extract article text from a given URL using newspaper3k"""
    try:
        article = Article(url, language="en")
        article.download()
        article.parse()
        return article.text.strip()
    except Exception as e:
        print(f"Error extracting article: {e}")
        return ""

def extract_named_entities(text):
    """Extract key named entities using SpaCy NER"""
    if not nlp:
        return {"People": [], "Organizations": [], "Locations": []}
    
    try:
        doc = nlp(text[:10000])
        entities = {"People": [], "Organizations": [], "Locations": []}
        
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                entities["People"].append(ent.text)
            elif ent.label_ == "ORG":
                entities["Organizations"].append(ent.text)
            elif ent.label_ in ["GPE", "LOC"]:
                entities["Locations"].append(ent.text)
        
        for key in entities:
            entities[key] = list(set(entities[key]))[:5]
        
        return entities
    except Exception as e:
        print(f"Error extracting entities: {e}")
        return {"People": [], "Organizations": [], "Locations": []}

def generate_title_from_content(text):
    """Generate a clear, concise title from the article content"""
    text = ' '.join(text.split())
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    
    if not sentences:
        return "Untitled Article"
    
    title = sentences[0]
    skip_prefixes = ['article content extracted', 'this article', 'the article', 'click here', 'read more']
    if any(title.lower().startswith(prefix) for prefix in skip_prefixes):
        title = sentences[1] if len(sentences) > 1 else title
    
    title = re.sub(r'\s+', ' ', title).strip()
    
    if len(title) > 100:
        title = title[:97].rsplit(' ', 1)[0] + '...'
    
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
    
    return title if title else "Untitled Article"

def generate_summary(text, length='medium'):
    """Generate summary with dynamic length control"""
    text = ' '.join(text.split())
    sentences = [s.strip() + '.' for s in re.split(r'[.!?]+', text) if s.strip() and len(s.strip()) > 20]
    
    if not sentences:
        return "No summary available."
    
    if length == 'short':
        num_sentences = min(2, len(sentences))
    elif length == 'long':
        num_sentences = min(7, len(sentences))
    else:
        num_sentences = min(4, len(sentences))
    
    return ' '.join(sentences[:num_sentences])

def extract_keywords(text):
    """Extract keywords from text using improved TF-IDF-like approach"""
    common_words = {'the','a','an','and','or','but','in','on','at','to','for','of','with','is','was','are','were','been','be','have','has','had','do','does','did','will','would','could','should','may','might','must','can','this','that','these','those','i','you','he','she','it','we','they','them','their','what','which','who','when','where','why','how','all','each','every','both','few','more','most','other','some','such','no','nor','not','only','own','same','so','than','too','very','s','t','just','don','now','from','said','about','after','also','been','into','out','over','than','them','then','there','two','up','use','way','who','one','said','make','like','time','year','people','take','come','see','know','get','give','find','tell','ask','work','seem','feel','try','leave','call'}
    
    # Tokenize and clean
    words = text.lower().split()
    word_freq = {}
    
    for word in words:
        # Remove punctuation but keep hyphens in compound words
        word = re.sub(r'[^\w\-]', '', word)
        word = word.strip('-')
        
        # Skip if too short, too long, or common word
        if len(word) > 3 and len(word) < 20 and word not in common_words:
            # Skip numbers
            if not word.isdigit():
                word_freq[word] = word_freq.get(word, 0) + 1
    
    # Get top 12 keywords instead of 8 for better overlap detection
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:12]
    return [{'word': word.capitalize(), 'count': count} for word, count in sorted_words]

def generate_key_points(text):
    """Generate key points from text"""
    sentences = [s.strip() + '.' for s in re.split(r'[.!?]+', text) if s.strip()]
    key_points = []
    
    skip_phrases = ['article content', 'click here', 'read more', 'subscribe', 'follow us']
    
    for sentence in sentences[:15]:
        if len(sentence) > 50 and len(key_points) < 5:
            if not any(phrase in sentence.lower() for phrase in skip_phrases):
                key_points.append(sentence)
    
    return key_points if key_points else ['Content analysis completed successfully.']

def calculate_sentiment(text):
    """Calculate sentiment scores"""
    positive_words = {'good','great','excellent','amazing','wonderful','fantastic','positive','success','successful','happy','joy','love','best','better','improved','growth','achievement','win','winner','breakthrough','innovation','progress','optimistic','hopeful'}
    negative_words = {'bad','terrible','awful','horrible','worst','negative','fail','failure','sad','anger','hate','crisis','disaster','decline','loss','poor','weak','concern','risk','threat','danger','critical','severe'}
    
    words = [re.sub(r'[^a-z]', '', w.lower()) for w in text.split()]
    positive_count = sum(1 for word in words if word in positive_words)
    negative_count = sum(1 for word in words if word in negative_words)
    total_count = positive_count + negative_count
    
    if total_count == 0:
        return {'positive': 40, 'neutral': 50, 'negative': 10}
    
    positive_pct = int((positive_count / total_count) * 100)
    negative_pct = int((negative_count / total_count) * 100)
    neutral_pct = 100 - positive_pct - negative_pct
    
    positive_pct = max(5, min(80, positive_pct))
    negative_pct = max(5, min(50, negative_pct))
    neutral_pct = 100 - positive_pct - negative_pct
    
    return {
        'positive': positive_pct,
        'neutral': max(10, neutral_pct),
        'negative': negative_pct
    }

def determine_crisis_level(content, title):
    """Determine crisis level and provide detailed reason"""
    crisis_keywords = {
        'high': ['emergency','crisis','disaster','catastrophe','urgent','critical','pandemic','war','attack','collapse','fatal','death','kill'],
        'medium': ['warning','alert','concern','risk','threat','danger','issue','problem','significant','major','serious','breach'],
        'low': ['notice','update','change','development','situation','event','announcement','plan']
    }
    
    text_lower = (content + ' ' + title).lower()

    def find_keywords(level):
        return [kw for kw in crisis_keywords[level] if kw in text_lower]

    high_hits = find_keywords('high')
    if high_hits:
        reason = f"This article is flagged as High Crisis because it mentions critical terms such as {', '.join(high_hits[:3])} indicating severe events, potential loss of life, or urgent situations requiring immediate attention."
        return 'High', reason

    medium_hits = find_keywords('medium')
    if medium_hits:
        reason = f"This article is flagged as Medium Crisis because it contains terms like {', '.join(medium_hits[:3])}, indicating potential risks, warnings, or significant developments that could impact people or operations."
        return 'Medium', reason

    low_hits = find_keywords('low')
    if low_hits:
        reason = f"This article is flagged as Low Crisis because it mentions general informational terms such as {', '.join(low_hits[:3])}, suggesting minor updates, announcements, or developments worth monitoring."
        return 'Low', reason

    return 'None', 'This article does not contain explicit crisis-related terms, but it may still hold information of potential significance.'

@app.route('/history')
@login_required
def history():
    try:
        summaries = list(mongo.db.summaries.find(
            {'user_id': session['user_id']}
        ).sort('created_at', -1).limit(50))

        for summary in summaries:
            summary['_id'] = str(summary['_id'])
            if 'created_at' in summary:
                dt = summary['created_at']
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                summary['created_at'] = dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

        return jsonify({'success': True, 'history': summaries}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/analysis/<summary_id>')
@login_required
def analysis_page(summary_id):
    return render_template('analysis.html',
                          user_name=session.get('user_name'),
                          summary_id=summary_id)

@app.route('/comparison/<comparison_id>')
@login_required
def comparison_page(comparison_id):
    return render_template('comparison.html',
                          user_name=session.get('user_name'),
                          comparison_id=comparison_id)

@app.route('/api/summary/<summary_id>')
@login_required
def get_summary_api(summary_id):
    try:
        if not ObjectId.is_valid(summary_id):
            return jsonify({'success': False, 'message': 'Invalid summary ID'}), 400

        summary = mongo.db.summaries.find_one({
            '_id': ObjectId(summary_id),
            'user_id': session['user_id']
        })

        if not summary:
            return jsonify({'success': False, 'message': 'Summary not found'}), 404

        summary['_id'] = str(summary['_id'])
        
        if 'created_at' in summary:
            dt = summary['created_at']
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            summary['created_at'] = dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

        if 'sentiment' not in summary or not summary['sentiment']:
            summary['sentiment'] = {'positive': 50, 'neutral': 40, 'negative': 10}
        
        if 'key_points' not in summary or not summary['key_points']:
            summary['key_points'] = ['Analysis completed successfully.']
        
        if 'keywords' not in summary or not summary['keywords']:
            summary['keywords'] = []
        
        if 'named_entities' not in summary:
            summary['named_entities'] = {"People": [], "Organizations": [], "Locations": []}
        
        if 'crisis_level' not in summary:
            summary['crisis_level'] = 'None'
        
        if 'crisis_description' not in summary:
            summary['crisis_description'] = ''
        
        if 'summary_short' not in summary:
            summary['summary_short'] = summary.get('summary', '')
        if 'summary_medium' not in summary:
            summary['summary_medium'] = summary.get('summary', '')
        if 'summary_long' not in summary:
            summary['summary_long'] = summary.get('summary', '')

        return jsonify({'success': True, 'summary': summary}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/comparison/<comparison_id>')
@login_required
def get_comparison_api(comparison_id):
    try:
        if not ObjectId.is_valid(comparison_id):
            return jsonify({'success': False, 'message': 'Invalid comparison ID'}), 400
        
        comparison = mongo.db.comparisons.find_one({
            '_id': ObjectId(comparison_id),
            'user_id': session['user_id']
        })
        
        if not comparison:
            return jsonify({'success': False, 'message': 'Comparison not found'}), 404
        
        comparison['_id'] = str(comparison['_id'])
        
        if 'created_at' in comparison:
            dt = comparison['created_at']
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            comparison['created_at'] = dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

        if 'articles' in comparison and comparison['articles']:
            for article in comparison['articles']:
                if '_id' in article:
                    article['_id'] = str(article['_id'])

        return jsonify({'success': True, 'comparison': comparison}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/summary/<summary_id>')
@login_required
def view_summary(summary_id):
    return redirect(url_for('analysis_page', summary_id=summary_id))

@app.route('/delete-history/<summary_id>', methods=['DELETE'])
@login_required
def delete_history(summary_id):
    """Delete a summary from history - matches the dashboard route"""
    try:
        if not ObjectId.is_valid(summary_id):
            return jsonify({'success': False, 'message': 'Invalid summary ID'}), 400

        result = mongo.db.summaries.delete_one({
            '_id': ObjectId(summary_id),
            'user_id': session['user_id']
        })

        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Analysis deleted successfully'}), 200

        return jsonify({'success': False, 'message': 'Analysis not found'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/delete-summary/<summary_id>', methods=['DELETE'])
@login_required
def delete_summary(summary_id):
    """Alternative endpoint for backwards compatibility"""
    return delete_history(summary_id)

def generate_pdf_summary(summary, output):
    """Generate a professional, clean, and visually balanced PDF summary report."""

    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=60,
        leftMargin=60,
        topMargin=60,
        bottomMargin=50
    )

    elements = []
    styles = getSampleStyleSheet()

    # === STYLES ===
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=26,
        textColor=colors.HexColor('#4B0082'),
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=4,
        leading=30
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#9370DB'),
        alignment=TA_CENTER,
        spaceAfter=25,
        fontName='Helvetica-Oblique'
    )

    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#4B0082'),
        spaceBefore=20,
        spaceAfter=10,
        fontName='Helvetica-Bold',
        borderPadding=(6, 6, 6, 6),
        leftIndent=0,
    )

    article_title = ParagraphStyle(
        'ArticleTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#4B0082'),
        spaceAfter=10,
        leading=22,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold'
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
        alignment=TA_JUSTIFY,
        leading=16,
        spaceAfter=10
    )

    meta_style = ParagraphStyle(
        'Meta',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#6A5ACD'),
        spaceAfter=15,
        alignment=TA_LEFT,
        fontName='Helvetica-Oblique'
    )

    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#9370DB'),
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
        leading=10
    )

    # === HEADER ===
    header_data = [
        [Paragraph("NEWSLYTICS", title_style)],
        [Paragraph("Where Information meets Intelligence.", subtitle_style)]
    ]
    
    header_table = Table(header_data, colWidths=[6.8 * inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F4ECFF')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (0, 0), 15),
        ('BOTTOMPADDING', (0, 1), (0, 1), 12)
    ]))
    
    elements.append(header_table)
    elements.append(Spacer(1, 0.25 * inch))

    # === ARTICLE TITLE ===
    elements.append(Paragraph(summary.get('title', 'Untitled Article'), article_title))
    meta_text = (
        f"<b>Source:</b> {summary.get('source', 'Unknown')} &nbsp;&nbsp;&nbsp; "
        f"<b>Date:</b> {summary.get('created_at', datetime.now(timezone.utc)).strftime('%B %d, %Y at %I:%M %p')}"
    )
    elements.append(Paragraph(meta_text, meta_style))
    elements.append(Spacer(1, 0.1 * inch))

    divider = Table([['']], colWidths=[6.8 * inch])
    divider.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 1.5, colors.HexColor('#D8BFD8'))]))
    elements.append(divider)
    elements.append(Spacer(1, 0.2 * inch))

    # === CRISIS ALERT ===
    crisis_level = summary.get('crisis_level', 'None')
    if crisis_level and crisis_level.lower() != 'none':
        colorset = {
            'high': ('#FFEBEE', '#EF5350'),
            'medium': ('#FFF3E0', '#FFB74D'),
            'low': ('#E8F5E9', '#66BB6A')
        }
        bg, border = colorset.get(crisis_level.lower(), ('#F0F0F0', '#CCCCCC'))
        crisis_para = Paragraph(
            f"<b>{crisis_level.upper()} CRISIS ALERT</b><br/><br/>{summary.get('crisis_description', '')}",
            body_style
        )
        box = Table([[crisis_para]], colWidths=[6.8 * inch])
        box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg)),
            ('BOX', (0, 0), (-1, -1), 2, colors.HexColor(border)),
            ('PADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(box)
        elements.append(Spacer(1, 0.25 * inch))

    # === SUMMARY ===
    elements.append(Paragraph("Executive Summary", section_heading))
    summary_text = summary.get('summary', 'No summary available')
    summary_box = Table([[Paragraph(summary_text, body_style)]], colWidths=[6.8 * inch])
    summary_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FBF8FF')),
        ('PADDING', (0, 0), (-1, -1), 15),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E6E6FA'))
    ]))
    elements.append(summary_box)
    elements.append(Spacer(1, 0.25 * inch))

    # === KEY INSIGHTS ===
    key_points = summary.get('key_points', [])
    if key_points:
        elements.append(Paragraph("Key Insights", section_heading))
        for i, point in enumerate(key_points[:5], 1):
            p = Paragraph(f"<b>{i}.</b> {point}", body_style)
            box = Table([[p]], colWidths=[6.8 * inch])
            box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8F4FF')),
                ('PADDING', (0, 0), (-1, -1), 10),
            ]))
            elements.append(box)
            elements.append(Spacer(1, 0.1 * inch))

    # === SENTIMENT ANALYSIS ===
    sentiment = summary.get('sentiment', {})
    if sentiment:
        elements.append(Paragraph("Sentiment Analysis", section_heading))
        sentiment_table_data = [['Sentiment', 'Score', 'Visualization']]

        def make_bar(value, color):
            bar = Table([['']], colWidths=[(value / 100) * 2.8 * inch], rowHeights=[10])
            bar.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(color))]))
            return bar

        sentiment_table_data.append(['Positive', f"{sentiment.get('positive', 0)}%", make_bar(sentiment.get('positive', 0), '#66BB6A')])
        sentiment_table_data.append(['Neutral', f"{sentiment.get('neutral', 0)}%", make_bar(sentiment.get('neutral', 0), '#9370DB')])
        sentiment_table_data.append(['Negative', f"{sentiment.get('negative', 0)}%", make_bar(sentiment.get('negative', 0), '#EF5350')])

        sentiment_table = Table(sentiment_table_data, colWidths=[1.3 * inch, 0.8 * inch, 2.8 * inch])
        sentiment_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EDE6FF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#4B0082')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#E6E6FA')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
        ]))
        elements.append(sentiment_table)
        elements.append(Spacer(1, 0.25 * inch))

    # === KEYWORDS ===
    keywords = summary.get('keywords', [])
    if keywords:
        elements.append(Paragraph("Key Terms", section_heading))
        kw_text = " • ".join([
            f"{kw.get('word', kw) if isinstance(kw, dict) else kw}"
            for kw in keywords[:8]
        ])
        elements.append(Paragraph(kw_text, body_style))
        elements.append(Spacer(1, 0.2 * inch))

    # === NAMED ENTITIES ===
    entities = summary.get('named_entities', {})
    if entities:
        elements.append(Paragraph("Named Entities", section_heading))
        for label, names in entities.items():
            if names:
                elements.append(Paragraph(f"<b>{label}:</b> {', '.join(names)}", body_style))
        elements.append(Spacer(1, 0.25 * inch))

    # === FULL CONTENT ===
    elements.append(PageBreak())
    elements.append(Paragraph("Full Article Content", section_heading))
    elements.append(Spacer(1, 0.1 * inch))

    for para in summary.get('full_content', 'No content available').split('\n\n'):
        if para.strip():
            elements.append(Paragraph(para.strip(), body_style))
            elements.append(Spacer(1, 0.1 * inch))

    # === FOOTER ===
    elements.append(Spacer(1, 0.4 * inch))
    footer_divider = Table([['']], colWidths=[6.8 * inch])
    footer_divider.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, -1), 1, colors.HexColor('#D8BFD8'))]))
    elements.append(footer_divider)
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph("Generated by NEWSLYTICS • The Smarter Way to Stay Informed", footer_style))
    elements.append(Paragraph(datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC"), footer_style))

    doc.build(elements)
    return output

@app.route('/export-summary/<summary_id>')
@login_required
def export_summary(summary_id):
    try:
        if not ObjectId.is_valid(summary_id):
            return jsonify({'success': False, 'message': 'Invalid summary ID'}), 400

        summary = mongo.db.summaries.find_one({
            '_id': ObjectId(summary_id),
            'user_id': session['user_id']
        })

        if not summary:
            return jsonify({'success': False, 'message': 'Summary not found'}), 404

        export_format = request.args.get('format', 'text')
        
        if export_format == 'pdf':
            output = io.BytesIO()
            generate_pdf_summary(summary, output)
            output.seek(0)
            
            filename = f"newslytics_summary_{summary_id}.pdf"
            return send_file(
                output,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
        else:
            export_text = f"""
NEWSLYTICS SUMMARY EXPORT
========================

Title: {summary.get('title', 'Untitled')}
Source: {summary.get('source', 'Unknown')}
Date: {summary.get('created_at', datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M:%S')}

SUMMARY
-------
{summary.get('summary', 'No summary available')}

KEY POINTS
----------
"""
            if summary.get('key_points'):
                for i, point in enumerate(summary['key_points'], 1):
                    export_text += f"{i}. {point}\n"
            
            export_text += f"""

NAMED ENTITIES
--------------
"""
            if summary.get('named_entities'):
                entities = summary['named_entities']
                if entities.get('People'):
                    export_text += f"People: {', '.join(entities['People'])}\n"
                if entities.get('Organizations'):
                    export_text += f"Organizations: {', '.join(entities['Organizations'])}\n"
                if entities.get('Locations'):
                    export_text += f"Locations: {', '.join(entities['Locations'])}\n"

            export_text += f"""
SENTIMENT ANALYSIS
-----------------
Positive: {summary.get('sentiment', {}).get('positive', 0)}%
Neutral: {summary.get('sentiment', {}).get('neutral', 0)}%
Negative: {summary.get('sentiment', {}).get('negative', 0)}%

KEYWORDS
--------
"""
            if summary.get('keywords'):
                for kw in summary['keywords']:
                    if isinstance(kw, dict):
                        export_text += f"- {kw.get('word', 'N/A')} ({kw.get('count', 0)} occurrences)\n"
                    else:
                        export_text += f"- {kw}\n"

            export_text += f"""

FULL CONTENT
-----------
{summary.get('full_content', 'No content available')}

========================
Generated by Newslytics
"""

            output = io.BytesIO()
            output.write(export_text.encode('utf-8'))
            output.seek(0)

            filename = f"newslytics_summary_{summary_id}.txt"
            return send_file(output, as_attachment=True, download_name=filename, mimetype='text/plain')

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
# Add these imports at the top
from deep_translator import GoogleTranslator
import traceback

@app.route('/api/translate', methods=['POST'])
@login_required
def translate_text():
    """Translate text to target language"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        target_language = data.get('target_language', 'en').strip()
        
        print(f"Translation request - Target: {target_language}, Text length: {len(text)}")
        
        if not text:
            return jsonify({'success': False, 'message': 'Text is required'}), 400
        
        if target_language == 'en':
            return jsonify({'success': True, 'translated_text': text}), 200
        
        # Language code mapping (deep-translator uses different codes)
        language_map = {
            'zh': 'zh-CN',  # Chinese Simplified
            'ja': 'ja',     # Japanese
            'ko': 'ko',     # Korean
            'es': 'es',     # Spanish
            'fr': 'fr',     # French
            'de': 'de',     # German
            'it': 'it',     # Italian
            'pt': 'pt',     # Portuguese
            'hi': 'hi',     # Hindi
            'ar': 'ar',     # Arabic
            'ru': 'ru',      # Russian
            'bn': 'bn',      # Bengali
            'te': 'te',      # Telugu
            'mr': 'mr',      # Marathi
            'ta': 'ta',      # Tamil
            'ur': 'ur',      # Urdu
            'gu': 'gu',      # Gujarati
            'kn': 'kn',      # Kannada
            'ml': 'ml',      # Malayalam
            'pa': 'pa'
        }
        
        target_lang = language_map.get(target_language, target_language)
        
        # Split into manageable chunks
        max_chunk_size = 4500
        translated_chunks = []
        
        # Split by sentences to avoid breaking in the middle
        sentences = text.split('. ')
        current_chunk = ''
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 2 <= max_chunk_size:
                current_chunk += sentence + '. '
            else:
                if current_chunk:
                    translated_chunks.append(current_chunk.strip())
                current_chunk = sentence + '. '
        
        if current_chunk:
            translated_chunks.append(current_chunk.strip())
        
        # Translate each chunk
        final_translation = []
        for i, chunk in enumerate(translated_chunks):
            try:
                print(f"Translating chunk {i+1}/{len(translated_chunks)}")
                translator = GoogleTranslator(source='en', target=target_lang)
                translated = translator.translate(chunk)
                final_translation.append(translated)
            except Exception as chunk_error:
                print(f"Chunk {i+1} error: {chunk_error}")
                # If translation fails, keep original text for this chunk
                final_translation.append(chunk)
        
        translated_text = ' '.join(final_translation)
        
        return jsonify({
            'success': True,
            'translated_text': translated_text,
            'chunks_processed': len(translated_chunks)
        }), 200
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Translation error: {e}")
        print(f"Full traceback: {error_trace}")
        return jsonify({
            'success': False,
            'message': f'Translation failed: {str(e)}'
        }), 500

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/check-session')
def check_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'user_name': session.get('user_name'),
            'user_email': session.get('user_email')
        })
    return jsonify({'logged_in': False})

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'message': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'message': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True)