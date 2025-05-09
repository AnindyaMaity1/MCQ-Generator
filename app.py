from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import sqlite3
import os
from functools import wraps
import pdfplumber
import docx
from fpdf import FPDF
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from dotenv import load_dotenv
import urllib.parse

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configuration from .env
app.secret_key = os.getenv('SECRET_KEY')  # Secret key for session & flash messages
OUTPUT_FOLDER = "results"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SCHOOL_INFO = {
    "name": "Greenfield Academy",
    "address": "Springfield, IL 62704",
    "email": "info@greenfieldacademy.com",
    "phone": "222 555 7777"
}

# LangChain LLM setup using Groq
llm = ChatOpenAI(
    model="llama3-70b-8192",
    openai_api_key=os.getenv('OPENAI_API_KEY'),
    openai_api_base=os.getenv('OPENAI_API_BASE'),
    temperature=0.0
)

# Prompt template for MCQ generation
mcq_prompt = PromptTemplate(
    input_variables=["context", "num_questions"],
    template="""You are an AI assistant helping the user generate multiple-choice questions (MCQs) from the text below:

Text:
{context}

Generate {num_questions} MCQs. Each should include:
- A clear question
- Four answer options labeled A, B, C, and D
- The correct answer clearly indicated at the end

Format:
## MCQ
Question: [question]
A) [option A]
B) [option B]
C) [option C]
D) [option D]
Correct Answer: [correct option]
"""
)

mcq_chain = LLMChain(llm=llm, prompt=mcq_prompt)

# Extract text from uploaded file
def extract_text(file_path):
    ext = file_path.rsplit('.', 1)[-1].lower()
    if ext == "pdf":
        with pdfplumber.open(file_path) as pdf:
            return ''.join([p.extract_text() for p in pdf.pages if p.extract_text()])
    elif ext == "docx":
        doc = docx.Document(file_path)
        return ' '.join([para.text for para in doc.paragraphs])
    elif ext == "txt":
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        raise ValueError("Unsupported file type")
    
# Save MCQs to .txt
def save_txt(mcqs, filename):
    path = os.path.join(OUTPUT_FOLDER, filename)

    header = (
        f"{SCHOOL_INFO['name']}\n"
        f"{SCHOOL_INFO['address']}\n"
        f"{SCHOOL_INFO['email']}\n"
        f"{SCHOOL_INFO['phone']}\n\n"
        "Name: ____________________    Subject: ________________    Grade Level: ______\n\n"
    )

    sections = {"Multiple Choice": [], "True or False": [], "Fill in the Blank": []}
    current_section = "Multiple Choice"
    for q in mcqs.split("## MCQ"):
        q = q.strip()
        if not q:
            continue
        if "True or False" in q:
            current_section = "True or False"
        elif "Fill in the Blank" in q:
            current_section = "Fill in the Blank"
        sections[current_section].append(q)

    body = ""
    for section, qlist in sections.items():
        if qlist:
            body += section + ":\n"
            for idx, q in enumerate(qlist, 1):
                body += f"{idx}. {q.strip()}\n\n"

    with open(path, 'w', encoding='utf-8') as f:
        f.write(header + body.strip())

    return filename

# Save MCQs to PDF
def save_pdf(mcqs, filename):
    path = os.path.join(OUTPUT_FOLDER, filename)
    width, height = A4
    c = canvas.Canvas(path, pagesize=A4)

    # Header styling
    c.setFillColorRGB(0.4, 0.8, 0.7)
    c.rect(0, height - 100, width, 100, fill=1)

    # Placeholder logo
    c.setFillColor(colors.white)
    c.circle(50, height - 50, 30, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(50, height - 52, "YOUR")
    c.drawCentredString(50, height - 64, "LOGO")

    # School details
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.white)
    c.drawRightString(width - 40, height - 40, SCHOOL_INFO["name"])
    c.drawRightString(width - 40, height - 55, SCHOOL_INFO["address"])
    c.drawRightString(width - 40, height - 70, SCHOOL_INFO["email"])
    c.drawRightString(width - 40, height - 85, SCHOOL_INFO["phone"])

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.green)
    c.drawCentredString(width / 2, height - 120, "QUIZ PAPER")

    # Student lines
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.black)
    c.drawString(50, height - 150, "Name:")
    c.drawString(200, height - 150, "Subject:")
    c.drawString(370, height - 150, "Grade Level:")
    c.line(90, height - 152, 180, height - 152)
    c.line(255, height - 152, 345, height - 152)
    c.line(455, height - 152, 530, height - 152)

    # MCQ Content
    mcq_blocks = [m.strip() for m in mcqs.split("## MCQ") if m.strip()]
    y = height - 180
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Multiple Choice:")
    y -= 20
    c.setFont("Helvetica", 11)

    for block in mcq_blocks:
        lines = block.split('\n')
        for line in lines:
            if y < 100:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 11)
            c.drawString(60, y, line.strip())
            y -= 15
        y -= 10

    c.save()
    return filename



# Upload & process file route
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files or request.files['file'].filename == '':
        return "No file selected", 400

    file = request.files['file']
    file_path = os.path.join(OUTPUT_FOLDER, file.filename)
    file.save(file_path)

    try:
        text = extract_text(file_path)
        if not text.strip():
            return "No text extracted from file.", 400

        num_questions = int(request.form.get('num_questions', 5))
        mcqs = mcq_chain.run({"context": text, "num_questions": num_questions}).strip()

        base_name = os.path.splitext(file.filename)[0]
        txt_filename = f"generated_mcqs_{base_name}.txt"
        pdf_filename = f"generated_mcqs_{base_name}.pdf"

        save_txt(mcqs, txt_filename)
        save_pdf(mcqs, pdf_filename)

        return render_template('result.html', mcqs=mcqs, txt_filename=txt_filename, pdf_filename=pdf_filename)
    
    except Exception as e:
        return f"Error: {str(e)}", 500

# File download route
@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)

# ---------- Utility ----------

def init_db():
    if not os.path.exists("users.db"):
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute(''' 
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fullname TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

# ---------- Login Required Decorator ----------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please log in first", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- Routes ----------

@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['user'] = user[1]  # Store the full name
            return jsonify({'status': 'success'})
        else:
            flash("Invalid email or password.", "danger")
            return jsonify({'status': 'error'})

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirmpassword']

        if password != confirm:
            flash("Passwords do not match!", "danger")
            return redirect(url_for('register'))

        try:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (fullname, email, password) VALUES (?, ?, ?)",
                           (fullname, email, password))
            conn.commit()
            conn.close()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/index')
@login_required
def index():
    return render_template('index.html', username=session['user'])

@app.route('/about')
@login_required
def about():
    return render_template('about.html', username=session['user'])

@app.route('/question-papers')
@login_required
def question_papers():
    return render_template('question-papers.html', username=session['user'])

@app.route('/contact')
@login_required
def contact():
    return render_template('contact.html', username=session['user'])

@app.route('/developedby')
@login_required
def developedby():
    return render_template('developedby.html', username=session['user'])

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({'status': 'success', 'message': 'Logged out successfully'})


# ---------- Run ----------

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
