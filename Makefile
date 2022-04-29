test:
	@(cd pystarport/tests && poetry run pytest)

lint:
	@poetry run flake8 --show-source --count --statistics
	@poetry run isort --check-only .