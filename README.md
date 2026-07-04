# GetItDone

A productivity platform built for students to organize their academic workload, generate structured study plans, manage daily tasks, and track learning progress through a clean and intuitive interface.

**Live Demo:** https://study-optimizer-vrtz.onrender.com

**GitHub Repository:** https://github.com/lavanyapc/study_optimizer

---

## About the Project

Every student has experienced the feeling of knowing **what** needs to be done but struggling with **where to begin**.
During my own academic journey, I often found myself juggling notebooks, sticky notes, reminders, and multiple productivity apps just to keep track of assignments, deadlines, and study goals. Instead of making studying easier, managing everything became another task in itself.

That experience inspired **GetItDone**.

I built this application to solve a problem I personally faced. Rather than designing software around features first, I started with a simple question:
> *If I were going to use this every day, what would I actually need?*
In many ways, I was the first user of the application. Every feature was added only after considering whether it genuinely improved the study experience.
The goal of GetItDone is simple: help students spend less time planning and more time learning by providing a single place to organize their academic workflow.
---

## Features

- Secure user registration and authentication
- Personalized dashboard
- Study task management
- Structured study plan generation
- Progress tracking
- Performance analytics
- Productivity summary
- Clean and responsive interface

---

## Technology Stack

### Backend

- Python
- Flask
Flask was chosen because it provides a lightweight yet powerful framework for developing web applications. It allowed me to focus on building the application's logic while keeping the project modular and easy to maintain.

### Frontend

- HTML5
- CSS3
- JavaScript
The frontend was intentionally built using core web technologies instead of large frameworks. This helped strengthen my understanding of responsive layouts, client-side interactions, and clean interface design.

### Database

- SQLite
SQLite was selected because it is lightweight, easy to integrate with Flask, and well suited for a productivity application of this scale.

### Deployment

- Render
The application is deployed on Render, allowing users to access it directly through a web browser without requiring local installation.

---

## Why This Tech Stack?

One of my primary goals was to understand the complete lifecycle of building a web application.
Rather than relying heavily on external frameworks, I wanted to gain practical experience with each layer of development—from designing the interface and managing user sessions to storing data and deploying the final application.
This project gave me hands-on experience with:

- Full-stack web development
- User authentication
- Session management
- Database design
- Backend routing
- Frontend integration
- Git and GitHub workflows
- Cloud deployment
- Debugging production environments

Every technology used in this project was chosen because it contributed to both solving the problem and improving my understanding of modern web development.

---

## Application Workflow

1. Users create an account.
2. Users securely log in.
3. Study tasks are added and managed.
4. The application generates structured study plans.
5. Users track their productivity and progress.
6. Performance summaries provide insights into study habits.

---

## Project Structure

```
study_optimizer/
│
├── app.py
├── requirements.txt
├── templates/
├── static/
├── data/
├── README.md
└── .gitignore
```

---

## Challenges Faced

Developing GetItDone involved much more than writing application code.

Some of the major challenges included:

- Designing a modular Flask application
- Implementing secure authentication
- Managing persistent data using SQLite
- Organizing reusable templates
- Deploying the application successfully
- Understanding the differences between hosting platforms
- Debugging production deployment issues

Working through these challenges significantly improved my understanding of real-world software engineering and deployment workflows.

---

## Future Improvements

Some planned enhancements include:

- AI-generated study recommendations
- Pomodoro timer
- Email reminders
- Mobile application
- Cloud database integration for improved scalability

---

## Running the Project Locally

Clone the repository:

```bash
git clone https://github.com/lavanyapc/study_optimizer.git
```

Navigate into the project:

```bash
cd study_optimizer
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python app.py
```

Open your browser and visit:

```
http://127.0.0.1:5000
```

---

## Live Demo

https://study-optimizer-vrtz.onrender.com
