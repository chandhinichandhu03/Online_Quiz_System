import os
import json
import random
import time
import requests
import hashlib
import numpy as np
from datetime import datetime
from models import db, Quiz, Question

# Setup local knowledge base directories
DOCUMENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'documents'))
VECTOR_STORE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'vector_store'))
DOCS_META_FILE = os.path.join(DOCUMENTS_DIR, "metadata.json")

# Global caches to avoid reloading expensive models on every single call
_embeddings_instance = None
_vector_store_instance = None
_cross_encoder_instance = None

# Canonical Subject Synonym Mapping
SUBJECT_SYNONYMS = {
    "Data Structures": [
        "dsa", "data structure", "data structures", "data structures and algorithms", 
        "data structures & algorithms", "data structure & algorithm", "ds",
        "dsa notes", "dsa lab"
    ],
    "Algorithms": [
        "algorithm", "algorithms", "algo", "sorting algorithms", "searching algorithms"
    ],
    "Software Engineering": [
        "software engineering", "software architecture", "design patterns", "design pattern",
        "software design", "se", "software development", "sdlc"
    ],
    "Operating Systems": [
        "os", "operating system", "operating systems", "os notes", "os lab"
    ],
    "DBMS": [
        "dbms", "db", "database", "databases", "database management system", 
        "database management systems", "dbms notes", "dbms lab"
    ],
    "Computer Networks": [
        "computer networks", "computer network", "networks", "networking", "cn", "cn notes"
    ],
    "Python": [
        "python", "python programming", "python coding", "py"
    ],
    "AI": [
        "ai", "artificial intelligence", "machine learning", "ml", "deep learning", "dl"
    ]
}

# NLP subject dictionary for keyword matching fallback
SUBJECT_KEYWORDS = {
    "Data Structures": [
        "data structure", "dsa", "stack", "queue", "linked list", "array", "binary tree", 
        "bst", "avl", "red-black tree", "heap", "trie", "hash table", "hash map", "graph"
    ],
    "Algorithms": [
        "algorithm", "sorting", "searching", "dijkstra", "kruskal", "prim", "bellman-ford", 
        "dynamic programming", "greedy", "divide and conquer", "backtracking", "complexity", "big o"
    ],
    "Software Engineering": [
        "software architecture", "design pattern", "pattern", "singleton", "observer", "mvc",
        "model view controller", "factory", "adapter", "decorator pattern", "strategy pattern",
        "microservices", "monolithic", "service oriented", "solid principles", "uml",
        "software design", "software engineering", "sdlc", "agile", "scrum"
    ],
    "Operating Systems": [
        "operating system", "os", "process", "thread", "scheduling", "deadlock", "mutex", 
        "semaphore", "paging", "segmentation", "virtual memory", "thrashing", "file system", "context switch"
    ],
    "DBMS": [
        "database", "dbms", "sql", "nosql", "normalization", "normal form", "1nf", "2nf", "3nf", "bcnf",
        "acid", "transaction", "primary key", "foreign key", "join", "index", "schema"
    ],
    "Computer Networks": [
        "network", "tcp", "udp", "ip address", "ipv4", "ipv6", "dns", "http", "routing", 
        "switch", "subnet", "osi model", "ethernet", "port", "socket"
    ],
    "Python": [
        "python", "decorator", "generator", "list comprehension", "dunder", "tuple", "dictionary", 
        "pip", "virtualenv", "flask", "django", "numpy", "pandas"
    ],
    "AI": [
        "artificial intelligence", "machine learning", "neural network", "deep learning", "regression", 
        "classification", "supervised", "unsupervised", "clustering", "gradient descent", "transformer", "llm"
    ]
}

# Query expansion mappings to expand abbreviations automatically
QUERY_EXPANSIONS = {
    "dsa": "Data Structures, Algorithms, Stack, Queue, Tree, Graph, Linked List, Sorting, Searching, Recursion, Dynamic Programming, Greedy, Hashing, Heap",
    "ds": "Data Structures, Stack, Queue, Tree, Graph, Linked List, Heap, Hash Table",
    "os": "Operating Systems, Process, Thread, Scheduling, Deadlock, Memory Management, Paging, Virtual Memory",
    "dbms": "Database Management System, SQL, Normalization, Relation, Key, Transaction, Normal Forms, ACID",
    "cn": "Computer Networks, TCP, UDP, IP Address, Routing, DNS, OSI Model, Subnetting"
}

def normalize_subject(subject_name):
    """
    Normalizes synonymous inputs (like DS, OS, DBMS) to their canonical subjects.
    """
    subj_clean = subject_name.strip().lower()
    for canonical, synonyms in SUBJECT_SYNONYMS.items():
        if subj_clean == canonical.lower():
            return canonical
        for syn in synonyms:
            if subj_clean == syn.lower() or syn.lower() in subj_clean:
                return canonical
    return subject_name.title()

def expand_query(topic_query):
    """
    Expands acronyms (like DSA -> Stack, Queue, Tree, Graph) automatically.
    """
    query_lower = topic_query.lower().strip()
    expanded = [topic_query]
    for key, terms in QUERY_EXPANSIONS.items():
        if query_lower == key:
            expanded.append(terms)
        elif f" {key} " in f" {query_lower} ":
            expanded.append(terms)
    return " | ".join(expanded)

def get_doc_custom_metadata(filename):
    """
    Retrieves the subject and topic map assigned to this document from SQLite DocumentMetadata.
    """
    from models import DocumentMetadata
    try:
        meta = DocumentMetadata.query.filter_by(filename=filename).first()
        if meta:
            return {
                "subject": meta.subject,
                "chapter": meta.chapter or "Chapter 1",
                "topic": meta.topics or "",
                "keywords": meta.keywords or "",
                "difficulty": meta.difficulty or "Medium"
            }
    except Exception as e:
        print("[RAG] DB metadata lookup error (falling back to JSON):", str(e))
        
    # JSON metadata.json fallback
    if os.path.exists(DOCS_META_FILE):
        try:
            with open(DOCS_META_FILE, "r") as f:
                data = json.load(f)
            return data.get(filename, {})
        except Exception:
            pass
    return {}

