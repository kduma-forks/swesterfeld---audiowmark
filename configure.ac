AC_INIT([audiowmark],[0.6.5])
AC_CONFIG_SRCDIR([src/audiowmark.cc])
AC_CONFIG_AUX_DIR([build-aux])
AC_CONFIG_MACRO_DIR([m4])
AC_CONFIG_HEADERS([config.h])
AM_INIT_AUTOMAKE([foreign])
AC_PROG_CC
AC_PROG_CXX
AM_PROG_AR
AC_CANONICAL_HOST
AC_ARG_ENABLE([static-deps], [AS_HELP_STRING([--enable-static-deps], [request static dependency link flags from pkg-config])], [], [enable_static_deps=no])
# MinGW can embed static COFF archives in DLLs. Libtool's default DLL/import
# archive check otherwise rejects them and silently builds a static module.
AS_CASE([$host_os], [mingw*], [
  AS_IF([test "x$enable_static_deps" = xyes], [lt_cv_deplibs_check_method=pass_all])
])
LT_INIT
AM_CONDITIONAL([COND_ELF], [test "x$host_os" != "x${host_os#linux}"])
AM_CONDITIONAL([COND_WINDOWS], [test "x$host_os" != "x${host_os#mingw}"])
AM_CONDITIONAL([COND_WINDOWS_STATIC_SDK],
  [test "x$host_os" != "x${host_os#mingw}" && test "x$enable_shared" = xno])
AC_ARG_ENABLE([videowmark], [AS_HELP_STRING([--disable-videowmark], [do not build or install videowmark])], [], [enable_videowmark=yes])
AM_CONDITIONAL([COND_VIDEOWMARK], [test "x$enable_videowmark" = xyes])
AC_ARG_ENABLE([bundled-tools], [AS_HELP_STRING([--enable-bundled-tools], [require helper programs beside the executable, without PATH fallback])], [], [enable_bundled_tools=no])
AS_CASE([$enable_bundled_tools], [yes], [bundled_tools=1], [no], [bundled_tools=0],
  [AC_MSG_ERROR([--enable-bundled-tools accepts only yes or no])])
