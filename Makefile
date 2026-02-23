.PHONY: test
test:
	docker compose build api
	docker run --rm -v "$$(pwd):/app" \
		-e DATABASE_URL="sqlite+aiosqlite:///:memory:" \
		-e INITIAL_ADMIN_PASSWORD="testpass123" \
		-e INITIAL_ADMIN_USERNAME="admin" \
		octane-core-api python -m pytest tests/ -v