def save_doc_custom_metadata(filename, subject, topic, chapter="Chapter 1", keywords="", difficulty="Medium"):
    """
    Stores subject and topic metadata for a newly uploaded document in SQLite and metadata.json.
    """
    from models import DocumentMetadata
    subject_canonical = normalize_subject(subject)
    try:
        meta = DocumentMetadata.query.filter_by(filename=filename).first()
        if not meta:
            meta = DocumentMetadata(filename=filename)
            db.session.add(meta)
        meta.subject = subject_canonical
        meta.topics = topic
        meta.chapter = chapter
        meta.keywords = keywords
        meta.difficulty = difficulty
        db.session.commit()
    except Exception as e:
        print("[RAG] DB metadata save error (falling back to JSON):", str(e))
        
    # Fallback JSON metadata.json save
    data = {}
    if os.path.exists(DOCS_META_FILE):
        try:
            with open(DOCS_META_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    data[filename] = {
        "subject": subject_canonical,
        "topic": topic,
        "chapter": chapter,
        "keywords": keywords,
        "difficulty": difficulty,
        "uploaded_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        with open(DOCS_META_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("[RAG] Failed to save JSON custom document metadata:", str(e))

def classify_document_with_ollama(filename, text_snippet):
    """
    Connects to Ollama to automatically classify the uploaded document segment.
    Falls back to local keyword classification if Ollama is offline or fails.
    """
    subject = "General"
    chapter = "Chapter 1"
    topics = ""
    keywords = ""
    difficulty = "Medium"
    
    url_tags = "http://localhost:11434/api/tags"
    ollama_active = False
    selected_model = None
    try:
        response_tags = requests.get(url_tags, timeout=1.5)
        if response_tags.status_code == 200:
            models = response_tags.json().get('models', [])
            gen_models = [m['name'] for m in models if 'embed' not in m['name'].lower()]
            if gen_models:
                ollama_active = True
                selected_model = gen_models[0]
    except Exception:
        pass
        
    if ollama_active and selected_model:
        prompt = f"""
        You are an educational assistant.
        Analyze the following text segment from document '{filename}' and output metadata as JSON matching this schema exactly:
        {{
          "subject": "e.g. Data Structures, Operating Systems, DBMS, Python, AI, Computer Networks",
          "chapter": "e.g. Chapter 1: Introduction",
          "topics": ["topic1", "topic2"],
          "keywords": ["kw1", "kw2"],
          "difficulty": "Easy/Medium/Hard"
        }}
        
        Text segment:
        {text_snippet[:2500]}
        """
        url_generate = "http://localhost:11434/api/generate"
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1}
        }
        try:
            res = requests.post(url_generate, json=payload, timeout=25.0)
            if res.status_code == 200:
                resp_text = res.json().get('response', '').strip()
                data = json.loads(resp_text)
                
                raw_subject = data.get("subject", "General")
                subject = normalize_subject(raw_subject)
                chapter = data.get("chapter", "Chapter 1")
                
                raw_topics = data.get("topics", [])
                topics = ", ".join(raw_topics) if isinstance(raw_topics, list) else str(raw_topics)
                
                raw_keywords = data.get("keywords", [])
                keywords = ", ".join(raw_keywords) if isinstance(raw_keywords, list) else str(raw_keywords)
                
                difficulty = data.get("difficulty", "Medium")
                print(f"[RAG] Auto-classified document '{filename}' via Ollama: Subject='{subject}'")
                return subject, chapter, topics, keywords, difficulty
        except Exception as e:
            print(f"[RAG] Ollama auto-classification failed: {str(e)}. Falling back to keywords...")
            
    # Local keyword matching fallback
    subject, detected_topic = detect_subject_and_topic(text_snippet[:4000])
    subject = normalize_subject(subject)
    topics = detected_topic
    keywords = ", ".join(detected_topic.split()[:5])
    print(f"[RAG] Document '{filename}' locally classified: Subject='{subject}', Topics='{topics}'")
    return subject, chapter, topics, keywords, difficulty

def detect_subject_and_topic(prompt, history_topic=None, history_subject=None):
    """
    Detects Subject and Topic using canonical normalization, NLP keyword match, and conversation history.
    """
    prompt_lower = prompt.lower()
    
    # 1. Memory retrieval check
    follow_up_keywords = ["more", "another", "retry", "again", "continue", "next", "generate 10", "generate 5"]
    is_follow_up = any(kw in prompt_lower for kw in follow_up_keywords) or len(prompt.strip()) < 4
    if is_follow_up and history_topic and history_subject:
        print(f"[RAG] Conversation Memory Match. Topic='{history_topic}', Subject='{history_subject}'")
        return history_subject, history_topic
        
    # 2. Check keywords for subject mapping
    detected_subject = "General"
    max_matches = 0
    for subj, keywords in SUBJECT_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in prompt_lower)
        if matches > max_matches:
            max_matches = matches
            detected_subject = subj
            
    # Canonical subject synonym resolution
    detected_subject = normalize_subject(detected_subject)
            
    # 3. Topic extraction (strip filler words)
    fillers = ["generate", "quiz", "questions", "question", "mcq", "mcqs", "test", "exam", "about", "on", "for", "some", "10", "5", "20"]
    words = prompt.split()
    topic_words = [w for w in words if w.lower() not in fillers]
    detected_topic = " ".join(topic_words).strip() if topic_words else prompt
    
    # 4. Fallback search existing DB records to check subject matches
    if detected_subject == "General" and os.path.exists(DOCS_META_FILE):
        try:
            with open(DOCS_META_FILE, "r") as f:
                saved_meta = json.load(f)
            for doc_info in saved_meta.values():
                subj = doc_info.get("subject")
                if subj and subj.lower() in prompt_lower:
                    detected_subject = normalize_subject(subj)
                    break
        except Exception:
            pass
            
    return detected_subject, detected_topic

def load_single_document(filename):
    """
    Loads text content from a study document (PDF, DOCX, TXT, MD) and
    returns a list of LangChain Document objects.
    """
    from langchain_core.documents import Document
    file_path = os.path.join(DOCUMENTS_DIR, filename)
    docs = []
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Study document not found: {file_path}")
        
    print(f"[RAG] Extracting text from '{filename}'...")
    ext = filename.lower()
    
    try:
        if ext.endswith('.pdf'):
            import pypdf
            reader = pypdf.PdfReader(file_path)
            for page_idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                docs.append(Document(
                    page_content=text,
                    metadata={"source": file_path, "page": page_idx}
                ))
        elif ext.endswith('.docx'):
            import docx2txt
            text = docx2txt.process(file_path)
            docs.append(Document(
                page_content=text,
                metadata={"source": file_path, "page": 0}
            ))
        elif ext.endswith(('.txt', '.md')):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            docs.append(Document(
                page_content=text,
                metadata={"source": file_path, "page": 0}
            ))
        else:
            raise ValueError(f"Unsupported file format: {ext}")
            
    except Exception as e:
        print(f"[RAG] Error extracting text from '{filename}': {str(e)}")
        raise e
        
    return docs

