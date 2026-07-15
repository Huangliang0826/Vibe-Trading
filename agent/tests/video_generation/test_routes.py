from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.video_generation_routes import register_video_generation_routes


class FakeSeedanceClient:
    def __init__(self):
        self.created = None

    def create_task(self, payload):
        self.created = payload
        return {"id": "cgt-route", "status": "queued"}

    def get_task(self, task_id):
        return {"id": task_id, "status": "running"}


def test_create_and_query_video_task():
    app = FastAPI()
    fake = FakeSeedanceClient()
    register_video_generation_routes(app, require_auth=lambda: None, client=fake)
    client = TestClient(app)

    created = client.post("/video-generation/tasks", json={
        "prompt": "城市夜景",
        "image_urls": ["https://example.com/reference.jpg"],
        "ratio": "16:9",
        "resolution": "720p",
        "duration": 5,
        "generate_audio": True,
        "watermark": False,
    })
    queried = client.get("/video-generation/tasks/cgt-route")

    assert created.status_code == 200
    assert created.json()["id"] == "cgt-route"
    assert fake.created["image_urls"] == ["https://example.com/reference.jpg"]
    assert queried.json()["status"] == "running"


def test_rejects_unsafe_reference_urls_and_task_ids():
    app = FastAPI()
    register_video_generation_routes(app, require_auth=lambda: None, client=FakeSeedanceClient())
    client = TestClient(app)

    bad_url = client.post("/video-generation/tasks", json={
        "prompt": "test", "image_urls": ["file:///etc/passwd"],
    })
    bad_id = client.get("/video-generation/tasks/not%2Fa%2Ftask")

    assert bad_url.status_code == 422
    assert bad_id.status_code in {400, 404}
