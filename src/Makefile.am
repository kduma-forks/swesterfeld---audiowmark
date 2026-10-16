bin_PROGRAMS = audiowmark
if COND_VIDEOWMARK
bin_PROGRAMS += videowmark
endif

ENGINE_SRC = utils.hh utils.cc convcode.hh convcode.cc random.hh random.cc wavdata.cc wavdata.hh \
	     audiostream.cc audiostream.hh sfinputstream.cc sfinputstream.hh stdoutwavoutputstream.cc stdoutwavoutputstream.hh \
	     sfoutputstream.cc sfoutputstream.hh rawinputstream.cc rawinputstream.hh rawoutputstream.cc rawoutputstream.hh \
	     rawconverter.cc rawconverter.hh mp3inputstream.cc mp3inputstream.hh wmcommon.cc wmcommon.hh fft.cc fft.hh \
	     limiter.cc limiter.hh shortcode.cc shortcode.hh mpegts.cc mpegts.hh hls.cc hls.hh audiobuffer.hh \
	     wmget.cc wmadd.cc syncfinder.cc syncfinder.hh wmspeed.cc wmspeed.hh threadpool.cc threadpool.hh \
	     resample.cc resample.hh wavpipeinputstream.cc wavpipeinputstream.hh wavchunkloader.cc wavchunkloader.hh \
	     process.cc process.hh
COMMON_LIBS = $(SNDFILE_LIBS) $(FFTW_LIBS) $(LIBGCRYPT_LIBS) $(LIBMPG123_LIBS) $(FFMPEG_LIBS) $(LTLIBZITA_RESAMPLER)
if COND_WINDOWS
# process.cc: security descriptors for private temporary directories
COMMON_LIBS += -ladvapi32 -lbcrypt
endif
AM_CPPFLAGS = -I$(top_srcdir)/include -I$(top_builddir)
AM_CXXFLAGS = $(SNDFILE_CFLAGS) $(FFTW_CFLAGS) $(LIBGCRYPT_CFLAGS) $(LIBMPG123_CFLAGS) $(FFMPEG_CFLAGS) -fvisibility=hidden -fvisibility-inlines-hidden
noinst_LTLIBRARIES = libengine.la
libengine_la_SOURCES = $(ENGINE_SRC)

# Convenience archive is linked directly into CLI: no SDK runtime dependency.
audiowmark_SOURCES = audiowmark.cc
audiowmark_LDADD = libengine.la $(COMMON_LIBS)
audiowmark_LDFLAGS = $(AUDIOWMARK_CLI_LDFLAGS)

# A module target avoids libtool's lib prefix/version suffix for Windows DLLs.
if COND_WINDOWS
audiowmark_LDADD += -lshell32
lib_LTLIBRARIES = audiowmark.la
audiowmark_la_SOURCES = c-api.cc
audiowmark_la_CPPFLAGS = $(AM_CPPFLAGS) -DAUDIOWMARK_BUILD
audiowmark_la_LIBADD = libengine.la $(COMMON_LIBS) $(AUDIOWMARK_SDK_RUNTIME_LIBS)
audiowmark_la_LDFLAGS = -module -avoid-version -no-undefined -export-symbols-regex '^audiowmark_' $(AUDIOWMARK_SHARED_LDFLAGS)
SDK_LIB = audiowmark.la
else
lib_LTLIBRARIES = libaudiowmark.la
libaudiowmark_la_SOURCES = c-api.cc
libaudiowmark_la_CPPFLAGS = $(AM_CPPFLAGS) -DAUDIOWMARK_BUILD
libaudiowmark_la_LIBADD = libengine.la $(COMMON_LIBS) $(AUDIOWMARK_SDK_RUNTIME_LIBS)
libaudiowmark_la_LDFLAGS = -version-info 1:0:0 -no-undefined $(AUDIOWMARK_SHARED_LDFLAGS)
SDK_LIB = libaudiowmark.la
if COND_ELF
libaudiowmark_la_LDFLAGS += -Wl,--version-script=$(srcdir)/audiowmark.map -Wl,--as-needed
EXTRA_libaudiowmark_la_DEPENDENCIES = $(srcdir)/audiowmark.map
else
libaudiowmark_la_LDFLAGS += -export-symbols-regex '^audiowmark_'
endif
endif

