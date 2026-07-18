import os
import json
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from models import db, User, Quiz, Question, Result
from generate_custom_quiz import generate_quiz_with_ollama, detect_subject_and_topic, get_doc_custom_metadata, save_doc_custom_metadata

app = Flask(__name__)
app.config['SECRET_KEY'] = 'quiz_secret_key_change_in_production_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ─────────────────────────────────────────
# Auth decorator
# ─────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        if not identifier or not password:
            flash('Please fill in all fields.', 'danger')
            return render_template('login.html')

        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = (user.username == 'admin')
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        errors = []
        if not username or not email or not password or not confirm:
            errors.append('All fields are required.')
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if '@' not in email or '.' not in email:
            errors.append('Please enter a valid email address.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')
        if User.query.filter_by(username=username).first():
            errors.append('Username already taken.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('register.html',
                                   username=username, email=email)

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    attempted_ids = set(
        r.quiz_id for r in Result.query.filter_by(user_id=session['user_id']).all()
    )
    return render_template('dashboard.html',
                           quizzes=quizzes,
                           attempted_ids=attempted_ids)


@app.route('/api/ollama/status')
@login_required
def ollama_status():
    import requests
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=1.5)
        if response.status_code == 200:
            models_data = response.json().get('models', [])
            models = [m['name'] for m in models_data]
            return jsonify({'running': True, 'models': models})
        else:
            return jsonify({'running': False, 'models': [], 'error': f'Ollama status code {response.status_code}'})
    except Exception as e:
        return jsonify({'running': False, 'models': [], 'error': str(e)})


