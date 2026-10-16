#!/usr/bin/env python3
"""Run extracted assets in a temporary directory without a build/dependency prefix."""
import argparse
import ctypes
import json
import os
import pathlib
import struct
import subprocess
import tempfile
import wave

class Options(ctypes.Structure):
    _fields_ = [('struct_size',ctypes.c_uint32),('abi_version',ctypes.c_uint32),
                ('strength',ctypes.c_double),('sync_threshold',ctypes.c_double),
                ('chunk_minutes',ctypes.c_double),('speed',ctypes.c_double),
                ('speed_mode',ctypes.c_uint32),('n_best',ctypes.c_uint32),
                ('workers',ctypes.c_uint32),('reserved',ctypes.c_uint32)]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=pathlib.Path,required=True)
    parser.add_argument('--cli',type=pathlib.Path)
    args=parser.parse_args()
    sdk=args.sdk.resolve()
    candidates=[p for p in (sdk/'lib').iterdir() if p.name in ('audiowmark.dll','libaudiowmark.so','libaudiowmark.dylib')]
    if len(candidates)!=1: raise RuntimeError('expected one library')
    metadata=json.loads((sdk/'metadata.json').read_text())
    library=ctypes.CDLL(str(candidates[0]))
    library.audiowmark_abi_version.restype=ctypes.c_uint32
    library.audiowmark_version.restype=ctypes.c_char_p
    if library.audiowmark_abi_version()!=1: raise RuntimeError('wrong ABI')
    if library.audiowmark_version().decode()!=metadata['version']: raise RuntimeError('library/package version mismatch')
    library.audiowmark_options_init.argtypes=[ctypes.POINTER(Options)]
    library.audiowmark_context_create.argtypes=[ctypes.POINTER(Options),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p)]
    library.audiowmark_context_create.restype=ctypes.c_int32
    library.audiowmark_context_free.argtypes=[ctypes.c_void_p]
    library.audiowmark_detect_file.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p)]
    library.audiowmark_detect_file.restype=ctypes.c_int32
    library.audiowmark_error_free.argtypes=[ctypes.c_void_p]
    library.audiowmark_result_free.argtypes=[ctypes.c_void_p]
    library.audiowmark_result_count.argtypes=[ctypes.c_void_p]
    library.audiowmark_result_count.restype=ctypes.c_uint64
    options=Options();library.audiowmark_options_init(ctypes.byref(options))
    if options.struct_size!=56 or options.workers!=1: raise RuntimeError('bad defaults')
    context=ctypes.c_void_p();error=ctypes.c_void_p();result=ctypes.c_void_p()
    if library.audiowmark_context_create(ctypes.byref(options),ctypes.byref(context),ctypes.byref(error))!=0: raise RuntimeError('context creation failed')
    try:
        with tempfile.TemporaryDirectory(prefix='audiowmark-package-') as directory:
            work=pathlib.Path(directory)
            missing=str(work/'missing.wav').encode('utf-8')
            if library.audiowmark_detect_file(context,missing,ctypes.byref(result),ctypes.byref(error))!=2: raise RuntimeError('missing file must return I/O error')
            library.audiowmark_error_free(error);error=ctypes.c_void_p()
            wav=work/'dźwięk-音.wav'
            with wave.open(str(wav),'wb') as audio:
                audio.setparams((2,2,44100,0,'NONE','not compressed'))
                audio.writeframes(struct.pack('<hh',0,0)*44100)
            if library.audiowmark_detect_file(context,str(wav).encode('utf-8'),ctypes.byref(result),ctypes.byref(error))!=0: raise RuntimeError('context failed after I/O error / UTF-8 path failure')
            if library.audiowmark_result_count(result)!=0: raise RuntimeError('silence detection not empty')
            library.audiowmark_result_free(result)
            if args.cli:
                cli=args.cli.resolve()
                env=os.environ.copy()
                for key in ('LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH'):
                    env.pop(key,None)
                if os.name=='nt': env['PATH']=os.environ.get('SystemRoot','C:\\Windows')+'\\System32'
                else: env['PATH']='/usr/bin:/bin'
                subprocess.run([str(cli),'--version'],cwd=work,env=env,check=True)
                output=work/'marked.wav'
                subprocess.run([str(cli),'add',str(wav),str(output),'0123456789abcdef0011223344556677'],cwd=work,env=env,check=True)
                with wave.open(str(output),'rb') as audio:
                    if (audio.getnframes(),audio.getnchannels(),audio.getframerate())!=(44100,2,44100): raise RuntimeError('CLI changed audio layout')
                # Exercise binary stdin/stdout outside MSYS2, including Windows CRT text-mode hazards.
                piped=subprocess.run([str(cli),'add','-','-','0123456789abcdef0011223344556677'],input=wav.read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=work,env=env,check=True)
                if piped.stdout[:4] not in (b'RIFF',b'RF64'): raise RuntimeError('CLI stdout is not a binary WAV')
    finally:
        library.audiowmark_context_free(context)
    print('extracted SDK/CLI smoke passed')

if __name__=='__main__': main()
