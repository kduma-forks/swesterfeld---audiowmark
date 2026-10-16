use audiowmark::{BlockType, ErrorKind, Library, Options, Payload};
use std::{env, path::PathBuf, thread};
fn noise(rate: u32, channels: u32) -> Vec<f32> {
    let mut state = 123456789u32;
    (0..rate as usize * 40 * channels as usize)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            (state as f64 / u32::MAX as f64 * 0.5 - 0.25) as f32
        })
        .collect()
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().collect();
    if args.len() != 5 {
        return Err("usage: audiowmark-consumer LIBRARY INPUT.wav OUTPUT.wav WORK_DIR".into());
    }
    let library = Library::load(&args[1])?;
    println!("Rust SDK {}", library.version()?);
    let input = PathBuf::from(&args[2]);
    let output = PathBuf::from(&args[3]);
    let work = PathBuf::from(&args[4]);
    let payload = Payload::from_hex("0123456789abcdef0123456789abcdef")?;
    let key = library.generate_key("Rust żółw")?;
    let key_text = key.export()?;
    let imported = library.import_key(&key_text)?;
    assert_eq!(key.name()?, imported.name()?);
    assert_eq!(key.export()?, imported.export()?);
    let key_path = work.join("rust-klucz-żółw.key");
    imported.save(&key_path)?;
    assert_eq!(library.load_key(&key_path)?.export()?, key_text);
    let mut context = library.context()?;
    context.set_keys(&[&imported])?;
    drop(key);
    drop(imported); // context has copied the key
    let failure = context
        .detect_file(work.join("missing-żółw.wav"))
        .unwrap_err();
    assert_eq!(failure.kind, ErrorKind::Io);
    assert!(context.add_pcm(&[0.; 3], 2, 44100, payload).is_err());
    assert!(library
        .context_with_options(&Options {
            workers: 0,
            ..Options::default()
        })
        .is_err());
    assert!(context.detect_pcm(&[], 1, 44100)?.is_empty());
    assert!(context.add_pcm(&[], 1, 44100, payload)?.is_empty());
    context.add_file(&input, &output, payload)?;
    let detections = context.detect_file(&output)?;
    assert!(detections
        .iter()
        .any(|d| d.payload == payload && d.key_name == "Rust żółw"));
    assert!(detections
        .iter()
        .all(|d| d.key_index == 0 && d.speed > 0. && d.quality.is_finite()));
    assert!(detections.iter().any(|d| matches!(
        d.block_type,
        BlockType::ClipA
            | BlockType::ClipB
            | BlockType::ClipAb
            | BlockType::A
            | BlockType::B
            | BlockType::Ab
            | BlockType::All
    )));
    context.set_keys(&[])?;
    assert!(context
        .detect_file(&output)?
        .iter()
        .all(|d| d.payload != payload)); // default key cannot decode the known watermark
    context.add_file(&input, work.join("rust-default.wav"), payload)?;
    assert!(context
        .detect_file(work.join("rust-default.wav"))?
        .iter()
        .any(|d| d.payload == payload));
    assert!(context.detect_pcm(&vec![0.; 44100], 1, 44100)?.is_empty());
    // Two independent contexts use different keys, options, rates and channel counts.
    let mut threads = Vec::new();
    for i in 0..2 {
        let library = library.clone();
        threads.push(thread::spawn(move || -> Result<(), audiowmark::Error> {
            let name = format!("parallel-rust-{i}");
            let key = library.generate_key(&name)?;
            let mut c = library.context_with_options(&Options {
                strength: 15. + i as f64,
                workers: 1,
                ..Options::default()
            })?;
            c.set_keys(&[&key])?;
            let (rate, channels) = if i == 0 { (32000, 1) } else { (44100, 2) };
            let input = noise(rate, channels);
            let payload = Payload([i as u8 + 1; 16]);
            drop(library);
            drop(key); // handles keep module alive, key was copied
            let marked = c.add_pcm(&input, channels, rate, payload)?;
            assert_eq!(marked.len(), input.len());
            let found = c.detect_pcm(&marked, channels, rate)?;
            assert!(found
                .iter()
                .any(|d| d.payload == payload && d.key_name == name));
            assert!(found
                .iter()
                .all(|d| d.key_name == name && d.payload != Payload([2 - i as u8; 16])));
            Ok(())
        }));
    }
    drop(library);
    for t in threads {
        t.join().expect("worker panic")?;
    }
    println!("Rust packaged consumer passed (file, PCM, keys, errors, parallel contexts)");
    Ok(())
}