AC_DEFINE_UNQUOTED([AUDIOWMARK_BUNDLED_TOOLS], [$bundled_tools], [Require bundled helper programs])
AC_ARG_VAR([AUDIOWMARK_CLI_LDFLAGS], [extra flags for standalone CLI only (for example -all-static)])
AC_PATH_PROGS([PYTHON], [python3 python])
AS_IF([test -n "$PYTHON"], [
  AS_IF(["$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1],
    [], [PYTHON=""])
])
AC_ARG_VAR([AUDIOWMARK_SHARED_LDFLAGS], [extra flags for SDK only (for example -static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL)])

AC_C_BIGENDIAN()

dnl
dnl sndfile
dnl
AC_DEFUN([AC_SNDFILE_REQUIREMENTS],
[
    PKG_CHECK_MODULES(SNDFILE, [sndfile])
    AC_SUBST(SNDFILE_CFLAGS)
    AC_SUBST(SNDFILE_LIBS)
])

dnl
dnl libmpg123
dnl
AC_DEFUN([AC_LIBMPG123_REQUIREMENTS],
[
    PKG_CHECK_MODULES(LIBMPG123, [libmpg123])
    AC_SUBST(LIBMPG123_CFLAGS)
    AC_SUBST(LIBMPG123_LIBS)
])

dnl
dnl zita resampler
dnl
AC_DEFUN([AC_ZITA_REQUIREMENTS],
[
    AC_LIB_HAVE_LINKFLAGS([zita-resampler])
    if test "x$HAVE_LIBZITA_RESAMPLER" = "xno"; then
        AC_MSG_ERROR([You need to install libzita-resampler to build this package.])
    fi
])

dnl ffmpeg stuff
AC_DEFUN([AC_FFMPEG_REQUIREMENTS],
[
  PKG_CHECK_MODULES(FFMPEG, libavcodec libavformat libavutil libswresample)
])

dnl FFTW3
AC_DEFUN([AC_FFTW_CHECK],
[
    dnl this used to be optional, but is currently required
    PKG_CHECK_MODULES(FFTW, [fftw3f])

    SPECTMORPH_HAVE_FFTW=1
    if test $SPECTMORPH_HAVE_FFTW -gt 0; then
    fftw_save_CFLAGS="$CFLAGS"
    CFLAGS="$CFLAGS $FFTW_CFLAGS"
    AC_MSG_CHECKING([whether FFTW is recent enough])
      AC_COMPILE_IFELSE([
        AC_LANG_SOURCE([
          #include "fftw3.h"
          int x = FFTW_WISDOM_ONLY;
        ])
      ],[
        AC_MSG_RESULT([yes])
      ],[
        AC_MSG_RESULT([no])
        SPECTMORPH_HAVE_FFTW=0
      ])
    fi
    CFLAGS="$fftw_save_CFLAGS"
    AC_DEFINE_UNQUOTED(SPECTMORPH_HAVE_FFTW, $SPECTMORPH_HAVE_FFTW, [Whether libfftw3 is available])
])

dnl libgcrypt
AC_DEFUN([AC_LIBGCRYPT_REQUIREMENTS],
[
    dnl newer libgcrypt versions provide a pkg-config file
    PKG_CHECK_MODULES(LIBGCRYPT, [libgcrypt], [have_libgcrypt=yes], [have_libgcrypt=no])

    dnl older libgcrypt versions provide libgcrypt-config
    if test "x$have_libgcrypt" != "xyes"; then
      AM_PATH_LIBGCRYPT([], [have_libgcrypt=yes])
    fi

    dnl fail if neither pkg-config file nor libgcrypt-config was found
    if test "x$have_libgcrypt" != "xyes"; then
      AC_MSG_ERROR([You need to install libgcrypt to build this package.])
    fi
])

PKG_PROG_PKG_CONFIG
AS_IF([test "x$enable_static_deps" = xyes], [PKG_CONFIG="$PKG_CONFIG --static"])
AC_SNDFILE_REQUIREMENTS
AC_LIBMPG123_REQUIREMENTS
AC_ZITA_REQUIREMENTS
AC_FFTW_CHECK
AC_LIBGCRYPT_REQUIREMENTS

dnl -------------------- ffmpeg is optional ----------------------------
AC_ARG_WITH([ffmpeg], [AS_HELP_STRING([--with-ffmpeg], [build against ffmpeg libraries])], [], [with_ffmpeg=no])
if test "x$with_ffmpeg" != "xno"; then
  AC_FFMPEG_REQUIREMENTS
  HAVE_FFMPEG=1
else
  HAVE_FFMPEG=0
fi
AC_DEFINE_UNQUOTED(HAVE_FFMPEG, $HAVE_FFMPEG, [whether ffmpeg libs are available])
AM_CONDITIONAL([COND_WITH_FFMPEG], [test "x$with_ffmpeg" != "xno"])
dnl -------------------------------------------------------------------------

dnl --------------- building documentation is optional ----------------------
AC_ARG_WITH([docs], [AS_HELP_STRING([--with-docs], [build documentation])], [], [with_docs=no])
AM_CONDITIONAL([COND_WITH_DOCS], [test "x$with_docs" != "xno"])
AC_ARG_VAR([DOC_VERSION], [version displayed in the technical documentation])
AC_ARG_VAR([DOC_COMMIT], [source commit displayed in the technical documentation])
AS_IF([test -z "$DOC_VERSION"], [DOC_VERSION="$PACKAGE_VERSION"])
AS_IF([test -z "$DOC_COMMIT"], [DOC_COMMIT="unknown"])
AS_IF([test "x$with_docs" != "xno"], [
  AC_PATH_PROG([PANDOC], [pandoc])
  AC_PATH_PROG([GNUPLOT], [gnuplot])
  AC_PATH_PROG([DOT], [dot])
  AC_PATH_PROG([XELATEX], [xelatex])
  AS_IF([test -z "$PANDOC" || test -z "$GNUPLOT" || test -z "$DOT" || test -z "$XELATEX" || test -z "$PYTHON"],
    [AC_MSG_ERROR([--with-docs requires pandoc, gnuplot, dot, xelatex and Python 3])])
  AC_MSG_CHECKING([for Python documentation modules])
  AS_IF(["$PYTHON" -c 'import pygraphviz, pandocfilters' >/dev/null 2>&1],
    [AC_MSG_RESULT([yes])], [AC_MSG_ERROR([--with-docs requires Python pygraphviz and pandocfilters])])
  AC_MSG_CHECKING([whether pandoc supports embedded resources])
  AS_IF(["$PANDOC" --help | grep -q -- --embed-resources],
    [AC_MSG_RESULT([yes])], [AC_MSG_ERROR([--with-docs requires pandoc 2.19 or newer (--embed-resources)])])
])
dnl -------------------------------------------------------------------------

dnl -------------------- address sanitizer ----------------------------------
AC_ARG_ENABLE([asan], [AS_HELP_STRING([--enable-asan], [build using address sanitizer])],
[
  CXXFLAGS="$CXXFLAGS -fsanitize=address -fno-omit-frame-pointer -fstack-protector-all -fno-inline"
  LDFLAGS="$LDFLAGS -lasan"
],
[
  enable_asan=no
])
dnl -------------------------------------------------------------------------

dnl -------------------- undefined behaviour sanitizer ----------------------
AC_ARG_ENABLE([ubsan], [AS_HELP_STRING([--enable-ubsan], [build using undefined behaviour sanitizer])],
[
  CXXFLAGS="$CXXFLAGS -fsanitize=undefined -fno-omit-frame-pointer -fstack-protector-all -fno-inline"
  LDFLAGS="$LDFLAGS -lubsan"
],
[
  enable_ubsan=no
])
dnl -------------------------------------------------------------------------

dnl -------------------- thread sanitizer -----------------------------------
AC_ARG_ENABLE([tsan], [AS_HELP_STRING([--enable-tsan], [build using thread sanitizer])],
[
  CXXFLAGS="$CXXFLAGS -fsanitize=thread -fno-omit-frame-pointer -fstack-protector-all -fno-inline"
  LDFLAGS="$LDFLAGS -ltsan"
],
[
  enable_tsan=no
])
dnl -------------------------------------------------------------------------

dnl -------------------- leak sanitizer -------------------------------------
AC_ARG_ENABLE([lsan], [AS_HELP_STRING([--enable-lsan], [build using leak sanitizer])],
[
  CXXFLAGS="$CXXFLAGS -fsanitize=leak -fno-omit-frame-pointer -fstack-protector-all -fno-inline"
  LDFLAGS="$LDFLAGS -llsan"
],
[
  enable_lsan=no
])
dnl -------------------------------------------------------------------------

dnl -------------------- glibcxx assertions ----------------------------------
AC_ARG_ENABLE(debug-cxx,AS_HELP_STRING([--enable-debug-cxx], [setup compiler flags to do C++ STL debug checks]),
[
  CXXFLAGS="$CXXFLAGS -D_GLIBCXX_DEBUG -D_GLIBCXX_DEBUG_PEDANTIC"
],
[
  enable_debug_cxx=no
])
dnl -------------------------------------------------------------------------

# need c++14 mode
AX_CXX_COMPILE_STDCXX_14(ext)

# use -Wall / -pthread if available
AC_LANG_PUSH([C++])
AX_CHECK_COMPILE_FLAG([-Wall],    [CXXFLAGS="$CXXFLAGS -Wall"])
AX_CHECK_COMPILE_FLAG([-pthread], [CXXFLAGS="$CXXFLAGS -pthread"])
AC_LANG_POP([C++])

# Less cluttered build output
m4_ifdef([AM_SILENT_RULES], [AM_SILENT_RULES([yes])])

# Libtool C++ postdeps append -lstdc++/-lgcc_s even when compiler static
# runtime flags were supplied. Put the requested runtime archives before them.
AUDIOWMARK_SDK_LIBTOOL_TAG=CXX
AUDIOWMARK_SDK_RUNTIME_LIBS=
AS_CASE([$AUDIOWMARK_SHARED_LDFLAGS], [*-static-libstdc++*], [
  AUDIOWMARK_SDK_LIBTOOL_TAG=CC
  audiowmark_cxx_archive=`$CXX -print-file-name=libstdc++.a`
  AS_IF([test -f "$audiowmark_cxx_archive"], [AUDIOWMARK_SDK_RUNTIME_LIBS="$audiowmark_cxx_archive"], [AC_MSG_ERROR([static libstdc++ archive unavailable])])
  AS_CASE([$host_os], [mingw*], [
    audiowmark_winpthread_archive=`$CXX -print-file-name=libwinpthread.a`
    AS_IF([test -f "$audiowmark_winpthread_archive"],
      [AUDIOWMARK_SDK_RUNTIME_LIBS="$AUDIOWMARK_SDK_RUNTIME_LIBS $audiowmark_winpthread_archive"],
      [AC_MSG_ERROR([static libwinpthread archive unavailable; install the MinGW winpthreads static library])])
  ])
])
AS_CASE([$AUDIOWMARK_SHARED_LDFLAGS], [*-static-libgcc*], [
  for audiowmark_runtime in libgcc.a libgcc_eh.a; do
    audiowmark_runtime_archive=`$CXX -print-file-name=$audiowmark_runtime`
    AS_IF([test -f "$audiowmark_runtime_archive"], [AUDIOWMARK_SDK_RUNTIME_LIBS="$AUDIOWMARK_SDK_RUNTIME_LIBS $audiowmark_runtime_archive"])
  done
])
AC_SUBST([AUDIOWMARK_SDK_RUNTIME_LIBS])
AC_SUBST([AUDIOWMARK_SDK_LIBTOOL_TAG])

AC_CONFIG_FILES([Makefile src/Makefile tests/Makefile tests/test-common.sh docs/Makefile manpages/Makefile])
AC_OUTPUT

# Output summary message

echo
echo "---------------------------------------------------------------------------"
echo "$PACKAGE_NAME $PACKAGE_VERSION"
echo "---------------------------------------------------------------------------"
echo "  Use address sanitizer. . . . . . . .: $enable_asan (for debugging)"
echo "  Use undefined behaviour sanitizer. .: $enable_ubsan (for debugging)"
echo "  Use thread sanitizer . . . . . . . .: $enable_tsan (for debugging)"
echo "  Use leak sanitizer . . . . . . . . .: $enable_lsan (for debugging)"
echo "  Use stdc++ debug mode. . . . . . . .: $enable_debug_cxx (for debugging)"
echo "  Use ffmpeg libs. . . . . . . . . . .: $with_ffmpeg (use --with-ffmpeg to enable, required for HLS)"
echo "  Build developer documentation  . . .: $with_docs (use --with-docs to enable)"
