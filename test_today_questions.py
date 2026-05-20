from app import app, db, User
import json

with app.app_context():
    # Test user 48 (elisa)
    user = User.query.filter_by(UserId=48).first()
    if not user:
        print("User 48 not found!")
    else:
        print(f"Testing /api/today_questions for user: {user.UserName} (ID: {user.UserId})")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.UserId)
            sess['_fresh'] = True
        
        try:
            res = client.get('/api/today_questions', headers={'Accept': 'application/json'})
            print(f"Status: {res.status_code}")
            data = res.get_data(as_text=True)
            print(f"Response: {data[:500]}")  # truncate to 500 chars
        except Exception as e:
            import traceback
            traceback.print_exc()
