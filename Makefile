.PHONY: test validate compile-all list

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

validate:
	python3 -m framework.cli validate intents/*.md

compile-all:
	python3 -m framework.cli compile-all --intent-dir intents --out-dir generated

list:
	python3 -m framework.cli list --intent-dir intents
