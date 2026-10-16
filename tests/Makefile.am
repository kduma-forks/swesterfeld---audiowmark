CHECKS = detect-speed-test block-decoder-test clip-decoder-test \
       pipe-test short-payload-test sync-test sample-rate-test \
       key-test wav-pipe-test wav-subformat-test test-programs

if COND_WITH_FFMPEG
CHECKS += hls-test raw-format-test testhls-open-failure
if COND_VIDEOWMARK
CHECKS += full-test
endif
endif

EXTRA_DIST = detect-speed-test.sh block-decoder-test.sh clip-decoder-test.sh \
       pipe-test.sh short-payload-test.sh sync-test.sh sample-rate-test.sh \
       key-test.sh hls-test.sh wav-pipe-test.sh wav-subformat-test.sh test-programs.sh \
       raw-format-test.sh full-test.py fixtures/README fixtures/video-vp8.webm

check: $(CHECKS)

detect-speed-test:
	Q=1 $(top_srcdir)/tests/detect-speed-test.sh

block-decoder-test:
	Q=1 $(top_srcdir)/tests/block-decoder-test.sh

clip-decoder-test:
	Q=1 $(top_srcdir)/tests/clip-decoder-test.sh

pipe-test:
	Q=1 $(top_srcdir)/tests/pipe-test.sh

wav-pipe-test:
	Q=1 $(top_srcdir)/tests/wav-pipe-test.sh

wav-subformat-test:
	Q=1 $(top_srcdir)/tests/wav-subformat-test.sh

short-payload-test:
	Q=1 $(top_srcdir)/tests/short-payload-test.sh

sync-test:
	Q=1 $(top_srcdir)/tests/sync-test.sh

sample-rate-test:
	Q=1 $(top_srcdir)/tests/sample-rate-test.sh

key-test:
	Q=1 $(top_srcdir)/tests/key-test.sh

hls-test:
	Q=1 $(top_srcdir)/tests/hls-test.sh

raw-format-test:
	Q=1 $(top_srcdir)/tests/raw-format-test.sh

testhls-open-failure:
	$(top_builddir)/src/testhls open-failure-cleanup

test-programs:
	Q=1 $(top_srcdir)/tests/test-programs.sh

# Tests videowmark and HLS with ffmpeg/ffprobe copied beside the programs under test. Tools are taken
# from the build directory (bundled builds) or else from PATH. Python 3 is required (checked by
# configure). Use FULL_TEST_ARGS=--smoke for a short run.
full-test:
	@if test -z "$(PYTHON)"; then echo "full-test: Python 3 is required but was not found by configure" >&2; exit 1; fi; \
	stage="full-test-bin.$$$$"; rm -rf "$$stage"; mkdir "$$stage" || exit 1; \
	trap 'rm -rf "$$stage"' EXIT; \
	for program in audiowmark videowmark; do \
	  cp "$(top_builddir)/src/$$program$(EXEEXT)" "$$stage/" || exit 1; \
	done; \
	for tool in ffmpeg ffprobe; do \
	  if test -f "$(top_builddir)/src/$$tool$(EXEEXT)"; then source="$(top_builddir)/src/$$tool$(EXEEXT)"; \
	  else source=`command -v "$$tool$(EXEEXT)"`; fi; \
	  test -n "$$source" || { echo "full-test: $$tool not found" >&2; exit 1; }; \
	  cp "$$source" "$$stage/" || exit 1; \
	done; \
	"$(PYTHON)" "$(top_srcdir)/tests/full-test.py" --bin-dir "$$stage" $(FULL_TEST_ARGS)
