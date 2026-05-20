from app import app, db, User
import json

with app.app_context():
    users = User.query.all()
    for user in users:
        print(f"\nTesting /timer for user: {user.UserName} (ID: {user.UserId})")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.UserId)
            sess['_fresh'] = True
        
        try:
            res = client.get('/timer', headers={'Accept': 'application/json'})
            print(f"Status /timer: {res.status_code}")
            if res.status_code == 200 and user.UserId == 48:
                print(f"Response /timer for {user.UserName}: {res.get_data(as_text=True)}")
                
                # Test POST /save_pomodoro
                post_res = client.post('/save_pomodoro', 
                                       data=json.dumps({"duration": 25, "type": "pomodoro"}),
                                       content_type='application/json')
                print(f"Status /save_pomodoro: {post_res.status_code}")
                print(f"Response /save_pomodoro: {post_res.get_data(as_text=True)}")
                
            if res.status_code == 500:
                print(res.get_data(as_text=True))
        except Exception as e:
            import traceback
            traceback.print_exc()


