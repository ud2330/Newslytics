# Newslytics

A Flask-based intelligent news analysis platform that extracts, summarizes, compares, and translates news articles. Newslytics supports URLs and file uploads, performs NLP analysis, generates insights, and exports professional PDF reports.

## Features

* User Auth (Signup, Login, Sessions)
* Extract news from URLs or uploaded files (PDF, DOCX, TXT, Images via OCR)
* NLP Analysis
  * Named Entities (spaCy)
  * Keywords & Key Insights
  * Multi-length Summaries
  * Sentiment Scores
  * Crisis-Level Detection
* Compare up to 5 articles

  * Semantic similarity (Sentence Transformers)
  * Keyword/Entity overlap fallback
* Export PDF / TXT reports
* Translate text into multiple languages
* History tracking (MongoDB)

## Tech Stack

* Python, Flask
* MongoDB + Flask-PyMongo
* spaCy (`en_core_web_sm`)
* Sentence-Transformers (`all-MiniLM-L6-v2`)
* newspaper3k
* ReportLab (PDF)
* OCR: Tesseract + Pillow
* PyPDF2, python-docx, deep-translator

## Project Structure

```
app.py
templates/
static/
uploads/
requirements.txt
README.md
```
  
## Setup

### **1. Install dependencies**

```bash
pip install -r requirements.txt
```

### **2. Install spaCy model**

```bash
python -m spacy download en_core_web_sm
```

### **3. Install system tools**

```bash
sudo apt-get install tesseract-ocr
```

### **4. Run MongoDB**

Use local or cloud (MongoDB Atlas).

### **5. Start the app**

```bash
python app.py
```

Visit: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

## Environment Variables

Set these before running:

```
SECRET_KEY=your-secret-key
MONGO_URI=mongodb://localhost:27017/newslytics
UPLOAD_FOLDER=uploads
```

## Core Endpoints

* `POST /signup` — Create account
* `POST /login` — Login
* `POST /analyze` — Analyze article (URL/Text)
* `POST /compare-articles` — Compare multiple articles
* `GET /api/summary/<id>` — Get summary
* `GET /export-summary/<id>?format=pdf` — Export report
* `POST /api/translate` — Translate text
* `GET /history` — User history

## File Support

* `.txt`, `.pdf`, `.docx`, `.jpg`, `.jpeg`, `.png`
* Max file: **16MB**
* OCR enabled for images

## Security Notes

* Use strong `SECRET_KEY`
* Use authenticated MongoDB in production
* Add rate limiting for analysis endpoints
* Prefer HTTPS + secure session cookies

## To do

* Implement password reset with secure email token
* Add progress indicators for long operations (OCR, PDF generation)
* Improve sentiment analysis using an ML model instead of keyword matching
* Save article embeddings to the database to speed up comparisons
* Add Docker Compose (Flask + MongoDB) for easy deployment