@app.route('/generate_quiz', methods=['POST'])
@login_required
def generate_quiz():
    topic = request.form.get('topic', '').strip()
    num_questions = request.form.get('num_questions', 10, type=int)
    num_questions = min(25, max(3, num_questions))
    
    if not topic:
        flash('Please enter a topic or keyword to generate quiz questions.', 'danger')
        return redirect(url_for('dashboard'))
        
    try:
        history_subject = session.get('last_subject')
        history_topic = session.get('last_topic')
        
        # Determine subject and topic and save to memory
        detected_subject, detected_topic = detect_subject_and_topic(topic, history_topic, history_subject)
        session['last_subject'] = detected_subject
        session['last_topic'] = detected_topic
        
        quiz_id = generate_quiz_with_ollama(
            topic=topic,
            num_questions=num_questions,
            history_subject=history_subject,
            history_topic=history_topic
        )
        flash(f'Success! Generated a local quiz about "{detected_topic}" under Subject: {detected_subject}.', 'success')
        return redirect(url_for('quiz', quiz_id=quiz_id))
    except Exception as e:
        flash(f'Error generating quiz: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


@app.route('/admin/knowledge-base', methods=['GET'])
@login_required
def knowledge_base():
    files = []
    if os.path.exists(DOCUMENTS_DIR):
        for filename in os.listdir(DOCUMENTS_DIR):
            if filename == "metadata.json":
                continue
            file_path = os.path.join(DOCUMENTS_DIR, filename)
            if os.path.isfile(file_path):
                size_kb = round(os.path.getsize(file_path) / 1024, 1)
                mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                custom = get_doc_custom_metadata(filename)
                files.append({
                    'name': filename,
                    'size': size_kb,
                    'mtime': mtime,
                    'subject': custom.get('subject', 'Auto-detect'),
                    'topic': custom.get('topic', 'Auto-detect')
                })
    return render_template('knowledge_base.html', files=files)


@app.route('/admin/knowledge-base/upload', methods=['POST'])
@login_required
def kb_upload():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('knowledge_base'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('knowledge_base'))
    
    from werkzeug.utils import secure_filename
    filename = secure_filename(file.filename)
    if filename.lower().endswith(('.pdf', '.docx', '.txt', '.md')):
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        file_path = os.path.join(DOCUMENTS_DIR, filename)
        file.save(file_path)
        
        # Validate if the document contains readable text
        from generate_custom_quiz import load_single_document, get_or_build_vector_store
        try:
            docs = load_single_document(filename)
            total_len = sum(len(d.page_content.strip()) for d in docs)
            if total_len == 0:
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Upload failed: The document "{filename}" contains no readable text.', 'danger')
                return redirect(url_for('knowledge_base'))
            
            # Print upload logs
            print(f"[Upload Audit] Filename: {filename}")
            print(f"[Upload Audit] Extracted text length: {total_len} characters")
            print(f"[Upload Audit] Number of pages: {len(docs)}")
            
            # Extract segment for classification
            segment = ""
            if filename.lower().endswith('.pdf'):
                for page in docs[:2]:
                    segment += page.page_content + "\n"
            else:
                segment = docs[0].page_content[:4000]
                
            # Classify automatically using Ollama (falls back to local rules)
            from generate_custom_quiz import classify_document_with_ollama
            subject, chapter, topics, keywords, difficulty = classify_document_with_ollama(filename, segment)
            save_doc_custom_metadata(filename, subject, topics, chapter, keywords, difficulty)
            
            # Trigger FAISS index rebuild/update immediately
            print(f"[Upload Audit] Rebuilding/Updating FAISS index...")
            vector_store = get_or_build_vector_store()
            if not vector_store:
                raise Exception("Failed to rebuild or update FAISS index.")
                
            num_docs = len(vector_store.docstore._dict)
            print(f"[Upload Audit] Indexing success! FAISS document count: {num_docs}")
            
            flash(f'Successfully uploaded and auto-classified "{filename}" under Subject: {subject}.', 'success')
        except Exception as e:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            flash(f'Upload failed: Error parsing or indexing document. {str(e)}', 'danger')
            return redirect(url_for('knowledge_base'))
    else:
        flash('Unsupported file type. Please upload PDF, DOCX, TXT, or MD.', 'danger')
    return redirect(url_for('knowledge_base'))


@app.route('/admin/knowledge-base/delete/<filename>', methods=['POST'])
@login_required
def kb_delete(filename):
    from werkzeug.utils import secure_filename
    filename = secure_filename(filename)
    file_path = os.path.join(DOCUMENTS_DIR, filename)
    
    # 1. Delete from DB metadata first
    from models import DocumentMetadata
    try:
        meta = DocumentMetadata.query.filter_by(filename=filename).first()
        if meta:
            db.session.delete(meta)
            db.session.commit()
    except Exception as e:
        print("[Delete DB Metadata Error]:", str(e))
        
    # 2. Delete file
    deleted_file = False
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            deleted_file = True
        except Exception as e:
            flash(f'Error deleting file: {str(e)}', 'danger')
            return redirect(url_for('knowledge_base'))
            
    # 3. Rebuild vector store
    if deleted_file:
        from generate_custom_quiz import get_or_build_vector_store
        try:
            print(f"[Delete Audit] File '{filename}' deleted. Rebuilding FAISS index...")
            get_or_build_vector_store()
            flash(f'Successfully deleted "{filename}" and rebuilt vector store.', 'info')
        except Exception as e:
            flash(f'Successfully deleted file, but vector store rebuild failed: {str(e)}', 'warning')
    else:
        flash('File not found.', 'danger')
        
    return redirect(url_for('knowledge_base'))


# ─────────────────────────────────────────
# Quiz routes
# ─────────────────────────────────────────
@app.route('/quiz/<int:quiz_id>')
@login_required
def quiz(quiz_id):
    q = Quiz.query.get_or_404(quiz_id)
    if not q.questions:
        flash('This quiz has no questions yet.', 'warning')
        return redirect(url_for('dashboard'))
    return render_template('quiz.html', quiz=q)


@app.route('/submit', methods=['POST'])
@login_required
def submit():
    quiz_id = request.form.get('quiz_id', type=int)
    time_taken = request.form.get('time_taken', 0, type=int)

    q = Quiz.query.get_or_404(quiz_id)
    questions = q.questions

    correct = 0
    answers = {}
    for question in questions:
        key = f'answer_{question.id}'
        selected = request.form.get(key, '')
        answers[str(question.id)] = {
            'selected': selected,
            'correct': question.correct_answer,
            'question': question.question_text,
            'options': [question.option1, question.option2,
                        question.option3, question.option4],
            'is_correct': selected == question.correct_answer,
            'explanation': getattr(question, 'explanation', None)
        }
        if selected == question.correct_answer:
            correct += 1

    # Extract diagnostics if present
    diagnostics = None
    if q.description and "---DIAGNOSTICS---" in q.description:
        try:
            parts = q.description.split("---DIAGNOSTICS---")
            diagnostics = json.loads(parts[1].strip())
        except Exception:
            pass
            
    if diagnostics:
        answers["_diagnostics"] = diagnostics

    total = len(questions)
    score_pct = round((correct / total) * 100, 1) if total > 0 else 0

    result = Result(
        user_id=session['user_id'],
        quiz_id=quiz_id,
        score=score_pct,
        correct_answers=correct,
        total_questions=total,
        time_taken=time_taken,
        answers_json=json.dumps(answers)
    )
    db.session.add(result)
    db.session.commit()

    return render_template('result.html',
                           quiz=q,
                           result=result,
                           answers=answers,
                           correct=correct,
                           total=total,
                           score=score_pct)


# ─────────────────────────────────────────
# Profile & History
# ─────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.get_or_404(session['user_id'])

    if request.method == 'POST':
        new_email = request.form.get('email', '').strip().lower()
        new_username = request.form.get('username', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')

        errors = []
        if not user.check_password(current_password):
            errors.append('Current password is incorrect.')
        if new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                errors.append('Username already taken.')
        if new_email != user.email:
            if User.query.filter_by(email=new_email).first():
                errors.append('Email already in use.')
        if new_password and len(new_password) < 6:
            errors.append('New password must be at least 6 characters.')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            user.username = new_username
            user.email = new_email
            if new_password:
                user.set_password(new_password)
            db.session.commit()
            session['username'] = user.username
            flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))

    stats = user.get_stats()
    recent_results = (Result.query
                      .filter_by(user_id=user.id)
                      .order_by(Result.timestamp.desc())
                      .limit(5).all())
    return render_template('profile.html',
                           user=user, stats=stats,
                           recent_results=recent_results)


