# docs/Makefile.am
#
# Out-of-tree safe: every input is referenced through $(srcdir), every product
# (including graphviz-images/ and the gnuplot inputs) is written to the build
# directory. Tools, DOC_VERSION and DOC_COMMIT come from configure --with-docs.

doc_DATA  = audiowmark.pdf audiowmark.html

GRAPHVIZ_PY = $(srcdir)/graphviz.py
DOC_SOURCE  = $(srcdir)/audiowmark.md

PANDOC      = @PANDOC@
GNUPLOT     = @GNUPLOT@
XELATEX     = @XELATEX@
DOC_VERSION = @DOC_VERSION@
DOC_COMMIT  = @DOC_COMMIT@

DOC_META = --metadata title="audiowmark $(DOC_VERSION)" \
	   --metadata subtitle="Technical documentation, commit $(DOC_COMMIT)" \
	   --metadata lang=en

# Literal names: make dist copies these relative to the source directory.
EXTRA_DIST = audiowmark.md graphviz.py example-spectrum.dat example-spectrum.gp \
	     videowmark-win.cc win-x64-build-guide.txt

# PDF and HTML may build in parallel (make -j): both read the same shared inputs and
# the graphviz-images/ directory is created once by a stamp rule. Diagram file names
# include the output extension, so svg and pdf renderings never collide.
graphviz-images/.stamp:
	mkdir -p graphviz-images
	touch $@

audiowmark.pdf: $(DOC_SOURCE) $(GRAPHVIZ_PY) example-spectrum.png graphviz-images/.stamp
	"$(PANDOC)" -F "$(GRAPHVIZ_PY)" --pdf-engine="$(XELATEX)" -V papersize:a4 -V geometry:margin=2cm $(DOC_META) "$(DOC_SOURCE)" -o "$@"

audiowmark.html: $(DOC_SOURCE) $(GRAPHVIZ_PY) example-spectrum.png graphviz-images/.stamp
	"$(PANDOC)" -F "$(GRAPHVIZ_PY)" --standalone --embed-resources --metadata pagetitle="audiowmark $(DOC_VERSION)" $(DOC_META) "$(DOC_SOURCE)" -o "$@"

# gnuplot resolves its data file relative to the working directory, so the inputs
# are copied into the build directory. In-tree builds (srcdir = .) use them directly.
example-spectrum.png: $(srcdir)/example-spectrum.dat $(srcdir)/example-spectrum.gp
	test "$(srcdir)" = . || cp "$(srcdir)/example-spectrum.dat" "$(srcdir)/example-spectrum.gp" .
	"$(GNUPLOT)" example-spectrum.gp

# DEPS: apt install -y pandoc graphviz gnuplot texlive-xetex python3-pygraphviz python3-pandocfilters

clean-local:
	rm -rf graphviz-images $(doc_DATA) example-spectrum.png
	test "$(srcdir)" = . || rm -f example-spectrum.dat example-spectrum.gp
