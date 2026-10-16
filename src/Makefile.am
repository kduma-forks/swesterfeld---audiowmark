bin_PROGRAMS = audiowmark
if COND_VIDEOWMARK
bin_PROGRAMS += videowmark
endif

COMMON_SRC = utils.hh utils.cc convcode.hh convcode.cc random.hh random.cc wavdata.cc wavdata.hh \
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
COMMON_LIBS += -ladvapi32
endif

AM_CXXFLAGS = $(SNDFILE_CFLAGS) $(FFTW_CFLAGS) $(LIBGCRYPT_CFLAGS) $(LIBMPG123_CFLAGS) $(FFMPEG_CFLAGS)

audiowmark_SOURCES = audiowmark.cc $(COMMON_SRC)
audiowmark_LDFLAGS = $(COMMON_LIBS) $(AUDIOWMARK_CLI_LDFLAGS)
if COND_WINDOWS
audiowmark_LDFLAGS += -lshell32
endif

# videowmark only drives ffprobe, ffmpeg and audiowmark; it does not need the audio libraries
videowmark_SOURCES = videowmark.cc utils.hh utils.cc process.cc process.hh
videowmark_LDFLAGS = $(AUDIOWMARK_CLI_LDFLAGS)
if COND_WINDOWS
videowmark_LDFLAGS += -lshell32 -ladvapi32
endif

noinst_PROGRAMS = testconvcode testrandom testmp3 teststream testlimiter testshortcode testmpegts testthreadpool \
		  testrawconverter testwavformat testprocess

testprocess_SOURCES = testprocess.cc utils.hh utils.cc process.cc process.hh
if COND_WINDOWS
testprocess_LDFLAGS = -ladvapi32
endif

testconvcode_SOURCES = testconvcode.cc $(COMMON_SRC)
testconvcode_LDFLAGS = $(COMMON_LIBS)

testrandom_SOURCES = testrandom.cc $(COMMON_SRC)
testrandom_LDFLAGS = $(COMMON_LIBS)

testmp3_SOURCES = testmp3.cc $(COMMON_SRC)
testmp3_LDFLAGS = $(COMMON_LIBS)

teststream_SOURCES = teststream.cc $(COMMON_SRC)
teststream_LDFLAGS = $(COMMON_LIBS)

testlimiter_SOURCES = testlimiter.cc $(COMMON_SRC)
testlimiter_LDFLAGS = $(COMMON_LIBS)

testshortcode_SOURCES = testshortcode.cc $(COMMON_SRC)
testshortcode_LDFLAGS = $(COMMON_LIBS)

testmpegts_SOURCES = testmpegts.cc $(COMMON_SRC)
testmpegts_LDFLAGS = $(COMMON_LIBS)

testthreadpool_SOURCES = testthreadpool.cc $(COMMON_SRC)
testthreadpool_LDFLAGS = $(COMMON_LIBS)

testrawconverter_SOURCES = testrawconverter.cc $(COMMON_SRC)
testrawconverter_LDFLAGS = $(COMMON_LIBS)

testwavformat_SOURCES = testwavformat.cc $(COMMON_SRC)
testwavformat_LDFLAGS = $(COMMON_LIBS)

if COND_WITH_FFMPEG
COMMON_SRC += hlsoutputstream.cc hlsoutputstream.hh

noinst_PROGRAMS += testhls
testhls_SOURCES = testhls.cc $(COMMON_SRC)
testhls_LDFLAGS = $(COMMON_LIBS)
endif