# videowmark only drives ffprobe, ffmpeg and audiowmark; it does not need the audio libraries
videowmark_SOURCES = videowmark.cc utils.hh utils.cc process.cc process.hh
videowmark_CPPFLAGS = $(AM_CPPFLAGS)
videowmark_LDFLAGS = $(AUDIOWMARK_CLI_LDFLAGS)
if COND_WINDOWS
videowmark_LDFLAGS += -lshell32 -ladvapi32
endif

noinst_PROGRAMS = testconvcode testrandom testmp3 teststream testlimiter testshortcode testmpegts testthreadpool \
		  testrawconverter testwavformat testprocess
testprocess_SOURCES = testprocess.cc
testprocess_LDADD = libengine.la $(COMMON_LIBS)
testconvcode_SOURCES = testconvcode.cc
testconvcode_LDADD = libengine.la $(COMMON_LIBS)
testrandom_SOURCES = testrandom.cc
testrandom_LDADD = libengine.la $(COMMON_LIBS)
testmp3_SOURCES = testmp3.cc
testmp3_LDADD = libengine.la $(COMMON_LIBS)
teststream_SOURCES = teststream.cc
teststream_LDADD = libengine.la $(COMMON_LIBS)
testlimiter_SOURCES = testlimiter.cc
testlimiter_LDADD = libengine.la $(COMMON_LIBS)
testshortcode_SOURCES = testshortcode.cc
testshortcode_LDADD = libengine.la $(COMMON_LIBS)
testmpegts_SOURCES = testmpegts.cc
testmpegts_LDADD = libengine.la $(COMMON_LIBS)
testthreadpool_SOURCES = testthreadpool.cc
testthreadpool_LDADD = libengine.la $(COMMON_LIBS)
testrawconverter_SOURCES = testrawconverter.cc
testrawconverter_LDADD = libengine.la $(COMMON_LIBS)
testwavformat_SOURCES = testwavformat.cc
testwavformat_LDADD = libengine.la $(COMMON_LIBS)

check_PROGRAMS = testapi
TESTS = testapi
testapi_SOURCES = testapi.cc
testapi_LDADD = $(SDK_LIB) libengine.la $(COMMON_LIBS)
if COND_WITH_FFMPEG
libengine_la_SOURCES += hlsoutputstream.cc hlsoutputstream.hh
noinst_PROGRAMS += testhls
testhls_SOURCES = testhls.cc
testhls_LDADD = libengine.la $(COMMON_LIBS)
endif

EXTRA_DIST = audiowmark.map

# Remove fixtures from interrupted tests as well as successful test runs.
clean-local:
	-rm -rf testapi-[0-9]*

# The C libtool tag omits C++ postdeps when explicit static runtime archives
# were requested. The C++ compiler still produces every engine object.
audiowmark_la_LINK = $(LIBTOOL) $(AM_V_lt) --tag=$(AUDIOWMARK_SDK_LIBTOOL_TAG) $(AM_LIBTOOLFLAGS) $(LIBTOOLFLAGS) --mode=link $(CXX) $(AM_CXXFLAGS) $(CXXFLAGS) $(audiowmark_la_LDFLAGS) $(LDFLAGS) -o $@
libaudiowmark_la_LINK = $(LIBTOOL) $(AM_V_lt) --tag=$(AUDIOWMARK_SDK_LIBTOOL_TAG) $(AM_LIBTOOLFLAGS) $(LIBTOOLFLAGS) --mode=link $(CXX) $(AM_CXXFLAGS) $(CXXFLAGS) $(libaudiowmark_la_LDFLAGS) $(LDFLAGS) -o $@
