.PHONY: *
SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c
# Example: make T1
#
# Pick the server version (see config.py) with V=, e.g. make T3 V=2
# Outputs go to analytics/results/<TEST>_v<V>[_runNN].{csv,json} and <TEST>_v<V>.log
# Figures go to analytics/figures/
#
# Compare versions on one test (runs each version, then plots):
#   make compare TEST=T3 VERSIONS="2 3"
# Re-plot existing results without re-running:
#   make plot-compare TEST=T3 VERSIONS="2 3"
#   make plot TEST=HEAVY_SLOW V=3

V ?= $(shell python -c "from config import VERSION; print(VERSION)")
TEST ?= T3
VERSIONS ?= 2 3

OUT = analytics/results/$@_v$(V)
RUN = mkdir -p analytics/results && LIVERECALL_VERSION=$(V) python run_demo.py
LOG = 2>&1 | tee $(OUT).log

T1:
	$(RUN) --clients 20 --duration 20 --runs 3 --output-stem $(OUT) $(LOG)


T2:
	$(RUN) --clients 100 --duration 40 --runs 3 --output-stem $(OUT) $(LOG)


T3:
	$(RUN) --clients 100 --duration 60 --runs 3 \
	--slow-percent 10 --slow-ms 500 --output-stem $(OUT) $(LOG)


T4:
	$(RUN) --clients 100 --duration 60 --runs 3 \
	--disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
	--output-stem $(OUT) $(LOG)

HEAVY_SLOW:
	$(RUN) --clients 1000 --duration 600 --runs 1 \
	--slow-percent 90 --slow-ms 5000 --output-stem $(OUT) $(LOG)

HEAVY_DISCONNECT:
	$(RUN) --clients 1000 --duration 600 --runs 1 \
	--disconnect-percent 90 --disconnect-seconds 10 --output-stem $(OUT) $(LOG)

compare:
	for v in $(VERSIONS); do $(MAKE) $(TEST) V=$$v || exit 1; done
	$(MAKE) plot-compare TEST=$(TEST) VERSIONS="$(VERSIONS)"

plot-compare:
	python analytics/compare_versions.py $(TEST) $(VERSIONS)

plot:
	python analytics/plot_queue.py analytics/results/$(TEST)_v$(V).log \
	analytics/figures/$(TEST)_v$(V)_queue_length.png