@app.route('/history')
@login_required
def history():
    user_results = (Result.query
                    .filter_by(user_id=session['user_id'])
                    .order_by(Result.timestamp.desc())
                    .all())
    return render_template('history.html', results=user_results)


@app.route('/result/<int:result_id>')
@login_required
def result_detail(result_id):
    result = Result.query.get_or_404(result_id)
    if result.user_id != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('history'))
    answers = json.loads(result.answers_json)
    return render_template('result_detail.html',
                           result=result,
                           quiz=result.quiz,
                           answers=answers)


# ─────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────
@app.route('/leaderboard')
@login_required
def leaderboard():
    from sqlalchemy import func
    leaders = (
        db.session.query(
            User.username,
            func.count(Result.id).label('total'),
            func.avg(Result.score).label('avg_score'),
            func.max(Result.score).label('best_score')
        )
        .join(Result, User.id == Result.user_id)
        .group_by(User.id)
        .order_by(func.avg(Result.score).desc())
        .limit(10)
        .all()
    )
    return render_template('leaderboard.html', leaders=leaders)


# ─────────────────────────────────────────
# Admin Panel
# ─────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin():
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    total_users = User.query.count()
    total_results = Result.query.count()
    return render_template('admin.html',
                           quizzes=quizzes,
                           total_users=total_users,
                           total_results=total_results)


@app.route('/admin/diagnostics')
@admin_required
def admin_diagnostics():
    from generate_custom_quiz import get_rag_diagnostics_report
    try:
        report = get_rag_diagnostics_report()
    except Exception as e:
        report = {"error": str(e)}
    return render_template('diagnostics.html', report=report)


@app.route('/admin/quiz/create', methods=['GET', 'POST'])
@admin_required
def create_quiz():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        time_limit = request.form.get('time_limit', 0, type=int)

        if not title or not description:
            flash('Title and description are required.', 'danger')
            return render_template('admin_quiz_form.html')

        quiz = Quiz(title=title, description=description, time_limit=time_limit)
        db.session.add(quiz)
        db.session.commit()
        flash(f'Quiz "{title}" created!', 'success')
        return redirect(url_for('admin_questions', quiz_id=quiz.id))

    return render_template('admin_quiz_form.html')


