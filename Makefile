.PHONY: *
# Example: make T1

T1:
	python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1


T2:
	python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2


T3:
	python run_demo.py --clients 100 --duration 60 --runs 3 \
	--slow-percent 10 --slow-ms 500 --output-stem t3


T4:
	python run_demo.py --clients 100 --duration 60 --runs 3 \
	--disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
	--output-stem t4