def get_documents_metadata():
    if not os.path.exists(DOCUMENTS_DIR):
        os.makedirs(DOCUMENTS_DIR)
        return {}
    
    metadata = {}
    for filename in os.listdir(DOCUMENTS_DIR):
        file_path = os.path.join(DOCUMENTS_DIR, filename)
        if os.path.isfile(file_path) and filename.lower().endswith(('.pdf', '.docx', '.txt', '.md')):
            stat = os.stat(file_path)
            metadata[filename] = {
                'mtime': stat.st_mtime,
                'size': stat.st_size
            }
    return metadata

def create_chunk_metadata(doc, chunk_idx):
    filename = os.path.basename(doc.metadata.get("source", ""))
    custom_meta = get_doc_custom_metadata(filename)
    
    subject = custom_meta.get("subject")
    if not subject:
        subject, _ = detect_subject_and_topic(doc.page_content)
        
    subject = normalize_subject(subject)
    topic = custom_meta.get("topic") or custom_meta.get("topics")
    if not topic:
        topic = os.path.splitext(filename)[0].replace("_", " ").title()
        
    doc_id = hashlib.md5(filename.encode('utf-8')).hexdigest()
    chunk_id = f"{doc_id}_{chunk_idx}"
    
    return {
        "subject": subject,
        "chapter": custom_meta.get("chapter", "Chapter 1"),
        "topic": topic,
        "filename": filename,
        "page": doc.metadata.get("page", 0) + 1,
        "difficulty": custom_meta.get("difficulty", "Medium"),
        "document_id": doc_id,
        "chunk_id": chunk_id
    }

def get_embeddings():
    global _embeddings_instance
    if _embeddings_instance is None:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        print("[RAG] Loading HuggingFace Embeddings (BAAI/bge-base-en-v1.5)...")
        _embeddings_instance = HuggingFaceEmbeddings(
            model_name="BAAI/bge-base-en-v1.5",
            model_kwargs={'device': 'cpu'}
        )
    return _embeddings_instance

def verify_and_heal_index(vector_store, embeddings, current_meta):
    """
    Performs comprehensive diagnostic checks on the loaded FAISS index.
    Returns (is_healthy, reason)
    """
    if vector_store is None:
        return False, "No FAISS index loaded."
        
    try:
        # Check 1: Verify dimension match
        test_vector = embeddings.embed_query("test")
        expected_dim = len(test_vector)
        if vector_store.index.d != expected_dim:
            return False, f"Embedding dimension mismatch (FAISS={vector_store.index.d}, expected={expected_dim})."
            
        # Check 2: Verify total documents/vectors
        num_vectors = vector_store.index.ntotal
        num_docs = len(vector_store.docstore._dict)
        if num_vectors == 0 or num_docs == 0:
            return False, f"FAISS index is empty (vectors={num_vectors}, documents={num_docs})."
            
        # Check 3: Verify document files consistency
        indexed_files = set()
        for doc in vector_store.docstore._dict.values():
            fn = doc.metadata.get("filename")
            if fn:
                indexed_files.add(fn)
                
        actual_files = set(current_meta.keys())
        if actual_files != indexed_files:
            return False, f"Document file mismatch (Indexed: {indexed_files}, Actual: {actual_files})."
            
        # Check 4: Check if vector store IDs match docstore
        if num_vectors != num_docs:
            return False, f"Data count mismatch (vectors={num_vectors}, docs={num_docs})."
            
    except Exception as e:
        return False, f"Corrupted index or parsing error: {str(e)}"
        
    return True, "Index is healthy."

def rebuild_index_from_scratch(embeddings, current_meta):
    """
    Rebuilds the FAISS index from scratch using all files in current_meta.
    """
    from langchain_community.vectorstores import FAISS
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    print("[RAG] [Self-Healing] Rebuilding index from scratch...")
    
    # Clean cached files first
    if os.path.exists(VECTOR_STORE_DIR):
        for f in os.listdir(VECTOR_STORE_DIR):
            try:
                os.remove(os.path.join(VECTOR_STORE_DIR, f))
            except Exception:
                pass
                
    all_docs = []
    for filename in current_meta.keys():
        try:
            all_docs.extend(load_single_document(filename))
        except Exception as e:
            print(f"[RAG] [Rebuild Error] Skipping corrupted file '{filename}': {str(e)}")
            
    if not all_docs:
        print("[RAG] Knowledge Base is empty. Cannot rebuild index.")
        return None
        
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600, chunk_overlap=150,
        separators=["\n\n", "\n", " ", "", "def ", "class ", "function "]
    )
    split_docs = text_splitter.split_documents(all_docs)
    for idx, doc in enumerate(split_docs):
        doc.metadata = create_chunk_metadata(doc, idx)
        
    print(f"[RAG] [Self-Healing] Generating embeddings for {len(split_docs)} chunks...")
    vector_store = FAISS.from_documents(split_docs, embeddings)
    
    # Save the newly built index
    vector_store.save_local(VECTOR_STORE_DIR)
    
    # Save metadata.json
    metadata_file = os.path.join(VECTOR_STORE_DIR, "metadata.json")
    with open(metadata_file, "w") as f:
        json.dump(current_meta, f, indent=2)
        
    print("[RAG] [Self-Healing] FAISS index rebuilt and saved successfully.")
    return vector_store

