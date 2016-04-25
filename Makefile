.PHONY: all clean check check-relaxed

PYTHONFILES = $(wildcard *.py)

FLAKE8 = flake8
FLAKE8_OPTIONS = --exit-zero

all:
	@echo 'Valid make targets:'
	@echo '  check         - Analyze code with pyflakes and ${FLAKE8}'
	@echo '  check-relaxed - Analyze code with relaxed setting, ignoring some issues'
	@echo '  clean         - Remove all generated files'

check:
	python3 strbo_version.py
	python3 -m pyflakes $(PYTHONFILES)
	python3 -m ${FLAKE8} ${FLAKE8_OPTIONS} $(PYTHONFILES)

check-relaxed:
	python3 -m pyflakes $(PYTHONFILES)
	python3 -m ${FLAKE8} ${FLAKE8_OPTIONS} --ignore=E501,W504 $(PYTHONFILES)

clean:
	rm -rf __pycache__
	rm -f GPATH GRTAGS GTAGS tags types_py.taghl
