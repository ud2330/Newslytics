# Newslytics

A Flask-based intelligent news analysis platform that extracts, summarizes, compares, and translates news articles. Newslytics supports URLs and file uploads, performs NLP analysis, generates insights, and exports professional PDF reports.

---

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

---

## Tech Stack

* Python, Flask
* MongoDB + Flask-PyMongo
* spaCy (`en_core_web_sm`)
* Sentence-Transformers (`all-MiniLM-L6-v2`)
* newspaper3k
* ReportLab (PDF)
* OCR: Tesseract + Pillow
* PyPDF2, python-docx, deep-translator

---

## Project Structure

```
app.py
templates/
static/
uploads/
requirements.txt
README.md
```

---
## Clone the Repository

```bash
git clone https://github.com/ud2330/Newslytics.git
cd Newslytics
```


## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Install spaCy model

```bash
python -m spacy download en_core_web_sm
```

### 3. Install system tools (for OCR)

```bash
sudo apt-get install tesseract-ocr
```

Windows users should install Tesseract from:
[https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)

### 4. Run MongoDB

You can use:

* Local MongoDB
* MongoDB Atlas (cloud)

### 5. Start the application

```bash
python app.py
```

Visit the application at:
[http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## Environment Variables

Set these before running:

```
SECRET_KEY=your-secret-key
MONGO_URI=mongodb://localhost:27017/newslytics
UPLOAD_FOLDER=uploads
```

---

## Core Endpoints

* `POST /signup` — Create account
* `POST /login` — Login
* `POST /analyze` — Analyze article (URL or Text)
* `POST /compare-articles` — Compare multiple articles
* `GET /api/summary/<id>` — Return summary
* `GET /export-summary/<id>?format=pdf` — Export report
* `POST /api/translate` — Translate text
* `GET /history` — User analysis history

---

## File Support

Supported file formats:

* `.txt`
* `.pdf`
* `.docx`
* `.jpg`, `.jpeg`, `.png` (via OCR)

Max upload size: **16 MB**

---

## Security Notes

* Use a strong `SECRET_KEY` in production
* Use authenticated MongoDB users
* Enable HTTPS
* Add rate limiting to prevent heavy abuse
* Restrict file uploads where needed

---

If you want, I can also generate:

* A professional **project logo**
* A **contribution guide**
* A **Dockerfile** for deployment
* A **requirements freeze** with pinned versions
* A **full API documentation page**
