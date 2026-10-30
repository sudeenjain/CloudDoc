# CloudDoc

**A Cloud-Based Intelligent Document Workspace**

CloudDoc AI is a web-based document processing application designed to simplify the way users interact with PDF documents. It provides a centralized workspace where users can upload documents, extract their content, and retrieve relevant information through an interactive interface.

Inspired by notebook-style research platforms, the project explores how cloud computing and AI-related technologies can improve document accessibility and information retrieval.

## Overview

Managing large PDF documents and finding relevant information manually can be time-consuming.

CloudDoc AI addresses this challenge by providing a document workspace with PDF processing, text extraction, and relevance-based information retrieval.

The project follows a client-server architecture, separating the frontend interface from backend processing.

## Key Features

- PDF document upload and processing
- Automatic text extraction from PDF files
- Document-based information retrieval
- TF-IDF-based relevance matching
- Interactive web interface
- REST API integration
- Backend health monitoring
- Document upload validation

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, FastAPI |
| PDF Processing | PyMuPDF |
| Information Retrieval | TF-IDF |
| API Communication | REST API |
| Development | Visual Studio Code / Google Antigravity |

## System Architecture

The application follows a client-server architecture.

1. **Frontend:** Provides the user interface for interacting with documents.
2. **Backend:** Handles document uploads, validation, PDF processing, and API requests.
3. **Processing Layer:** Extracts PDF text and performs relevance-based retrieval.
4. **API Layer:** Connects the frontend and backend through REST endpoints.

## Project Structure

```text
CloudDoc-work/
│
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── test_api.py
│   └── README.md
│
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── README.md
│
├── ai-tests/
│
├── API_CONTRACT.md
├── ARCHITECTURE.md
├── INTEGRATION_CHECKLIST.md
├── TASKS.md
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10+
- pip
- Git

### 1. Clone the repository

```bash
git clone https://github.com/sudeenjain/CloudDoc.git
```

### 2. Navigate to the backend

```bash
cd CloudDoc-work/backend
```

### 3. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Start the backend

```bash
uvicorn main:app --reload
```

### 6. Access the API documentation

Open:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Backend health check |
| GET | `/api/documents` | Retrieve documents |
| POST | `/api/documents` | Upload documents |
| POST | `/api/chat` | Document-related retrieval requests |

## Cloud Computing Concepts

This project explores important cloud computing principles:

- Client-server architecture
- Separation of frontend and backend services
- RESTful API communication
- Modular application design
- Document processing as a backend service
- Potential scalability through cloud deployment

## Project Status

**Development in Progress**

CloudDoc is currently under development. The current implementation focuses on PDF processing, text extraction, and TF-IDF-based information retrieval.

Advanced AI-generated answers, cloud deployment, and additional intelligent document features are potential future enhancements.

## Future Enhancements

- LLM-powered document question answering
- Multiple document knowledge workspace
- Cloud storage integration
- User authentication
- Document history and management
- Conversation history
- Scalable cloud deployment

## Author

**Sudeen Jain H R**

Artificial Intelligence and Machine Learning Student

GitHub: https://github.com/sudeenjain/CloudDoc

---

*CloudDoc — Making document interaction smarter and more accessible.*
