.PHONY: start stop restart logs backup export test shell

start:
	./manage.sh start

stop:
	./manage.sh stop

restart:
	./manage.sh stop && ./manage.sh start

logs:
	docker compose logs -f monitor

backup:
	./scripts/backup_db.sh

export:
	~/.local/bin/uv run scripts/export_deals.py

test:
	~/.local/bin/uv run pytest tests/ -v

shell:
	docker compose exec monitor bash