def get_or_build_vector_store():
    """
    Incremental indexing pipeline with self-healing checks:
    - Verifies index exists and load it.
    - Runs comprehensive diagnostic checks.
    - Rebuilds from scratch if checks fail.
    - Otherwise, handles incremental updates (adds new/changed docs, Merges).
    """
    global _vector_store_instance
    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    
    embeddings = get_embeddings()
    current_meta = get_documents_metadata()
    metadata_file = os.path.join(VECTOR_STORE_DIR, "metadata.json")
    
    # If the documents directory is empty, we clean the vector store and return None
    if not current_meta:
        print("[RAG] Documents directory is empty. Cleaning index cache...")
        if os.path.exists(VECTOR_STORE_DIR):
            for f in os.listdir(VECTOR_STORE_DIR):
                try:
                    os.remove(os.path.join(VECTOR_STORE_DIR, f))
                except Exception:
                    pass
        _vector_store_instance = None
        return None
        
    saved_meta = {}
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, "r") as f:
                saved_meta = json.load(f)
        except Exception as e:
            print(f"[RAG] Error reading index metadata: {str(e)}")
            
    # Load vector store if cached
    vector_store = _vector_store_instance
    index_exists = os.path.exists(VECTOR_STORE_DIR) and os.path.exists(os.path.join(VECTOR_STORE_DIR, "index.faiss"))
    
    if vector_store is None and index_exists:
        from langchain_community.vectorstores import FAISS
        try:
            print("[RAG] Loading cached FAISS index from disk...")
            vector_store = FAISS.load_local(VECTOR_STORE_DIR, embeddings, allow_dangerous_deserialization=True)
            _vector_store_instance = vector_store
        except Exception as e:
            print(f"[RAG] Error loading cached index: {str(e)}")
            vector_store = None
            
    # Run audit and diagnostics check on the loaded index
    is_healthy, reason = verify_and_heal_index(vector_store, embeddings, current_meta)
    print(f"[RAG Audit] Health check result: {is_healthy} ({reason})")
    
    if not is_healthy:
        print(f"[RAG Audit] Triggering self-healing rebuild due to: {reason}")
        vector_store = rebuild_index_from_scratch(embeddings, current_meta)
        _vector_store_instance = vector_store
        return vector_store
        
    # Incremental update checking (since index is healthy)
    new_or_changed = []
    deleted = []
    
    for filename, info in current_meta.items():
        if filename not in saved_meta:
            new_or_changed.append(filename)
        else:
            saved_info = saved_meta[filename]
            if info['mtime'] != saved_info.get('mtime') or info['size'] != saved_info.get('size'):
                new_or_changed.append(filename)
                
    for filename in saved_meta.keys():
        if filename not in current_meta:
            deleted.append(filename)
            
    # If files were deleted, we rebuild from scratch to purge old chunks completely
    if deleted:
        print(f"[RAG] Documents deleted: {deleted}. Rebuilding from scratch...")
        vector_store = rebuild_index_from_scratch(embeddings, current_meta)
        _vector_store_instance = vector_store
    elif new_or_changed:
        # Incremental indexing for new/changed documents
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        print(f"[RAG] Incremental Indexing: {len(new_or_changed)} new/changed document(s)...")
        new_chunks = []
        for filename in new_or_changed:
            try:
                docs = load_single_document(filename)
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=600, chunk_overlap=150,
                    separators=["\n\n", "\n", " ", "", "def ", "class ", "function "]
                )
                split_docs = text_splitter.split_documents(docs)
                for idx, doc in enumerate(split_docs):
                    doc.metadata = create_chunk_metadata(doc, idx)
                new_chunks.extend(split_docs)
            except Exception as e:
                print(f"[RAG] Error loading new document '{filename}': {str(e)}")
                
        if new_chunks:
            print(f"[RAG] Adding {len(new_chunks)} chunks to FAISS index...")
            vector_store.add_documents(new_chunks)
            _vector_store_instance = vector_store
            
            # Save the updated index and metadata
            vector_store.save_local(VECTOR_STORE_DIR)
            with open(metadata_file, "w") as f:
                json.dump(current_meta, f, indent=2)
            print("[RAG] FAISS index and metadata successfully updated on disk.")
            
    return vector_store

def get_rag_diagnostics_report():
    """
    Generates a full diagnostics report dictionary for the RAG index.
    """
    global _vector_store_instance
    embeddings = get_embeddings()
    current_meta = get_documents_metadata()
    metadata_file = os.path.join(VECTOR_STORE_DIR, "metadata.json")
    
    # 1. FAISS status & document details
    faiss_status = "Not Found"
    num_vectors = 0
    num_docs = 0
    index_dim = 0
    indexed_files = set()
    
    index_exists = os.path.exists(VECTOR_STORE_DIR) and os.path.exists(os.path.join(VECTOR_STORE_DIR, "index.faiss"))
    
    vector_store = _vector_store_instance
    if vector_store is None and index_exists:
        from langchain_community.vectorstores import FAISS
        try:
            vector_store = FAISS.load_local(VECTOR_STORE_DIR, embeddings, allow_dangerous_deserialization=True)
            _vector_store_instance = vector_store
        except Exception:
            pass
            
    if vector_store is not None:
        faiss_status = "Online / Loaded"
        num_vectors = vector_store.index.ntotal
        num_docs = len(vector_store.docstore._dict)
        index_dim = vector_store.index.d
        for doc in vector_store.docstore._dict.values():
            fn = doc.metadata.get("filename")
            if fn:
                indexed_files.add(fn)
    elif index_exists:
        faiss_status = "Corrupted / Unloadable"
        
    # 2. Last index time
    last_index_time = "N/A"
    if os.path.exists(metadata_file):
        try:
            mtime = os.path.getmtime(metadata_file)
            last_index_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
            
    # 3. Missing documents
    actual_files = set(current_meta.keys())
    missing_docs = list(actual_files - indexed_files)
    
    # 4. Corrupted chunks
    corrupted_chunks_count = 0
    if vector_store is not None:
        for doc_id, doc in vector_store.docstore._dict.items():
            if not doc.page_content or not doc.metadata:
                corrupted_chunks_count += 1
                
    report = {
        "documents_indexed": list(indexed_files),
        "documents_indexed_count": len(indexed_files),
        "chunks_indexed_count": num_docs,
        "embedding_model": "BAAI/bge-base-en-v1.5",
        "embedding_dimension": index_dim,
        "retriever_status": "Ready" if vector_store is not None else "Not Ready",
        "faiss_status": faiss_status,
        "metadata_count": len(current_meta),
        "last_index_time": last_index_time,
        "missing_documents": missing_docs,
        "corrupted_chunks_count": corrupted_chunks_count
    }
    return report

def get_cross_encoder():
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        from sentence_transformers import CrossEncoder
        print("[RAG] Loading CrossEncoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2)...")
        _cross_encoder_instance = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    return _cross_encoder_instance

