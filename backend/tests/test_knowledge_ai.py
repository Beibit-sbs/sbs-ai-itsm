def _login_admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@sbs.local", "password": "Sbs!2026"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_knowledge_categories_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/knowledge/categories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        categories = response.json()
        assert len(categories) >= 8
        assert {item["name"] for item in categories} >= {"Сеть и интернет", "Оборудование"}


def test_knowledge_articles_list(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        articles = response.json()
        assert len(articles) >= 20
        assert articles[0]["article_number"].startswith("KB-")


def test_knowledge_article_detail(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        list_response = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {token}"})
        article_id = list_response.json()[0]["id"]

        detail_response = client.get(f"/api/v1/knowledge/articles/{article_id}", headers={"Authorization": f"Bearer {token}"})
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["id"] == article_id
        assert detail["content"]


def test_knowledge_search(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.get("/api/v1/knowledge/search?q=интернет", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        results = response.json()
        assert len(results) >= 1


def test_article_feedback(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        article_id = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]

        response = client.post(
            f"/api/v1/knowledge/articles/{article_id}/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={"is_helpful": True, "comment": "Работает"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["article_id"] == article_id
        assert payload["is_helpful"] is True


def test_ai_analyze_ticket(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.post(
            "/api/v1/ai/analyze-ticket",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "Пользователь не может войти в систему"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommended_priority"]
        assert payload["summary"]


def test_ai_analyze_internet_issue(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.post(
            "/api/v1/ai/analyze-ticket",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "Нет интернета и не работает Wi-Fi в кабинете"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommended_category"] == "Сеть и интернет"
        assert payload["recommended_priority"] == "HIGH"


def test_ai_analyze_phishing_issue(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        response = client.post(
            "/api/v1/ai/analyze-ticket",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "Пришло подозрительное фишинговое письмо"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommended_category"] == "Информационная безопасность"
        assert payload["recommended_priority"] == "CRITICAL"


def test_create_article_from_resolved_ticket(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]

        patch_response = client.patch(
            f"/api/v1/tickets/{ticket_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "RESOLVED"},
        )
        assert patch_response.status_code == 200

        article_response = client.post(
            f"/api/v1/ai/create-article-from-ticket/{ticket_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert article_response.status_code == 201
        article_payload = article_response.json()
        assert article_payload["article_number"].startswith("KB-")
