.PHONY: test validate compile-all list run-node-down

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

validate:
	python3 -m framework.cli validate intents/*.md

compile-all:
	python3 -m framework.cli compile-all --intent-dir intents --out-dir generated

list:
	python3 -m framework.cli list --intent-dir intents

run-node-down:
	python3 -m framework.cli run intents/02-node-down.md \
		--starcoin-bin /Users/simon/starcoin-projects/starcoin/target/debug/starcoin \
		--base-port 26000 \
		--node-count 2 \
		--fault-duration 20
