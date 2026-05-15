import requests

TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjQ5MzE0ZDE2LTQzMzQtNGVkNC05OWU3LTdhMjBjZmNjNWM1NyIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL29wZGhpaGRieXRraG5sc25neHpyLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJlNzcxNDc2YS0xNDM3LTQyYzAtYmFjOS03ZTU0OTVmNGEzZGQiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzc4ODM0ODIzLCJpYXQiOjE3Nzg4MzEyMjMsImVtYWlsIjoieWFzaHUyMjEyMTIxQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWwiOiJ5YXNodTIyMTIxMjFAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwic3ViIjoiZTc3MTQ3NmEtMTQzNy00MmMwLWJhYzktN2U1NDk1ZjRhM2RkIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3Nzg4MzEyMjN9XSwic2Vzc2lvbl9pZCI6IjViNTU0MTU4LTFmNjEtNDg4MS1iOWU3LTIyNjg4M2E3NmM3ZCIsImlzX2Fub255bW91cyI6ZmFsc2V9.utLd72udQTS3oaqOFjL7gAeIAZAxLA2snWwLPXT-SjgGAKkuax9V-EUbrWiNMOTgFhBSBh-T2IU_BwybS0Nk9w"

res = requests.post(
    "http://127.0.0.1:8000/api/profile/save",
    headers={"authorization": f"Bearer {TOKEN}"},
    json={
        "full_name": "yashu",
        "platform": "Instagram",
        "handle": "yashu_BBB",
        "followers": 100000,
        "niche": "Money",
        "engagement_rate": 90,
        "bio": "something unexpected",
        "past_sponsors": [],
        "pricing_min": 2000,
        "pricing_max": 5000
    }
)

print(res.json())

res2 = requests.get(
    "http://127.0.0.1:8000/api/profile/me",
    headers={"authorization": f"Bearer {TOKEN}"}
)
print(res2.json())