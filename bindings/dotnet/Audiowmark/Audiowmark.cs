using System;
using System.Collections.Generic;
using System.Globalization;

namespace Audiowmark
{
    public enum ErrorCode : int { Argument = 1, Io = 2, Internal = 3, Busy = 4, Memory = 5 }
    public sealed class AudiowmarkException : Exception
    {
        public ErrorCode Code { get; }
        public AudiowmarkException(ErrorCode code, string message) : base(message) { Code = code; }
    }
    public enum SpeedMode : uint { None = 0, Detect = 1, Patient = 2, Manual = 3 }
    public enum BlockType : uint { A = 1, B = 2, Ab = 3, All = 4, ClipA = 5, ClipB = 6, ClipAb = 7 }
    public sealed class Options
    {
        public double Strength { get; set; } = 10;
        public double SyncThreshold { get; set; } = .35;
        public double ChunkMinutes { get; set; } = 30;
        public SpeedMode SpeedMode { get; set; } = SpeedMode.None;
        public double Speed { get; set; } = 1;
        public uint NBest { get; set; } = 8;
        public uint Workers { get; set; } = 1;
        internal NativeOptions ToNative()
        {
            NativeOptions o; Native.audiowmark_options_init(out o);
            o.Strength = Strength; o.SyncThreshold = SyncThreshold; o.ChunkMinutes = ChunkMinutes;
            o.SpeedMode = (uint)SpeedMode; o.Speed = Speed; o.NBest = NBest; o.Workers = Workers;
            return o;
        }
    }
    public sealed class Payload : IEquatable<Payload>
    {
        private readonly byte[] bytes;
        public Payload(byte[] bytes)
        {
            if (bytes == null) throw new ArgumentNullException(nameof(bytes));
            if (bytes.Length != 16) throw new ArgumentException("Payload requires exactly 16 bytes.", nameof(bytes));
            this.bytes = (byte[])bytes.Clone();
        }
        public byte[] ToBytes() { return (byte[])bytes.Clone(); }
        public static Payload FromHex(string hex)
        {
            if (hex == null) throw new ArgumentNullException(nameof(hex));
            if (hex.Length != 32) throw new FormatException("Payload requires 32 hexadecimal digits.");
            var result = new byte[16];
            for (int i = 0; i < 16; ++i)
                result[i] = byte.Parse(hex.Substring(i * 2, 2), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture);
            return new Payload(result);
        }
        public override string ToString() { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
        public bool Equals(Payload other)
        {
            if (other == null) return false;
            for (int i = 0; i < 16; ++i) if (bytes[i] != other.bytes[i]) return false;
            return true;
        }
        public override bool Equals(object obj) { return Equals(obj as Payload); }
        public override int GetHashCode() { unchecked { int hash = 17; foreach (byte b in bytes) hash = hash * 31 + b; return hash; } }
    }
    public sealed class Detection
    {
        public Payload Payload { get; }
        public uint KeyIndex { get; }
        public string KeyName { get; }
        public BlockType BlockType { get; }
        public double TimeSeconds { get; }
        public double Quality { get; }
        public double DecodeError { get; }
        public double Ranking { get; }
        public double Speed { get; }
        internal Detection(NativeDetection d, string name)
        {
            Payload = new Payload(d.Payload); KeyIndex = d.KeyIndex; KeyName = name; BlockType = (BlockType)d.BlockType;
            TimeSeconds = d.TimeSeconds; Quality = d.Quality; DecodeError = d.DecodeError; Ranking = d.Ranking; Speed = d.Speed;
        }
    }
    /// <summary>Native SDK version information. Libraries are selected from NuGet runtime assets.</summary>
    public static class Library
    {
        public const uint AbiVersion = 1;
        public static string Version { get { Native.Initialize(); return Utf8.Copy(Native.audiowmark_version()); } }
    }
    public sealed class Key : IDisposable
    {
        private readonly object gate = new object();
        private readonly KeyHandle handle;
        private Key(IntPtr pointer) { handle = new KeyHandle(pointer); }
        private delegate int CreateKey(IntPtr value, out IntPtr key, out IntPtr error);
        private static Key Create(string value, CreateKey create)
        {
            Native.Initialize();
            using (var utf8 = new Utf8(value))
            {
                IntPtr pointer, error; int status = create(utf8.Pointer, out pointer, out error);
                var key = new Key(pointer);
                try { Native.Check(status, error); if (key.handle.IsInvalid) throw new AudiowmarkException(ErrorCode.Internal, "Null native key."); return key; }
                catch { key.Dispose(); throw; }
            }
        }
        public static Key Generate(string name = "") { return Create(name, Native.audiowmark_key_generate); }
        public static Key Import(string cliText) { return Create(cliText, Native.audiowmark_key_import); }
        public static Key Load(string path) { return Create(path, Native.audiowmark_key_load); }
        private void EnsureAlive() { if (handle.IsClosed) throw new ObjectDisposedException(nameof(Key)); }
        public string Name { get { lock (gate) { EnsureAlive(); return Utf8.Copy(Native.audiowmark_key_name(handle)); } } }
        public string Export() { lock (gate) { EnsureAlive(); return Utf8.Copy(Native.audiowmark_key_export(handle)); } }
        public void Save(string path)
        {
            lock (gate) { EnsureAlive(); using (var utf8 = new Utf8(path))
            { IntPtr error; int status = Native.audiowmark_key_save(handle, utf8.Pointer, out error); Native.Check(status, error); } }
        }
        internal KeyHandle Retain(out IntPtr pointer)
        {
            lock (gate)
            {
                EnsureAlive(); bool retained = false;
                handle.DangerousAddRef(ref retained);
                pointer = handle.DangerousGetHandle(); return handle;
            }
        }
        public void Dispose() { lock (gate) handle.Dispose(); }
    }
    /// <summary>Synchronous context. Calls on one context are serialized; independent contexts run in parallel.</summary>
    public sealed class Context : IDisposable
    {
        private readonly object gate = new object();
        private readonly ContextHandle handle;
        public Context(Options options = null)
        {
            Native.Initialize(); var o = (options ?? new Options()).ToNative();
            IntPtr pointer, error; int status = Native.audiowmark_context_create(ref o, out pointer, out error);
            handle = new ContextHandle(pointer);
            try { Native.Check(status, error); if (handle.IsInvalid) throw new AudiowmarkException(ErrorCode.Internal, "Null native context."); }
            catch { handle.Dispose(); throw; }
        }
        private void EnsureAlive() { if (handle.IsClosed) throw new ObjectDisposedException(nameof(Context)); }
        public void SetKeys(params Key[] keys)
        {
            if (keys == null) throw new ArgumentNullException(nameof(keys));
            lock (gate)
            {
                EnsureAlive(); var pointers = new IntPtr[keys.Length]; var retained = new List<KeyHandle>(keys.Length);
                try
                {
                    for (int i = 0; i < keys.Length; ++i)
                    {
                        if (keys[i] == null) throw new ArgumentNullException(nameof(keys));
                        retained.Add(keys[i].Retain(out pointers[i]));
                    }
                    IntPtr error; int status = Native.audiowmark_context_set_keys(handle, pointers, checked((uint)pointers.Length), out error);
                    Native.Check(status, error);
                }
                finally { foreach (var key in retained) key.DangerousRelease(); }
            }
        }
        public void AddFile(string input, string output, Payload payload)
        {
            if (payload == null) throw new ArgumentNullException(nameof(payload));
            lock (gate) { EnsureAlive(); using (var i = new Utf8(input)) using (var o = new Utf8(output))
            { IntPtr error; int status = Native.audiowmark_add_file(handle, i.Pointer, o.Pointer, payload.ToBytes(), out error); Native.Check(status, error); } }
        }
        public IReadOnlyList<Detection> DetectFile(string path)
        {
            lock (gate) { EnsureAlive(); using (var utf8 = new Utf8(path))
            { IntPtr result, error; int status = Native.audiowmark_detect_file(handle, utf8.Pointer, out result, out error); return Results(status, result, error); } }
        }
        /// <summary>Watermark interleaved float32 PCM into a distinct array with the same sample count.</summary>
        public float[] AddPcm(float[] input, uint channels, uint sampleRate, Payload payload)
        {
            if (payload == null) throw new ArgumentNullException(nameof(payload));
            ulong frames = ValidatePcm(input, channels, sampleRate); var output = new float[input.Length];
            lock (gate) { EnsureAlive(); IntPtr error;
                int status = Native.audiowmark_add_pcm(handle, input, frames, channels, sampleRate, payload.ToBytes(), output, (ulong)output.Length, out error);
                Native.Check(status, error); return output; }
        }
        public IReadOnlyList<Detection> DetectPcm(float[] input, uint channels, uint sampleRate)
        {
            ulong frames = ValidatePcm(input, channels, sampleRate);
            lock (gate) { EnsureAlive(); IntPtr result, error;
                int status = Native.audiowmark_detect_pcm(handle, input, frames, channels, sampleRate, out result, out error);
                return Results(status, result, error); }
        }
        private static ulong ValidatePcm(float[] input, uint channels, uint rate)
        {
            if (input == null) throw new ArgumentNullException(nameof(input));
            if (channels < 1 || channels > 64 || rate < 8000 || rate > 384000 || (ulong)input.Length % channels != 0)
                throw new ArgumentException("Invalid PCM channels, rate or interleaved length.");
            foreach (float sample in input) if (float.IsNaN(sample) || float.IsInfinity(sample)) throw new ArgumentException("PCM samples must be finite.");
            return (ulong)input.Length / channels;
        }
        private static IReadOnlyList<Detection> Results(int status, IntPtr pointer, IntPtr error)
        {
            using (var result = new ResultHandle(pointer))
            {
                Native.Check(status, error);
                if (result.IsInvalid) throw new AudiowmarkException(ErrorCode.Internal, "Null native result.");
                ulong count = Native.audiowmark_result_count(result);
                var copied = new List<Detection>(checked((int)count));
                for (ulong index = 0; index < count; ++index)
                {
                    NativeDetection d; IntPtr getError;
                    int getStatus = Native.audiowmark_result_get(result, index, out d, out getError);
                    Native.Check(getStatus, getError);
                    copied.Add(new Detection(d, Utf8.Copy(Native.audiowmark_result_key_name(result, index))));
                }
                return copied.AsReadOnly();
            }
        }
        public void Dispose() { lock (gate) handle.Dispose(); }
    }
}
