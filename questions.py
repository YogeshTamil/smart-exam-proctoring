"""
Sample question bank for the demo exam.

This is intentionally simple (a hardcoded list) so the project's focus stays
on the proctoring pipeline. Swap this for a database-backed bank keyed by
exam_id whenever you need multiple exams or an authoring UI.
"""

QUESTIONS = [
    {
        "id": 1,
        "prompt": "Which data structure uses LIFO (Last In, First Out) ordering?",
        "options": ["Queue", "Stack", "Linked List", "Graph"],
        "answer": "Stack",
    },
    {
        "id": 2,
        "prompt": "In HTTP, which status code means 'Not Found'?",
        "options": ["200", "301", "404", "500"],
        "answer": "404",
    },
    {
        "id": 3,
        "prompt": "What does SQL stand for?",
        "options": [
            "Structured Query Language",
            "Simple Query Logic",
            "Sequential Query List",
            "System Query Language",
        ],
        "answer": "Structured Query Language",
    },
    {
        "id": 4,
        "prompt": "Which sorting algorithm has the best average-case time complexity?",
        "options": ["Bubble Sort", "Selection Sort", "Quick Sort", "Insertion Sort"],
        "answer": "Quick Sort",
    },
    {
        "id": 5,
        "prompt": "In Python, which keyword defines a function?",
        "options": ["func", "def", "lambda", "function"],
        "answer": "def",
    },
]

EXAM_DURATION_SECONDS = 10 * 60  # 10 minutes, adjust as needed