@app.route('/admin/quiz/<int:quiz_id>/questions', methods=['GET', 'POST'])
@admin_required
def admin_questions(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if request.method == 'POST':
        question_text = request.form.get('question_text', '').strip()
        option1 = request.form.get('option1', '').strip()
        option2 = request.form.get('option2', '').strip()
        option3 = request.form.get('option3', '').strip()
        option4 = request.form.get('option4', '').strip()
        correct = request.form.get('correct_answer', '').strip()

        if not all([question_text, option1, option2, option3, option4, correct]):
            flash('All fields are required.', 'danger')
        elif correct not in [option1, option2, option3, option4]:
            flash('Correct answer must match one of the options.', 'danger')
        else:
            q = Question(
                quiz_id=quiz_id,
                question_text=question_text,
                option1=option1, option2=option2,
                option3=option3, option4=option4,
                correct_answer=correct
            )
            db.session.add(q)
            db.session.commit()
            flash('Question added!', 'success')
            return redirect(url_for('admin_questions', quiz_id=quiz_id))

    return render_template('admin_questions.html', quiz=quiz)


@app.route('/admin/question/<int:q_id>/delete', methods=['POST'])
@admin_required
def delete_question(q_id):
    q = Question.query.get_or_404(q_id)
    quiz_id = q.quiz_id
    db.session.delete(q)
    db.session.commit()
    flash('Question deleted.', 'info')
    return redirect(url_for('admin_questions', quiz_id=quiz_id))


@app.route('/admin/quiz/<int:quiz_id>/delete', methods=['POST'])
@admin_required
def delete_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    db.session.delete(quiz)
    db.session.commit()
    flash('Quiz deleted.', 'info')
    return redirect(url_for('admin'))


# ─────────────────────────────────────────
# DB init & seed
# ─────────────────────────────────────────
def seed_data():
    """Seed sample quizzes if DB is empty."""
    if Quiz.query.count() > 0:
        return

    # Admin user
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@quizapp.com')
        admin.set_password('admin123')
        db.session.add(admin)

    # Sample quizzes
    quizzes_data = [
        {
            'title': 'Python Fundamentals',
            'description': 'Test your knowledge of Python basics — variables, data types, loops, and functions.',
            'time_limit': 300,
            'questions': [
                {
                    'question_text': 'Which keyword is used to define a function in Python?',
                    'options': ['func', 'def', 'define', 'function'],
                    'correct': 'def'
                },
                {
                    'question_text': 'What is the output of: print(type([]))',
                    'options': ['<class \'list\'>', '<class \'array\'>', '<class \'tuple\'>', 'list'],
                    'correct': '<class \'list\'>'
                },
                {
                    'question_text': 'Which of these is a mutable data type in Python?',
                    'options': ['tuple', 'string', 'list', 'int'],
                    'correct': 'list'
                },
                {
                    'question_text': 'What does the `len()` function do?',
                    'options': ['Returns the largest item', 'Returns the number of items', 'Returns item length in bits', 'Sorts the list'],
                    'correct': 'Returns the number of items'
                },
                {
                    'question_text': 'How do you start a comment in Python?',
                    'options': ['//', '#', '/*', '--'],
                    'correct': '#'
                },
            ]
        },
        {
            'title': 'Web Development Basics',
            'description': 'HTML, CSS and JavaScript fundamentals for aspiring web developers.',
            'time_limit': 240,
            'questions': [
                {
                    'question_text': 'What does HTML stand for?',
                    'options': ['HyperText Markup Language', 'HyperText Making Language', 'HighText Markup Language', 'HyperText Marking Language'],
                    'correct': 'HyperText Markup Language'
                },
                {
                    'question_text': 'Which CSS property controls text size?',
                    'options': ['text-size', 'font-size', 'font-style', 'text-style'],
                    'correct': 'font-size'
                },
                {
                    'question_text': 'Which HTML tag is used for the largest heading?',
                    'options': ['<h6>', '<heading>', '<h1>', '<head>'],
                    'correct': '<h1>'
                },
                {
                    'question_text': 'What does CSS stand for?',
                    'options': ['Cascading Style Sheets', 'Creative Style Sheets', 'Computer Style Sheets', 'Colorful Style Sheets'],
                    'correct': 'Cascading Style Sheets'
                },
                {
                    'question_text': 'Which JavaScript method selects an element by ID?',
                    'options': ['querySelector()', 'getElementById()', 'selectById()', 'getElement()'],
                    'correct': 'getElementById()'
                },
            ]
        },
        {
            'title': 'General Knowledge',
            'description': 'A fun mix of science, geography, history, and pop culture trivia.',
            'time_limit': 180,
            'questions': [
                {
                    'question_text': 'What is the capital of France?',
                    'options': ['Berlin', 'Madrid', 'Paris', 'Rome'],
                    'correct': 'Paris'
                },
                {
                    'question_text': 'Which planet is known as the Red Planet?',
                    'options': ['Venus', 'Mars', 'Jupiter', 'Saturn'],
                    'correct': 'Mars'
                },
                {
                    'question_text': 'How many continents are there on Earth?',
                    'options': ['5', '6', '7', '8'],
                    'correct': '7'
                },
                {
                    'question_text': 'Who painted the Mona Lisa?',
                    'options': ['Vincent van Gogh', 'Pablo Picasso', 'Leonardo da Vinci', 'Michelangelo'],
                    'correct': 'Leonardo da Vinci'
                },
                {
                    'question_text': 'What is the chemical symbol for water?',
                    'options': ['H2O', 'CO2', 'O2', 'NaCl'],
                    'correct': 'H2O'
                },
            ]
        },
        {
            'title': 'Data Structures & Algorithms',
            'description': 'Test your CS fundamentals — arrays, sorting, complexity analysis, and more.',
            'time_limit': 360,
            'questions': [
                {
                    'question_text': 'What is the time complexity of binary search?',
                    'options': ['O(n)', 'O(n²)', 'O(log n)', 'O(1)'],
                    'correct': 'O(log n)'
                },
                {
                    'question_text': 'Which data structure uses LIFO (Last In First Out)?',
                    'options': ['Queue', 'Stack', 'Linked List', 'Tree'],
                    'correct': 'Stack'
                },
                {
                    'question_text': 'What is the worst-case time complexity of QuickSort?',
                    'options': ['O(n log n)', 'O(n²)', 'O(n)', 'O(log n)'],
                    'correct': 'O(n²)'
                },
                {
                    'question_text': 'Which traversal visits root, left, then right?',
                    'options': ['Inorder', 'Postorder', 'Preorder', 'Level order'],
                    'correct': 'Preorder'
                },
                {
                    'question_text': 'A hash table provides average-case lookup in:',
                    'options': ['O(n)', 'O(n log n)', 'O(log n)', 'O(1)'],
                    'correct': 'O(1)'
                },
            ]
        },
    ]

    for qd in quizzes_data:
        quiz = Quiz(
            title=qd['title'],
            description=qd['description'],
            time_limit=qd.get('time_limit', 0)
        )
        db.session.add(quiz)
        db.session.flush()

        for i, qdata in enumerate(qd['questions']):
            opts = qdata['options']
            question = Question(
                quiz_id=quiz.id,
                question_text=qdata['question_text'],
                option1=opts[0], option2=opts[1],
                option3=opts[2], option4=opts[3],
                correct_answer=qdata['correct']
            )
            db.session.add(question)

    db.session.commit()
    print('[Seed] Sample quizzes and admin user created.')


if __name__ == '__main__':
    with app.app_context():
        # Handle SQLite schema recreation automatically
        db_path = os.path.join(app.instance_path, 'database.db')
        if os.path.exists(db_path):
            import sqlite3
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(questions)")
                cols = [col[1] for col in cursor.fetchall()]
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_metadata'")
                table_exists = cursor.fetchone()
                conn.close()
                if 'explanation' not in cols or not table_exists:
                    print("[DB] Outdated DB schema detected (missing explanation column or document_metadata table). Recreating...")
                    os.remove(db_path)
            except Exception as e:
                print("[DB] Schema checking error:", str(e))
                
        db.create_all()
        seed_data()
    app.run(debug=True, port=5001)

