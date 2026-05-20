from app import app, db, PomodoroSession, Task

with app.app_context():
    try:
        sessions = PomodoroSession.query.all()
        for p in sessions:
            print(f"Session: ID={p.SessionId}, UserID={p.UserId}, Duration={p.Duration}, Type={p.Type}, CreatedAt={p.CreatedAt}")
            
        print("\nChecking Tasks:")
        tasks = Task.query.all()
        for t in tasks:
            print(f"Task: ID={t.TaskId}, UserID={t.UserId}, Title={t.Title}, Status={t.Status}, DueDate={t.DueDate}")
    except Exception as e:
        import traceback
        traceback.print_exc()
