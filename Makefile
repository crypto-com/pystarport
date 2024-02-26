test:
	@(cd pystarport/tests && poetry run pytest)

lint:
	@poetry run flake8 --show-source --count --statistics
	@poetry run isort --check-only .

lint-ci:
	@flake8 --show-source --count --statistics \
          --format="::error file=%(path)s,line=%(row)d,col=%(col)d::%(path)s:%(row)d:%(col)d: %(code)s %(text)s"