def tfidf_keyword_search_fallback(vector_store, expanded_query, faiss_k):
    """
    Performs keyword search using TF-IDF across the entire FAISS document store.
    """
    try:
        all_docs = list(vector_store.docstore._dict.values())
        if not all_docs:
            return []
            
        from sklearn.feature_extraction.text import TfidfVectorizer
        corpus = []
        for doc in all_docs:
            searchable_text = f"{doc.page_content} {doc.metadata.get('filename', '')} {doc.metadata.get('topic', '')} {doc.metadata.get('subject', '')}"
            corpus.append(searchable_text)
            
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([expanded_query])
        scores = (tfidf_matrix * query_vec.T).toarray().flatten()
        
        results = []
        for idx, score in enumerate(scores):
            if score > 0.05:  # keyword overlap match threshold
                dist = 1.0 / (score + 1e-5)
                results.append((all_docs[idx], dist))
                
        results.sort(key=lambda x: x[1])
        return results[:faiss_k]
    except Exception as e:
        print("[RAG] TF-IDF fallback search failed:", str(e))
        return []

def compute_hybrid_and_rerank(vector_store, query_text, detected_subject, detected_topic, top_k, faiss_k=25):
    """
    Multi-stage retrieval pipeline:
    - Stage 1: Subject Filter + Topic (Semantic)
    - Stage 2: Topic (Semantic, Ignore Subject filter)
    - Stage 3: Semantic similarity search across all documents
    - Stage 4: TF-IDF Keyword search fallback
    - Stage 5: Hybrid Rank + Cross-Encoder reranking (ms-marco-MiniLM-L-6-v2)
    """
    retrieved_docs_with_scores = []
    stage_log = []
    
    # Pre-check synonym expansion for queries
    expanded_query = expand_query(query_text)
    
    # ─── STAGE 1: Broad Semantic Search + Python Subject Post-Filter ───
    # NOTE: FAISS does NOT support native metadata filtering. The filter= parameter
    # silently returns 0 results. We do a broad search then filter in Python.
    print(f"[RAG] [Stage 1] Query: '{query_text}' | Expanded: '{expanded_query}' | Subject: '{detected_subject}'")
    stage_log.append("Subject Filter + Topic (Semantic)")
    try:
        all_results = vector_store.similarity_search_with_score(expanded_query, k=faiss_k * 3)
        # Post-filter by subject in Python
        subject_filtered = [
            (doc, score) for doc, score in all_results
            if doc.metadata.get("subject", "").lower() == detected_subject.lower()
        ]
        if subject_filtered:
            retrieved_docs_with_scores = subject_filtered[:faiss_k]
            print(f"[RAG] [Stage 1] Subject post-filter matched {len(subject_filtered)} chunks for '{detected_subject}'")
        else:
            # No subject match — use all results and let later stages handle it
            retrieved_docs_with_scores = all_results[:faiss_k]
            print(f"[RAG] [Stage 1] No subject match for '{detected_subject}', using all {len(all_results)} results")
    except Exception as e:
        print(f"[RAG] Stage 1 FAISS search error: {str(e)}")
            
    # Check max similarity confidence threshold
    max_score = 0.0
    if retrieved_docs_with_scores:
        max_score = max(1.0 / (1.0 + score) for _, score in retrieved_docs_with_scores)
        
    # If Stage 1 fails (fewer than 3 chunks or max similarity < 0.45)
    if len(retrieved_docs_with_scores) < 3 or max_score < 0.45:
        print(f"[RAG] [Stage 1 Failed] (retrieved={len(retrieved_docs_with_scores)}, max_sim={max_score:.4f}). Retrying Stage 2...")
        
        # ─── STAGE 2: Search only Topic (Ignore Subject Metadata) ───
        stage_log.append("Topic Search (No Subject Filter)")
        try:
            retrieved_docs_with_scores = vector_store.similarity_search_with_score(expanded_query, k=faiss_k)
        except Exception as e:
            print("[RAG] Stage 2 FAISS search error:", str(e))
            
        if retrieved_docs_with_scores:
            max_score = max(1.0 / (1.0 + score) for _, score in retrieved_docs_with_scores)
            
    # If Stage 2 still fails
    if len(retrieved_docs_with_scores) < 3 or max_score < 0.45:
        print(f"[RAG] [Stage 2 Failed] (retrieved={len(retrieved_docs_with_scores)}, max_sim={max_score:.4f}). Retrying Stage 3...")
        
        # ─── STAGE 3: Semantic similarity search across ALL indexed docs ───
        stage_log.append("Global Semantic Database Search")
        try:
            retrieved_docs_with_scores = vector_store.similarity_search_with_score(expanded_query, k=faiss_k * 2)
        except Exception as e:
            print("[RAG] Stage 3 FAISS search error:", str(e))
            
    # If Stage 3 still fails
    if not retrieved_docs_with_scores or len(retrieved_docs_with_scores) < 3:
        print("[RAG] [Stage 3 Failed]. Retrying Stage 4 (TF-IDF Keyword Search)...")
        
        # ─── STAGE 4: Keyword search using TF-IDF across titles, filenames, page content ───
        stage_log.append("TF-IDF Keyword Fallback Search")
        tfidf_results = tfidf_keyword_search_fallback(vector_store, expanded_query, faiss_k)
        if tfidf_results:
            retrieved_docs_with_scores = tfidf_results
            
    # If all stages return empty results
    if not retrieved_docs_with_scores:
        print("[RAG] [All Stages Failed] No documents found.")
        return [], stage_log
        
    # ─── STAGE 5: Combined hybrid ranking and CrossEncoder rerank ───
    stage_log.append("Reranked Top Chunks")
    docs = []
    seen_chunks = set()
    deduped_docs_with_scores = []
    
    for doc, dist in retrieved_docs_with_scores:
        chunk_id = doc.metadata.get("chunk_id")
        if chunk_id not in seen_chunks:
            seen_chunks.add(chunk_id)
            deduped_docs_with_scores.append((doc, dist))
            
    # Hybrid Search Scoring
    docs = [item[0] for item in deduped_docs_with_scores]
    distances = [item[1] for item in deduped_docs_with_scores]
    semantic_scores = [1.0 / (1.0 + dist) for dist in distances]
    
    # TF-IDF keyword overlap calculation
    from sklearn.feature_extraction.text import TfidfVectorizer
    corpus = [doc.page_content for doc in docs]
    try:
        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query_text])
        keyword_scores = (tfidf_matrix * query_vec.T).toarray().flatten()
    except Exception:
        keyword_scores = []
        q_words = set(query_text.lower().split())
        for content in corpus:
            overlap = sum(1 for w in q_words if w in content.lower())
            keyword_scores.append(overlap / (len(q_words) + 1.0))
            
    # Metadata score matching (Boost matches)
    metadata_scores = []
    topic_words = set(detected_topic.lower().split())
    for doc in docs:
        meta_score = 0.0
        doc_topic = doc.metadata.get("topic", "").lower()
        doc_file = doc.metadata.get("filename", "").lower()
        doc_subj = doc.metadata.get("subject", "").lower()
        if any(w in doc_topic for w in topic_words):
            meta_score += 0.4
        if any(w in doc_file for w in topic_words):
            meta_score += 0.4
        if detected_subject.lower() in doc_subj:
            meta_score += 0.2
        metadata_scores.append(min(1.0, meta_score))
        
    # Combines scores: 0.55 Semantic + 0.30 Keyword + 0.15 Metadata match
    hybrid_docs = []
    for idx, doc in enumerate(docs):
        final_hybrid = (
            0.55 * semantic_scores[idx] +
            0.30 * keyword_scores[idx] +
            0.15 * metadata_scores[idx]
        )
        hybrid_docs.append((doc, final_hybrid))
        
    hybrid_docs.sort(key=lambda x: x[1], reverse=True)
    
    # CrossEncoder Reranking
    print(f"[RAG] Reranking {len(hybrid_docs)} chunks with CrossEncoder...")
    encoder = get_cross_encoder()
    pairs = [(query_text, doc.page_content) for doc, _ in hybrid_docs]
    rerank_logits = encoder.predict(pairs)
    
    reranked_results = []
    for idx, (doc, _) in enumerate(hybrid_docs):
        logit = float(rerank_logits[idx])
        confidence_score = 1.0 / (1.0 + np.exp(-logit))
        reranked_results.append((doc, confidence_score))
        
    reranked_results.sort(key=lambda x: x[1], reverse=True)
    
    # Intelligent Retry: If fewer than 3 chunks match criteria (rerank score >= 0.45)
    # We dynamically expand top_k and lower threshold restrictions
    valid_chunks = [item for item in reranked_results if item[1] >= 0.45]
    if len(valid_chunks) < 3 and len(reranked_results) >= 3:
        print("[RAG] Retrieval underperforming confidence requirements. Relaxing confidence threshold constraint...")
        # Sort and take the top reranked chunks without threshold exclusions
        return reranked_results[:top_k], stage_log
        
    return reranked_results[:top_k], stage_log

