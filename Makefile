# Rocky Vox -- development, deployment and on-device diagnostics.
#
# Local targets run on this machine; everything else is driven over SSH.

PI       ?= rocky
APP_DIR  ?= /opt/rocky
PORT     ?= 8080
# How audio leaves the Pi: i2s (DAC board), usb (sound card), pwm (RC filter).
AUDIO    ?= i2s
VENV     ?= .venv
PY       := $(VENV)/bin/python
SSH      := ssh $(PI)
V        ?= 30

# rsync writes into /opt, so the remote side elevates. Passwordless sudo.
RSYNC := rsync -az --delete --rsync-path="sudo rsync"
PAYLOAD := src deploy media docs Makefile pyproject.toml README.md

.DEFAULT_GOAL := help
.PHONY: help venv lint fmt test check hooks deploy provision restart stop logs \
        status shell i2c-scan aplay-l speaker-test volume trigger halt open \
        state clean

help: ## Show this help
	@grep -hE '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- local

$(VENV): pyproject.toml
	uv venv $(VENV)
	VIRTUAL_ENV=$(VENV) uv pip install -e '.[dev]'
	@touch $(VENV)

venv: $(VENV) ## Create the dev virtualenv

lint: $(VENV) ## Ruff lint
	$(VENV)/bin/ruff check src tests

fmt: $(VENV) ## Ruff format
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests

test: $(VENV) ## Run the test suite
	$(VENV)/bin/pytest

check: $(VENV) ## Everything pre-commit runs, over every file
	pre-commit run --all-files

hooks: ## Install the git pre-commit hook
	pre-commit install

clean: ## Remove build and cache artefacts
	rm -rf $(VENV) .pytest_cache .ruff_cache src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---------------------------------------------------------------- deploy

# A Zero W takes roughly eight seconds from restart to a bound port, so every
# target that restarts the service waits for it rather than racing it.
define wait_up
$(SSH) 'for i in $$(seq 1 60); do \
	  curl -fsS -o /dev/null http://127.0.0.1:$(PORT)/api/state 2>/dev/null && exit 0; \
	  sleep 0.5; \
	done; echo "service did not come up; try: make logs" >&2; exit 1'
endef

deploy: ## Push the code to the Pi and restart the service
	$(RSYNC) --exclude '__pycache__' $(PAYLOAD) $(PI):$(APP_DIR)/
	$(SSH) 'sudo systemctl restart rocky-vox'
	@$(wait_up)
	@echo "deployed to http://$$($(SSH) hostname).local:$(PORT)"

provision: ## Setup on the Pi; pick the audio path: make provision AUDIO=usb
	$(SSH) 'sudo mkdir -p $(APP_DIR) && sudo chown $$USER $(APP_DIR)'
	$(RSYNC) --exclude '__pycache__' $(PAYLOAD) $(PI):$(APP_DIR)/
	$(SSH) 'sudo AUDIO=$(AUDIO) $(APP_DIR)/deploy/provision.sh'

restart: ## Restart the service and wait for it to answer
	$(SSH) 'sudo systemctl restart rocky-vox'
	@$(wait_up)
	@echo "up"

stop: ## Stop the service
	$(SSH) 'sudo systemctl stop rocky-vox'

logs: ## Follow the service log
	$(SSH) 'journalctl -u rocky-vox -f -n 60 --no-pager'

status: ## Service status
	$(SSH) 'systemctl status rocky-vox --no-pager -l | head -25'

shell: ## SSH to the Pi
	$(SSH)

# ------------------------------------------------------------ hardware

# /usr/sbin is not on the PATH for a non-login SSH session on Debian 13.
i2c-scan: ## Scan the I2C bus; the MAX9744 should answer at 0x4b
	$(SSH) '/usr/sbin/i2cdetect -y 1'

aplay-l: ## List ALSA playback devices; expect the card for your AUDIO=
	$(SSH) 'aplay -l'

speaker-test: ## Two channels of pink noise through the amp
	$(SSH) 'speaker-test -D default -c 2 -t pink -l 1'

# --------------------------------------------------------------- control

volume: ## Set the amp volume, 0-63:  make volume V=40
	@curl -fsS -X POST -H 'Content-Type: application/json' \
		-d '{"value": $(V)}' http://$(PI_HOST):$(PORT)/api/volume; echo

trigger: ## Play the next clip without a magnet
	@curl -fsS -X POST http://$(PI_HOST):$(PORT)/api/trigger; echo

halt: ## Stop playback
	@curl -fsS -X POST http://$(PI_HOST):$(PORT)/api/stop; echo

state: ## Dump the service state as JSON
	@curl -fsS http://$(PI_HOST):$(PORT)/api/state

open: ## Open the control panel in a browser
	xdg-open http://$(PI_HOST):$(PORT)

# Resolved once, lazily, so the SSH round trip only happens for the
# targets that actually talk to the running service.
PI_HOST = $(shell $(SSH) hostname 2>/dev/null).local
