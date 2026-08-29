def _login_admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@sbs.local", "password": "Sbs!2026"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _login(client, email: str, password: str = "Sbs!2026"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
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
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"}).json()["items"][0]["id"]

        # Gate 0 makes the lifecycle graph authoritative: a NEW ticket cannot
        # jump directly to RESOLVED, even in a knowledge-flow fixture.
        for target_status in ("TRIAGE", "ASSIGNED", "IN_PROGRESS", "RESOLVED"):
            patch_response = client.patch(
                f"/api/v1/tickets/{ticket_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": target_status},
            )
            assert patch_response.status_code == 200

        article_response = client.post(
            f"/api/v1/ai/create-article-from-ticket/{ticket_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert article_response.status_code == 201
        article_payload = article_response.json()
        assert article_payload["article_number"].startswith("KB-")


def test_knowledge_articles_page_and_status_flow(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        categories = client.get("/api/v1/knowledge/categories", headers={"Authorization": f"Bearer {token}"}).json()
        response = client.post(
            "/api/v1/knowledge/articles",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Тест публикации",
                "summary": "Короткое summary",
                "content": "Подробное описание",
                "category_id": categories[0]["id"],
                "tags": ["test", "publish"],
                "status": "draft",
                "visibility": "internal",
            },
        )
        assert response.status_code == 201
        article_id = response.json()["id"]

        page = client.get(
            "/api/v1/knowledge/articles/page?page=1&page_size=5&status=draft",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert page.status_code == 200
        payload = page.json()
        assert payload["total"] >= 1
        assert isinstance(payload["items"], list)

        published = client.post(
            f"/api/v1/knowledge/articles/{article_id}/publish",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert published.status_code == 200
        assert published.json()["status"] == "published"

        archived = client.post(
            f"/api/v1/knowledge/articles/{article_id}/archive",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"


def test_ai_suggestion_accept_reject(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        analyzed = client.post(
            "/api/v1/ai/analyze-ticket",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "Не работает интернет в аудитории"},
        )
        assert analyzed.status_code == 200
        suggestion_id = analyzed.json()["id"]

        accepted = client.post(
            f"/api/v1/ai/suggestions/{suggestion_id}/accept",
            headers={"Authorization": f"Bearer {token}"},
            json={"rationale": "Подходит для текущего кейса"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"

        rejected = client.post(
            f"/api/v1/ai/suggestions/{suggestion_id}/reject",
            headers={"Authorization": f"Bearer {token}"},
            json={"rationale": "Нужна ручная обработка"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"


def test_ticket_knowledge_links_flow(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        token = _login_admin(client)
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"}).json()["items"][0]["id"]
        article_id = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]

        created = client.post(
            f"/api/v1/tickets/{ticket_id}/knowledge-links",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "article_id": article_id,
                "link_type": "manual",
                "confidence": 0.9,
                "comment": "Используем для решения",
            },
        )
        assert created.status_code == 201
        link = created.json()
        assert link["article_id"] == article_id

        listing = client.get(
            f"/api/v1/tickets/{ticket_id}/knowledge-links",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listing.status_code == 200
        assert len(listing.json()) >= 1

        deleted = client.delete(
            f"/api/v1/tickets/{ticket_id}/knowledge-links/{link['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deleted.status_code == 204


def test_rbac_requester_cannot_publish_or_archive(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        requester = _login(client, "requester@sbs.local")
        article_id = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {admin}"}).json()[0]["id"]

        publish = client.post(
            f"/api/v1/knowledge/articles/{article_id}/publish",
            headers={"Authorization": f"Bearer {requester}"},
        )
        assert publish.status_code == 403

        archive = client.post(
            f"/api/v1/knowledge/articles/{article_id}/archive",
            headers={"Authorization": f"Bearer {requester}"},
        )
        assert archive.status_code == 403


def test_rbac_manager_can_publish_and_archive(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        manager = _login(client, "manager@sbs.local")
        categories = client.get("/api/v1/knowledge/categories", headers={"Authorization": f"Bearer {admin}"}).json()
        created = client.post(
            "/api/v1/knowledge/articles",
            headers={"Authorization": f"Bearer {admin}"},
            json={
                "title": "RBAC publish test",
                "summary": "summary",
                "content": "content",
                "category_id": categories[0]["id"],
                "status": "draft",
                "visibility": "internal",
            },
        )
        assert created.status_code == 201
        article_id = created.json()["id"]

        publish = client.post(
            f"/api/v1/knowledge/articles/{article_id}/publish",
            headers={"Authorization": f"Bearer {manager}"},
        )
        assert publish.status_code == 200

        archive = client.post(
            f"/api/v1/knowledge/articles/{article_id}/archive",
            headers={"Authorization": f"Bearer {manager}"},
        )
        assert archive.status_code == 200


def test_rbac_requester_cannot_attach_internal_article(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        requester = _login(client, "requester@sbs.local")
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {admin}"}).json()["items"][0]["id"]
        article_id = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {admin}"}).json()[0]["id"]

        attach = client.post(
            f"/api/v1/tickets/{ticket_id}/knowledge-links",
            headers={"Authorization": f"Bearer {requester}"},
            json={"article_id": article_id, "link_type": "manual"},
        )
        assert attach.status_code == 403


def test_rbac_it_agent_can_attach_internal_article(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        admin = _login(client, "admin@sbs.local")
        agent = _login(client, "agent.support@sbs.local")
        ticket_id = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {admin}"}).json()["items"][0]["id"]
        article_id = client.get("/api/v1/knowledge/articles", headers={"Authorization": f"Bearer {admin}"}).json()[0]["id"]

        attach = client.post(
            f"/api/v1/tickets/{ticket_id}/knowledge-links",
            headers={"Authorization": f"Bearer {agent}"},
            json={"article_id": article_id, "link_type": "manual"},
        )
        assert attach.status_code == 201