# Banned placeholder options that local LLMs sometimes produce
BANNED_OPTIONS = {
    "correct", "wrong", "incorrect", "true", "false",
    "none of the above", "all of the above", "n/a", "na",
    "not applicable", "answer", "right", "option a", "option b",
    "option c", "option d"
}

def validate_single_question(q_dict):
    """
    Validates a single parsed question dictionary.
    Returns (is_valid, list_of_reasons).
    """
    reasons = []
    
    q_text = q_dict.get("question", "")
    opts = q_dict.get("options", [])
    correct = q_dict.get("correct_answer", "")
    explanation = q_dict.get("explanation", "")
    
    # Check question text
    if not q_text or len(q_text.strip()) < 10:
        reasons.append(f"Question text too short or empty: '{q_text}'")
        
    # Check exactly 4 options
    if len(opts) != 4:
        reasons.append(f"Expected 4 options, got {len(opts)}")
        
    # Check no empty options
    for i, opt in enumerate(opts):
        if not opt or not opt.strip():
            reasons.append(f"Option {i+1} is empty")
            
    # Check no duplicate options
    opts_lower = [o.strip().lower() for o in opts if o]
    if len(set(opts_lower)) != len(opts_lower):
        reasons.append(f"Duplicate options detected: {opts}")
        
    # Check no banned placeholder options
    for opt in opts:
        if opt.strip().lower() in BANNED_OPTIONS:
            reasons.append(f"Banned placeholder option: '{opt}'")
            
    # Check correct answer exists in options
    if correct and correct not in opts:
        reasons.append(f"Correct answer '{correct}' not found in options {opts}")
        
    # Check explanation is non-empty
    if not explanation or len(explanation.strip()) < 3:
        reasons.append("Explanation is empty or too short")
        
    return (len(reasons) == 0), reasons

