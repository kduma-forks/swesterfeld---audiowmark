using System;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Audiowmark
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeOptions
    {
        internal uint StructSize, AbiVersion;
        internal double Strength, SyncThreshold, ChunkMinutes, Speed;
        internal uint SpeedMode, NBest, Workers, Reserved;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeDetection
    {
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 16)] internal byte[] Payload;
        internal uint KeyIndex, BlockType;
        internal double TimeSeconds, Quality, DecodeError, Ranking, Speed;
    }
    internal sealed class Utf8 : IDisposable
    {
        private static readonly Encoding Encoding = new UTF8Encoding(false, true);
        internal IntPtr Pointer { get; private set; }
        internal Utf8(string value)
        {
            if (value == null) throw new ArgumentNullException(nameof(value));
            if (value.IndexOf('\0') >= 0) throw new ArgumentException("UTF-8 text cannot contain NUL.", nameof(value));
            var bytes = Encoding.GetBytes(value);
            Pointer = Marshal.AllocHGlobal(checked(bytes.Length + 1));
            Marshal.Copy(bytes, 0, Pointer, bytes.Length);
            Marshal.WriteByte(Pointer, bytes.Length, 0);
        }
        internal static string Copy(IntPtr pointer)
        {
            if (pointer == IntPtr.Zero) throw new AudiowmarkException(ErrorCode.Internal, "Native SDK returned a null UTF-8 string.");
            int length = 0;
            while (Marshal.ReadByte(pointer, length) != 0) length = checked(length + 1);
            var bytes = new byte[length];
            Marshal.Copy(pointer, bytes, 0, length);
            return Encoding.GetString(bytes);
        }
        public void Dispose()
        {
            if (Pointer != IntPtr.Zero) { Marshal.FreeHGlobal(Pointer); Pointer = IntPtr.Zero; }
        }
    }
    internal sealed class ContextHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal ContextHandle(IntPtr p) : base(true) { SetHandle(p); }
        protected override bool ReleaseHandle() { Native.audiowmark_context_free(handle); return true; }
    }
    internal sealed class KeyHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal KeyHandle(IntPtr p) : base(true) { SetHandle(p); }
        protected override bool ReleaseHandle() { Native.audiowmark_key_free(handle); return true; }
    }
    internal sealed class ResultHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal ResultHandle(IntPtr p) : base(true) { SetHandle(p); }
        protected override bool ReleaseHandle() { Native.audiowmark_result_free(handle); return true; }
    }
    internal sealed class ErrorHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal ErrorHandle(IntPtr p) : base(true) { SetHandle(p); }
        protected override bool ReleaseHandle() { Native.audiowmark_error_free(handle); return true; }
    }
    internal static class Native
    {
        private const string Dll = "audiowmark";
        private static readonly object Gate = new object();
        private static bool initialized;
        internal static void Initialize()
        {
            lock (Gate)
            {
                if (initialized) return;
                // NuGet RID runtime assets (or the Framework app-local DLL)
                // select the module for every P/Invoke call. Never preload a
                // different module by path and assume basename resolution.
                if (IntPtr.Size != 8) throw new PlatformNotSupportedException("Audiowmark requires a 64-bit process.");
                if (Marshal.SizeOf<NativeOptions>() != 56 || Marshal.SizeOf<NativeDetection>() != 64)
                    throw new PlatformNotSupportedException("Audiowmark requires a supported 64-bit ABI.");
                if (audiowmark_abi_version() != 1)
                    throw new AudiowmarkException(ErrorCode.Internal, "Audiowmark native SDK ABI must be 1.");
                initialized = true;
            }
        }
        internal static void Check(int status, IntPtr error)
        {
            using (var owned = new ErrorHandle(error))
            {
                if (status == 0) return;
                var code = error == IntPtr.Zero ? status : audiowmark_error_code(owned);
                var message = error == IntPtr.Zero ? "Audiowmark native error " + status : Utf8.Copy(audiowmark_error_message(owned));
                throw new AudiowmarkException((ErrorCode)code, message);
            }
        }
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern uint audiowmark_abi_version();
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern IntPtr audiowmark_version();
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern void audiowmark_options_init(out NativeOptions options);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_context_create(ref NativeOptions options, out IntPtr context, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern void audiowmark_context_free(IntPtr context);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_context_set_keys(ContextHandle context, [In] IntPtr[] keys, uint count, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_key_generate(IntPtr name, out IntPtr key, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_key_import(IntPtr text, out IntPtr key, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_key_load(IntPtr path, out IntPtr key, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_key_save(KeyHandle key, IntPtr path, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern IntPtr audiowmark_key_export(KeyHandle key);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern IntPtr audiowmark_key_name(KeyHandle key);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern void audiowmark_key_free(IntPtr key);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_add_file(ContextHandle context, IntPtr input, IntPtr output, [In] byte[] payload, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_detect_file(ContextHandle context, IntPtr path, out IntPtr result, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_add_pcm(ContextHandle context, [In] float[] input, ulong frames, uint channels, uint rate, [In] byte[] payload, [Out] float[] output, ulong outputSamples, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_detect_pcm(ContextHandle context, [In] float[] input, ulong frames, uint channels, uint rate, out IntPtr result, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern ulong audiowmark_result_count(ResultHandle result);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_result_get(ResultHandle result, ulong index, out NativeDetection detection, out IntPtr error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern IntPtr audiowmark_result_key_name(ResultHandle result, ulong index);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern void audiowmark_result_free(IntPtr result);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern int audiowmark_error_code(ErrorHandle error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern IntPtr audiowmark_error_message(ErrorHandle error);
        [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        internal static extern void audiowmark_error_free(IntPtr error);
    }
}
