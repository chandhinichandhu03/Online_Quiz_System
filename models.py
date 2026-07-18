from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    results = db.relationship('Result', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_stats(self):
        if not self.results:
            return {'total_quizzes': 0, 'avg_score': 0}
        total = len(self.results)
        avg = sum(r.score for r in self.results) / total
        return {'total_quizzes': total, 'avg_score': round(avg, 1)}

    def __repr__(self):
        return f'<User {self.username}>'


class Quiz(db.Model):
    __tablename__ = 'quizzes'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    time_limit = db.Column(db.Integer, default=0)  # 0 = no limit, else seconds
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    questions = db.relationship('Question', backref='quiz', lazy=True, cascade='all, delete-orphan')
    results = db.relationship('Result', backref='quiz', lazy=True, cascade='all, delete-orphan')

    def question_count(self):
        return len(self.questions)

    def __repr__(self):
        return f'<Quiz {self.title}>'


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option1 = db.Column(db.String(300), nullable=False)
    option2 = db.Column(db.String(300), nullable=False)
    option3 = db.Column(db.String(300), nullable=False)
    option4 = db.Column(db.String(300), nullable=False)
    correct_answer = db.Column(db.String(300), nullable=False)
    explanation = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Question {self.id}>'


class Result(db.Model):
    __tablename__ = 'results'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)           # percentage
    correct_answers = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    time_taken = db.Column(db.Integer, default=0)         # seconds
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    answers_json = db.Column(db.Text, default='{}')       # JSON string of user answers

    def __repr__(self):
        return f'<Result user={self.user_id} quiz={self.quiz_id} score={self.score}>'


class DocumentMetadata(db.Model):
    __tablename__ = 'document_metadata'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(250), unique=True, nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    chapter = db.Column(db.String(100))
    topics = db.Column(db.Text)      # Comma separated list of topics
    keywords = db.Column(db.Text)    # Comma separated list of keywords
    difficulty = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DocumentMetadata {self.filename} subject={self.subject}>'
