using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Audiowmark;

internal static class Program
{
    private static void Require(bool ok, string message) { if (!ok) throw new Exception(message); }
    private static float[] Noise(uint rate, uint channels)
    {
        var samples = new float[checked((int)(rate * 40 * channels))]; uint state = 123456789;
        for (int i = 0; i < samples.Length; ++i)
        { state ^= state << 13; state ^= state >> 17; state ^= state << 5; samples[i] = (float)((double)state / uint.MaxValue * .5 - .25); }
        return samples;
    }
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 3) throw new ArgumentException("usage: Consumer INPUT.wav OUTPUT.wav WORK_DIR");
            Console.WriteLine("C# SDK " + Library.Version);
            var payload = Payload.FromHex("0123456789abcdef0123456789abcdef");
            using (var context = new Context())
            {
                using (var key = Key.Generate("C# żółw")) using (var imported = Key.Import(key.Export()))
                {
                    Require(key.Name == imported.Name && key.Export() == imported.Export(), "key text roundtrip");
                    var keyPath = Path.Combine(args[2], "csharp-klucz-żółw.key"); imported.Save(keyPath);
                    using (var loaded = Key.Load(keyPath)) Require(loaded.Export() == key.Export(), "key file roundtrip");
                    context.SetKeys(imported);
                }
                try { context.DetectFile(Path.Combine(args[2], "missing-żółw.wav")); throw new Exception("missing file succeeded"); }
                catch (AudiowmarkException e) { Require(e.Code == ErrorCode.Io, "I/O error code"); }
                try { context.AddPcm(new float[3], 2, 44100, payload); throw new Exception("invalid PCM succeeded"); }
                catch (ArgumentException) { }
                try { using (var invalid = new Context(new Options { Workers = 0 })) { } throw new Exception("invalid options succeeded"); }
                catch (AudiowmarkException e) { Require(e.Code == ErrorCode.Argument, "options error code"); }
                Require(context.DetectPcm(new float[0], 1, 44100).Count == 0, "empty PCM detection");
                Require(context.AddPcm(new float[0], 1, 44100, payload).Length == 0, "empty PCM add");
                context.AddFile(args[0], args[1], payload);
                var found = context.DetectFile(args[1]);
                Require(found.Any(d => d.Payload.Equals(payload) && d.KeyName == "C# żółw"), "file watermark missing");
                Require(found.All(d => d.KeyIndex == 0 && d.Speed > 0 && !double.IsNaN(d.Quality)), "typed detection fields");
                context.SetKeys();
                Require(context.DetectFile(args[1]).All(d => !d.Payload.Equals(payload)), "wrong key decoded known payload");
                var defaultFile = Path.Combine(args[2], "csharp-default.wav");
                context.AddFile(args[0], defaultFile, payload);
                Require(context.DetectFile(defaultFile).Any(d => d.Payload.Equals(payload)), "default-key file watermark");
                Require(context.DetectPcm(new float[44100], 1, 44100).Count == 0, "silence candidates");
            }
            Parallel.For(0, 2, i =>
            {
                string name = "parallel-csharp-" + i;
                using (var c = new Context(new Options { Strength = 15 + i, Workers = 1 }))
                {
                    using (var key = Key.Generate(name)) c.SetKeys(key);
                    uint rate = i == 0 ? 32000u : 44100u, channels = i == 0 ? 1u : 2u;
                    var input = Noise(rate, channels); var bytes = new byte[16];
                    for (int n = 0; n < 16; ++n) bytes[n] = (byte)(i + 1);
                    var data = new Payload(bytes); var output = c.AddPcm(input, channels, rate, data);
                    Require(input.Length == output.Length, "PCM length changed");
                    var found = c.DetectPcm(output, channels, rate);
                    Require(found.Any(d => d.Payload.Equals(data) && d.KeyName == name), "PCM watermark missing");
                    var otherBytes = new byte[16]; for (int n = 0; n < 16; ++n) otherBytes[n] = (byte)(2 - i);
                    var other = new Payload(otherBytes);
                    Require(found.All(d => d.KeyName == name && !d.Payload.Equals(other)), "parallel contexts mixed keys or payloads");
                }
            });
            var disposed = new Context(); disposed.Dispose(); disposed.Dispose();
            try { disposed.DetectPcm(new float[44100], 1, 44100); throw new Exception("disposed context succeeded"); }
            catch (ObjectDisposedException) { }
            Console.WriteLine("C# packaged consumer passed (file, PCM, keys, errors, parallel contexts)");
            return 0;
        }
        catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }
}