def parse_and_save_quiz_with_explanation(data, num_questions, description):
    """
    Parses JSON data returned by Ollama, validates every question,
    and writes only valid questions to the SQLite database.
    
    Invalid questions are logged and skipped — never padded with
    placeholder options like 'None of the above'.
    """
    title = data.get('title') or "Offline RAG Quiz"
    
    # Check for Ollama "insufficient context" response
    if data.get('error'):
        raise Exception(f"Ollama reported: {data['error']}")
    
    quiz = Quiz(
        title=title,
        description=description,
        time_limit=num_questions * 60
    )
    db.session.add(quiz)
    db.session.flush()
    
    raw_questions = data.get('questions') or []
    if not raw_questions:
        raise Exception("No questions found in the generated JSON response.")
    
    valid_count = 0
    seen_questions = set()  # Track duplicates by question text
    
    for idx, q in enumerate(raw_questions):
        # Flexible key extraction — LLMs use varying key names
        q_text = q.get('question') or q.get('question_text') or q.get('text') or ""
        opts = q.get('options') or q.get('choices') or q.get('answers') or []
        correct = (q.get('correct_answer') or q.get('answer') or 
                   q.get('correct') or q.get('correct_option') or "")
        explanation = q.get('explanation') or q.get('reasoning') or ""
        
        # Clean up
        q_text = str(q_text).strip()
        opts = [str(o).strip() for o in opts if o is not None]
        correct = str(correct).strip()
        if not explanation or not explanation.strip():
            explanation = "No explanation provided."
        else:
            explanation = str(explanation).strip()
        
        # Skip if the question text is empty
        if not q_text:
            print(f"[Parser] Skipping question {idx+1}: empty question text")
            continue
            
        # Skip duplicate questions
        q_key = q_text.lower().strip()
        if q_key in seen_questions:
            print(f"[Parser] Skipping question {idx+1}: duplicate of earlier question")
            continue
        seen_questions.add(q_key)
        
        # Resolve letter-based or index-based correct answers
        # e.g. "A" -> opts[0], "B" -> opts[1], "0" -> opts[0]
        if correct not in opts and len(opts) >= 4:
            letter_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
            if correct.upper() in letter_map and letter_map[correct.upper()] < len(opts):
                resolved = opts[letter_map[correct.upper()]]
                print(f"[Parser] Resolved letter answer '{correct}' -> '{resolved}'")
                correct = resolved
            elif correct.isdigit() and int(correct) < len(opts):
                resolved = opts[int(correct)]
                print(f"[Parser] Resolved index answer '{correct}' -> '{resolved}'")
                correct = resolved
            # Also try correct_option field as a letter
            elif q.get('correct_option') and q.get('correct_option').upper() in letter_map:
                opt_idx = letter_map[q['correct_option'].upper()]
                if opt_idx < len(opts):
                    resolved = opts[opt_idx]
                    print(f"[Parser] Resolved correct_option '{q['correct_option']}' -> '{resolved}'")
                    correct = resolved
        
        # Build validated question dict
        q_validated = {
            "question": q_text,
            "options": opts[:4],  # Take at most 4
            "correct_answer": correct,
            "explanation": explanation
        }
        
        # Run validation
        is_valid, reasons = validate_single_question(q_validated)
        
        if not is_valid:
            print(f"[Parser] REJECTED question {idx+1}: {reasons}")
            print(f"         Question: '{q_text[:80]}...'")
            print(f"         Options: {opts}")
            print(f"         Answer: '{correct}'")
            continue
        
        # Shuffle options (after validation confirmed correct answer is in opts)
        shuffled_opts = list(opts[:4])
        random.shuffle(shuffled_opts)
        
        question = Question(
            quiz_id=quiz.id,
            question_text=q_text,
            option1=shuffled_opts[0],
            option2=shuffled_opts[1],
            option3=shuffled_opts[2],
            option4=shuffled_opts[3],
            correct_answer=correct,
            explanation=explanation
        )
        db.session.add(question)
        valid_count += 1
    
    # Require at least some valid questions
    min_required = max(1, num_questions // 2)
    if valid_count < min_required:
        db.session.rollback()
        raise Exception(
            f"Only {valid_count} out of {len(raw_questions)} questions passed validation "
            f"(minimum {min_required} required). The LLM produced malformed output. "
            f"Please try again."
        )
        
    db.session.commit()
    print(f"[Parser] Saved {valid_count}/{len(raw_questions)} valid questions to database.")
    return quiz.id

def generate_quiz_with_ollama(topic, num_questions=10, history_subject=None, history_topic=None):
    """
    End-to-End High-Accuracy Offline RAG quiz generation with:
    - Multi-stage fallback search pipeline
    - Synonym subject canonical normalization & query abbreviation expansions
    - Cross-Encoder confidence threshold safeguards
    - JSON validation uploader self-repair loops
    - Metrics logging & Diagnostics UI
    """
    start_time = time.time()
    
    # 1. NLP classification and synonym resolution
    detected_subject, detected_topic = detect_subject_and_topic(topic, history_topic, history_subject)
    
    # 2. Dynamic retrieval scaling
    top_k = max(5, min(25, num_questions))
    faiss_k = max(20, top_k * 2)
    
    # Load / Build index
    vector_store = get_or_build_vector_store()
    if not vector_store:
        raise Exception("Your local Knowledge Base (documents/ directory) is empty. Please upload some study documents first.")
        
    embeddings = get_embeddings()
    current_meta = get_documents_metadata()
        
    # 3. Multi-Stage retrieval fallbacks execution
    reranked_docs, stage_log = compute_hybrid_and_rerank(vector_store, detected_topic, detected_subject, detected_topic, top_k, faiss_k)
    
    # Self-healing index check & retry if retrieval failed or is low confidence
    max_confidence = max(score for _, score in reranked_docs) if reranked_docs else 0.0
    retrieval_failed = not reranked_docs or max_confidence < 0.45
    
    if retrieval_failed:
        print("[RAG Audit] Retrieval failed or had low confidence. Rebuilding index to attempt self-healing...")
        vector_store = rebuild_index_from_scratch(embeddings, current_meta)
        if vector_store:
            print("[RAG Audit] FAISS index rebuilt. Retrying multi-stage search retrieval...")
            reranked_docs, stage_log = compute_hybrid_and_rerank(vector_store, detected_topic, detected_subject, detected_topic, top_k, faiss_k)
            
    if not reranked_docs:
        raise Exception(f"No relevant information could be found in the uploaded documents. Please upload additional study material related to '{detected_topic}'.")
        
    # 4. Confidence evaluation
    max_confidence = max(score for _, score in reranked_docs)
    avg_confidence = sum(score for _, score in reranked_docs) / len(reranked_docs)
    
    # Log RAG Retrieval Diagnostics (Query, Top K, Chunks, Scores, IDs, Metadata, Pages)
    print(f"\n================= RAG RETRIEVAL DIAGNOSTICS =================\n"
          f"Query: '{topic}'\n"
          f"Detected Subject: '{detected_subject}'\n"
          f"Detected Topic: '{detected_topic}'\n"
          f"Top K: {top_k}\n"
          f"Retrieved Chunks Count: {len(reranked_docs)}\n"
          f"============================================================")
    for idx, (doc, score) in enumerate(reranked_docs):
        print(f"[{idx+1}] Chunk ID: {doc.metadata.get('chunk_id')}\n"
              f"    Source File: {doc.metadata.get('filename')}\n"
              f"    Page Number: {doc.metadata.get('page')}\n"
              f"    Similarity Score (Rerank): {score:.4f}\n"
              f"    Content Preview: {doc.page_content[:150].strip()}...\n"
              f"    Metadata: {doc.metadata}\n"
              f"------------------------------------------------------------")
    print("============================================================\n")
    
    # Safety check: similarity/rerank score < 0.45 leads to immediate error
    if max_confidence < 0.45:
        raise Exception(f"No relevant information could be found in the uploaded documents (relevance score {max_confidence:.2f} < 0.45). Please upload additional study material related to '{detected_topic}'.")
        
    retrieved_chunks = [doc.page_content for doc, _ in reranked_docs]
    context_text = "\n\n---\n\n".join(retrieved_chunks)
    
    # 5. Ollama Context Verification (Context length and subject verification)
    if not context_text.strip() or len(context_text.strip()) < 50:
        raise Exception("Retrieved context text length is insufficient to generate quiz questions.")
        
    context_words = context_text.lower()
    subject_matched = any(word in context_words for word in detected_subject.lower().split())
    if not subject_matched:
        print(f"[RAG Warning] Retrieved context might not match subject: '{detected_subject}'")
    
    precision = round(max_confidence * 100, 1)
    recall = round(avg_confidence * 100, 1)
    chunk_coverage = len(reranked_docs)
    
    # 6. Ollama health check
    url_tags = "http://localhost:11434/api/tags"
    try:
        response_tags = requests.get(url_tags, timeout=2.0)
        if response_tags.status_code != 200:
            raise Exception("Ollama server is not running.")
        models_data = response_tags.json().get('models', [])
    except Exception as e:
        raise Exception("Ollama is not running. Start it using 'ollama serve' in your terminal.")

    installed_models = [m['name'] for m in models_data]
    generation_models = [m for m in installed_models if 'embed' not in m.lower()]
    if not generation_models:
        raise Exception("No local Ollama text generation model found. Run 'ollama pull llama3.2' or 'ollama pull llama2'.")
        
    selected_model = None
    for model_priority in ['llama3.2', 'mistral', 'phi3', 'llama2']:
        for inst_model in generation_models:
            if model_priority in inst_model:
                selected_model = inst_model
                break
        if selected_model:
            break
    if not selected_model:
        selected_model = generation_models[0]
        
    print(f"[RAG] Using Ollama generation model: {selected_model}")
    
    # 7. Strict university professor prompt
    prompt = f"""You are an experienced university professor creating an exam.
Generate multiple-choice questions ONLY from the supplied context.

STRICT RULES:
1. Generate exactly {num_questions} questions.
2. Each question MUST have exactly 4 different, meaningful options.
3. Every option must be a substantive answer — NEVER use generic placeholders.
4. FORBIDDEN options (never use these): "Correct", "Wrong", "Incorrect", "True", "False", "None of the above", "All of the above", "N/A".
5. The correct_answer must match one of the 4 options EXACTLY (character-for-character).
6. Each option must be unique — no duplicates.
7. Include a brief explanation for why the correct answer is right.
8. If the context is insufficient, return: {{"error": "Insufficient context"}}

Subject: {detected_subject}
Topic: {detected_topic}
Difficulty: Medium

Context:
{context_text}

Return ONLY valid JSON matching this exact schema (no markdown, no extra text):
{{
  "title": "{detected_topic} Quiz",
  "questions": [
    {{
      "question": "A clear question based on the context",
      "options": ["meaningful option A", "meaningful option B", "meaningful option C", "meaningful option D"],
      "correct_answer": "the exact text of the correct option",
      "explanation": "why this answer is correct based on the context"
    }}
  ]
}}"""
    
    url_generate = "http://localhost:11434/api/generate"
    payload = {
        "model": selected_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.2,
            "top_p": 0.85,
            "repeat_penalty": 1.2,
            "num_predict": 2500,
            "num_ctx": 8192,
            "num_thread": os.cpu_count() or 4,
            "keep_alive": "30m"
        }
    }
    
    print(f"[RAG] Prompt character length: {len(prompt)}")
    print("[RAG] Calling local Ollama generation API...")
    gen_start = time.time()
    try:
        response_gen = requests.post(url_generate, json=payload, timeout=180.0)
        if response_gen.status_code != 200:
            raise Exception(f"Ollama server returned error code {response_gen.status_code}")
            
        res_json = response_gen.json()
        response_text = res_json.get('response', '').strip()
        print(f"[RAG] Ollama Response: {response_text[:300]}...")
        
        # 8. JSON Validation & self-repair loop
        data = None
        try:
            data = json.loads(response_text)
            json_validation = "Success"
        except json.JSONDecodeError as je:
            print(f"[RAG] JSON malformed: {str(je)}. Requesting Ollama self-repair...")
            repair_prompt = f"""
            You are a JSON syntax repair assistant.
            The following raw text was returned by an LLM but failed JSON parsing with error: {str(je)}
            
            Raw text:
            {response_text}
            
            Fix the formatting, escape any unescaped quotes inside JSON string fields, and return ONLY valid, parseable JSON matching the quiz schema:
            {{
              "title": "Topic Quiz",
              "questions": [
                {{
                  "question": "question text",
                  "options": ["option1", "option2", "option3", "option4"],
                  "answer": "exact correct option string",
                  "explanation": "explanation"
                }}
              ]
            }}
            """
            repair_payload = {
                "model": selected_model,
                "prompt": repair_prompt,
                "stream": False,
                "format": "json"
            }
            repair_res = requests.post(url_generate, json=repair_payload, timeout=60.0)
            if repair_res.status_code == 200:
                repaired_text = repair_res.json().get('response', '').strip()
                try:
                    data = json.loads(repaired_text)
                    json_validation = "Repaired"
                except Exception as ex:
                    raise Exception(f"Ollama JSON repair output was also malformed: {str(ex)}")
            else:
                raise Exception("Ollama JSON self-repair failed to complete.")
                
        generation_time = time.time() - gen_start
        total_time = time.time() - start_time
        
        metadata_file = os.path.join(VECTOR_STORE_DIR, "metadata.json")
        cache_hits = "Yes" if os.path.exists(metadata_file) else "No"
        
        diagnostics = {
            "subject": detected_subject,
            "topic": detected_topic,
            "avg_similarity": round(float(avg_confidence), 3),
            "confidence_score": round(float(max_confidence), 3),
            "generation_time": round(generation_time, 2),
            "total_time": round(total_time, 2),
            "retrieval_precision": f"{precision}%",
            "retrieval_recall": f"{recall}%",
            "chunk_coverage": f"{chunk_coverage} chunks",
            "hallucination_risk": "Low" if max_confidence >= 0.8 else "Medium",
            "cache_hits": cache_hits,
            "json_validation": json_validation,
            "stages_executed": " -> ".join(stage_log)
        }
        
        desc_diagnostics = f"Generated from local study materials. ---DIAGNOSTICS--- {json.dumps(diagnostics)}"
        
        print("[RAG] Writing generated quiz to database...")
        quiz_id = parse_and_save_quiz_with_explanation(data, num_questions, desc_diagnostics)
        
        print(f"[RAG] Quiz generation successful! Total execution time: {total_time:.2f} seconds.")
        return quiz_id
        
    except requests.exceptions.RequestException as re:
        raise Exception(f"Could not connect to local Ollama server: {str(re)}")
    except Exception as ex:
        raise Exception(f"Failed to generate quiz: {str(ex)}")
