#!/bin/bash
set -Eeo pipefail -x

# install dependencies
brew install autoconf-archive automake libsndfile fftw mpg123 libgcrypt libtool ffmpeg@7
export PKG_CONFIG_PATH="$(brew --prefix ffmpeg@7)/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export PATH="$(brew --prefix ffmpeg@7)/bin:$PATH"

# build zita-resampler
git clone https://github.com/swesterfeld/zita-resampler
cd zita-resampler
cmake .
sudo make install
cd ..
export DYLD_LIBRARY_PATH=/usr/local/lib:$DYLD_LIBRARY_PATH
# zita-resampler's install name is @rpath/libzita-resampler.dylib: record the run path in the programs,
# so copies of them (tests/full-test.py runs with DYLD_* removed) can load it too
export LDFLAGS="-Wl,-rpath,/usr/local/lib ${LDFLAGS:-}"

# build audiowmark
./autogen.sh
NPROC=`sysctl -n hw.ncpu`
make -j $NPROC
make  -j $NPROC check

# test build audiowmark with ffmpeg support (HLS, videowmark); the tests run with ffmpeg from PATH
make clean
./autogen.sh --with-ffmpeg
make -j $NPROC
make -j $NPROC check
