import requests

def test_login():
    url = "http://127.0.0.1:51235/api/auth/login"
    data = {
        "username": "admin",
        "password": "Admin@123"
    }
    
    try:
        response = requests.post(url, json=data)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_login()
