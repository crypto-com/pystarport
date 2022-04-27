test:
	@(cd pystarport/tests && ./test_expansion/generate-test-yamls && poetry run pytest)

lint:
	@poetry run flake8 --show-source --count --statistics
	@poetry run isort --check-only .