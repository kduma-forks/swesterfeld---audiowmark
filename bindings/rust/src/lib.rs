//! Safe bindings to the audiowmark ABI 1 SDK, loaded from an explicit path.
//! Native binaries are distributed separately; compilation never downloads them.
mod ffi;
use std::{
    cell::Cell,
    ffi::{CStr, CString},
    fmt,
    marker::PhantomData,
    path::Path,
    ptr::{self, NonNull},
    sync::Arc,
};

/// ABI version supported by this wrapper.
pub const ABI_VERSION: u32 = 1;
/// Errors from the SDK or wrapper validation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ErrorKind {
    Argument,
    Io,
    Internal,
    Busy,
    Memory,
    Loading,
    Abi,
    Other(i32),
}
#[derive(Clone, Debug)]
pub struct Error {
    pub kind: ErrorKind,
    pub message: String,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)
    }
}
impl std::error::Error for Error {}
type Result<T> = std::result::Result<T, Error>;
fn error(kind: ErrorKind, message: impl Into<String>) -> Error {
    Error {
        kind,
        message: message.into(),
    }
}
fn text(value: &str) -> Result<CString> {
    CString::new(value).map_err(|_| error(ErrorKind::Argument, "text contains a NUL byte"))
}
fn path(value: &Path) -> Result<CString> {
    text(
        value
            .to_str()
            .ok_or_else(|| error(ErrorKind::Argument, "path must be UTF-8"))?,
    )
}
unsafe fn copy_text(value: *const std::ffi::c_char) -> Result<String> {
    if value.is_null() {
        return Err(error(ErrorKind::Internal, "SDK returned a null string"));
    }
    CStr::from_ptr(value)
        .to_str()
        .map(str::to_owned)
        .map_err(|_| error(ErrorKind::Internal, "SDK returned invalid UTF-8"))
}
struct OwnedError<'a> {
    api: &'a ffi::Api,
    ptr: ffi::Handle,
}
impl Drop for OwnedError<'_> {
    fn drop(&mut self) {
        unsafe { (self.api.error_free)(self.ptr) }
    }
}
fn check(api: &ffi::Api, status: i32, ptr: ffi::Handle) -> Result<()> {
    let owned = OwnedError { api, ptr };
    if status == 0 {
        return Ok(());
    }
    let code = if ptr.is_null() {
        status
    } else {
        unsafe { (api.error_code)(owned.ptr) }
    };
    let kind = match code {
        1 => ErrorKind::Argument,
        2 => ErrorKind::Io,
        3 => ErrorKind::Internal,
        4 => ErrorKind::Busy,
        5 => ErrorKind::Memory,
        code => ErrorKind::Other(code),
    };
    let message = if ptr.is_null() {
        format!("audiowmark error {status}")
    } else {
        unsafe { copy_text((api.error_message)(ptr)) }.unwrap_or_else(|e| e.message)
    };
    Err(error(kind, message))
}

/// Exactly 128 payload bits, in the same order as CLI hexadecimal text.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Payload(pub [u8; 16]);
impl Payload {
    pub fn from_hex(hex: &str) -> Result<Self> {
        if hex.len() != 32 || !hex.is_ascii() {
            return Err(error(
                ErrorKind::Argument,
                "payload requires 32 hexadecimal digits",
            ));
        }
        let mut bytes = [0; 16];
        for (i, byte) in bytes.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16)
                .map_err(|_| error(ErrorKind::Argument, "invalid payload hexadecimal digit"))?;
        }
        Ok(Self(bytes))
    }
}
impl fmt::Display for Payload {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(f, "{byte:02x}")?;
        }
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SpeedMode {
    None,
    Detect,
    Patient,
    Manual(f64),
}
#[derive(Clone, Debug)]
pub struct Options {
    pub strength: f64,
    pub sync_threshold: f64,
    pub chunk_minutes: f64,
    pub speed_mode: SpeedMode,
    pub n_best: u32,
    pub workers: u32,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            strength: 10.,
            sync_threshold: 0.35,
            chunk_minutes: 30.,
            speed_mode: SpeedMode::None,
            n_best: 8,
            workers: 1,
        }
    }
}
impl Options {
    fn native(&self, api: &ffi::Api) -> ffi::Options {
        let mut o = std::mem::MaybeUninit::uninit();
        unsafe {
            (api.options_init)(o.as_mut_ptr());
        }
        let mut o = unsafe { o.assume_init() };
        o.strength = self.strength;
        o.sync_threshold = self.sync_threshold;
        o.chunk_minutes = self.chunk_minutes;
        o.n_best = self.n_best;
        o.workers = self.workers;
        let (mode, speed) = match self.speed_mode {
            SpeedMode::None => (0, 1.),
            SpeedMode::Detect => (1, 1.),
            SpeedMode::Patient => (2, 1.),
            SpeedMode::Manual(speed) => (3, speed),
        };
        o.speed_mode = mode;
        o.speed = speed;
        o
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlockType {
    A,
    B,
    Ab,
    All,
    ClipA,
    ClipB,
    ClipAb,
    Unknown(u32),
}
impl From<u32> for BlockType {
    fn from(v: u32) -> Self {
        match v {
            1 => Self::A,
            2 => Self::B,
            3 => Self::Ab,
            4 => Self::All,
            5 => Self::ClipA,
            6 => Self::ClipB,
            7 => Self::ClipAb,
            v => Self::Unknown(v),
        }
    }
}
#[derive(Clone, Debug)]
pub struct Detection {
    pub payload: Payload,
    pub key_index: u32,
    pub key_name: String,
    pub block_type: BlockType,
    pub time_seconds: f64,
    pub quality: f64,
    pub decode_error: f64,
    pub ranking: f64,
    pub speed: f64,
}

/// A loaded matching SDK. Clones and native handles keep its module alive.
#[derive(Clone)]
pub struct Library {
    api: Arc<ffi::Api>,
}
impl Library {
    /// Load a trusted native SDK from an explicit path (never a bare loader name).
    /// Loading native code executes that library's initialization code.
    pub fn load(library_path: impl AsRef<Path>) -> Result<Self> {
        let library_path = library_path.as_ref();
        if !library_path.is_absolute()
            && library_path
                .parent()
                .map_or(true, |p| p.as_os_str().is_empty())
        {
            return Err(error(
                ErrorKind::Argument,
                "provide an explicit native library path",
            ));
        }
        let library_path = library_path
            .canonicalize()
            .map_err(|e| error(ErrorKind::Loading, e.to_string()))?;
        let library = unsafe { libloading::Library::new(library_path) }
            .map_err(|e| error(ErrorKind::Loading, e.to_string()))?;
        // Check ABI before calling any layout-sensitive function.
        let abi =
            unsafe { library.get::<unsafe extern "C" fn() -> u32>(b"audiowmark_abi_version\0") }
                .map_err(|e| error(ErrorKind::Loading, e.to_string()))?;
        if unsafe { abi() } != ABI_VERSION {
            return Err(error(ErrorKind::Abi, "native SDK ABI must be 1"));
        }
        let api = unsafe { ffi::Api::load(library) }
            .map_err(|e| error(ErrorKind::Loading, e.to_string()))?;
        debug_assert_eq!(unsafe { (api.abi_version)() }, ABI_VERSION);
        Ok(Self { api: Arc::new(api) })
    }
    pub fn version(&self) -> Result<String> {
        unsafe { copy_text((self.api.version)()) }
    }
    pub fn context(&self) -> Result<Context> {
        self.context_with_options(&Options::default())
    }
    pub fn context_with_options(&self, options: &Options) -> Result<Context> {
        let mut ptr = ptr::null_mut();
        let mut err = ptr::null_mut();
        let opts = options.native(&self.api);
        let status = unsafe { (self.api.context_create)(&opts, &mut ptr, &mut err) };
        check(&self.api, status, err)?;
        Ok(Context {
            ptr: NonNull::new(ptr).ok_or_else(|| error(ErrorKind::Internal, "null context"))?,
            api: self.api.clone(),
            _not_sync: PhantomData,
        })
    }
    fn new_key(
        &self,
        value: CString,
        create: unsafe extern "C" fn(
            *const std::ffi::c_char,
            *mut ffi::Handle,
            *mut ffi::Handle,
        ) -> i32,
    ) -> Result<Key> {
        let mut ptr = ptr::null_mut();
        let mut err = ptr::null_mut();
        let status = unsafe { create(value.as_ptr(), &mut ptr, &mut err) };
        check(&self.api, status, err)?;
        Ok(Key {
            ptr: NonNull::new(ptr).ok_or_else(|| error(ErrorKind::Internal, "null key"))?,
            api: self.api.clone(),
        })
    }
    pub fn generate_key(&self, name: &str) -> Result<Key> {
        self.new_key(text(name)?, self.api.key_generate)
    }
    pub fn import_key(&self, cli_text: &str) -> Result<Key> {
        self.new_key(text(cli_text)?, self.api.key_import)
    }
    pub fn load_key(&self, file: impl AsRef<Path>) -> Result<Key> {
        self.new_key(path(file.as_ref())?, self.api.key_load)
    }
}
/// An immutable native key. Contexts copy keys passed to `set_keys`.
pub struct Key {
    ptr: NonNull<std::ffi::c_void>,
    api: Arc<ffi::Api>,
}
// ABI keys are immutable and may be read from different threads.
unsafe impl Send for Key {}
unsafe impl Sync for Key {}
impl Key {
    pub fn export(&self) -> Result<String> {
        unsafe { copy_text((self.api.key_export)(self.ptr.as_ptr())) }
    }
    pub fn name(&self) -> Result<String> {
        unsafe { copy_text((self.api.key_name)(self.ptr.as_ptr())) }
    }
    pub fn save(&self, file: impl AsRef<Path>) -> Result<()> {
        let file = path(file.as_ref())?;
        let mut err = ptr::null_mut();
        let status = unsafe { (self.api.key_save)(self.ptr.as_ptr(), file.as_ptr(), &mut err) };
        check(&self.api, status, err)
    }
}
impl Drop for Key {
    fn drop(&mut self) {
        unsafe { (self.api.key_free)(self.ptr.as_ptr()) }
    }
}
/// One native context. It can move between threads but cannot be shared concurrently.
///
/// ```compile_fail
/// fn require_sync<T: Sync>() {}
/// require_sync::<audiowmark::Context>();
/// ```
pub struct Context {
    ptr: NonNull<std::ffi::c_void>,
    api: Arc<ffi::Api>,
    _not_sync: PhantomData<Cell<()>>,
}
// The native contract permits moving an idle context; every operation needs &mut self.
unsafe impl Send for Context {}
impl Drop for Context {
    fn drop(&mut self) {
        unsafe { (self.api.context_free)(self.ptr.as_ptr()) }
    }
}
struct NativeResult {
    ptr: ffi::Handle,
    api: Arc<ffi::Api>,
}
impl Drop for NativeResult {
    fn drop(&mut self) {
        unsafe { (self.api.result_free)(self.ptr) }
    }
}
impl Context {
    pub fn set_keys(&mut self, keys: &[&Key]) -> Result<()> {
        if keys.iter().any(|k| !Arc::ptr_eq(&k.api, &self.api)) {
            return Err(error(
                ErrorKind::Argument,
                "keys must originate from this loaded Library",
            ));
        }
        let count =
            u32::try_from(keys.len()).map_err(|_| error(ErrorKind::Argument, "too many keys"))?;
        let keys: Vec<_> = keys.iter().map(|k| k.ptr.as_ptr()).collect();
        let mut err = ptr::null_mut();
        let status = unsafe {
            (self.api.context_set_keys)(self.ptr.as_ptr(), keys.as_ptr(), count, &mut err)
        };
        check(&self.api, status, err)
    }
    pub fn add_file(
        &mut self,
        input: impl AsRef<Path>,
        output: impl AsRef<Path>,
        payload: Payload,
    ) -> Result<()> {
        let input = path(input.as_ref())?;
        let output = path(output.as_ref())?;
        let mut err = ptr::null_mut();
        let status = unsafe {
            (self.api.add_file)(
                self.ptr.as_ptr(),
                input.as_ptr(),
                output.as_ptr(),
                payload.0.as_ptr(),
                &mut err,
            )
        };
        check(&self.api, status, err)
    }
    pub fn detect_file(&mut self, file: impl AsRef<Path>) -> Result<Vec<Detection>> {
        let file = path(file.as_ref())?;
        let mut ptr = ptr::null_mut();
        let mut err = ptr::null_mut();
        let status =
            unsafe { (self.api.detect_file)(self.ptr.as_ptr(), file.as_ptr(), &mut ptr, &mut err) };
        let result = NativeResult {
            ptr,
            api: self.api.clone(),
        };
        check(&self.api, status, err)?;
        self.copy_results(result)
    }
    /// Watermark interleaved PCM into a new buffer of exactly the same length.
    pub fn add_pcm(
        &mut self,
        input: &[f32],
        channels: u32,
        sample_rate: u32,
        payload: Payload,
    ) -> Result<Vec<f32>> {
        let frames = frames(input, channels, sample_rate)?;
        let mut output = vec![0.; input.len()];
        let mut err = ptr::null_mut();
        let status = unsafe {
            (self.api.add_pcm)(
                self.ptr.as_ptr(),
                input.as_ptr(),
                frames,
                channels,
                sample_rate,
                payload.0.as_ptr(),
                output.as_mut_ptr(),
                output.len() as u64,
                &mut err,
            )
        };
        check(&self.api, status, err)?;
        Ok(output)
    }
    pub fn detect_pcm(
        &mut self,
        input: &[f32],
        channels: u32,
        sample_rate: u32,
    ) -> Result<Vec<Detection>> {
        let frames = frames(input, channels, sample_rate)?;
        let mut ptr = ptr::null_mut();
        let mut err = ptr::null_mut();
        let status = unsafe {
            (self.api.detect_pcm)(
                self.ptr.as_ptr(),
                input.as_ptr(),
                frames,
                channels,
                sample_rate,
                &mut ptr,
                &mut err,
            )
        };
        let result = NativeResult {
            ptr,
            api: self.api.clone(),
        };
        check(&self.api, status, err)?;
        self.copy_results(result)
    }
    fn copy_results(&self, result: NativeResult) -> Result<Vec<Detection>> {
        if result.ptr.is_null() {
            return Err(error(ErrorKind::Internal, "null result"));
        }
        let count = unsafe { (self.api.result_count)(result.ptr) };
        let count = usize::try_from(count)
            .map_err(|_| error(ErrorKind::Memory, "result count exceeds address space"))?;
        let mut copied = Vec::new();
        copied
            .try_reserve(count)
            .map_err(|_| error(ErrorKind::Memory, "result allocation failed"))?;
        for i in 0..count {
            let mut d = ffi::Detection::default();
            let mut err = ptr::null_mut();
            let status = unsafe { (self.api.result_get)(result.ptr, i as u64, &mut d, &mut err) };
            check(&self.api, status, err)?;
            let key_name = unsafe { copy_text((self.api.result_key_name)(result.ptr, i as u64)) }?;
            copied.push(Detection {
                payload: Payload(d.payload),
                key_index: d.key_index,
                key_name,
                block_type: d.block_type.into(),
                time_seconds: d.time_seconds,
                quality: d.quality,
                decode_error: d.decode_error,
                ranking: d.ranking,
                speed: d.speed,
            });
        }
        Ok(copied)
    }
}
fn frames(input: &[f32], channels: u32, sample_rate: u32) -> Result<u64> {
    if !(1..=64).contains(&channels)
        || !(8000..=384000).contains(&sample_rate)
        || input.len() % channels as usize != 0
        || input.iter().any(|x| !x.is_finite())
    {
        return Err(error(
            ErrorKind::Argument,
            "invalid PCM channels, rate, length or nonfinite samples",
        ));
    }
    Ok((input.len() / channels as usize) as u64)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn abi_layouts() {
        assert_eq!(std::mem::size_of::<ffi::Options>(), 56);
        assert_eq!(std::mem::size_of::<ffi::Detection>(), 64);
        assert_eq!(std::mem::offset_of!(ffi::Detection, time_seconds), 24);
        assert_eq!(std::mem::offset_of!(ffi::Options, workers), 48);
    }
    #[test]
    fn payload_and_pcm_validation() {
        let hex = "0123456789abcdef0123456789abcdef";
        assert_eq!(Payload::from_hex(hex).unwrap().to_string(), hex);
        assert!(Payload::from_hex("éééééééééééééééé").is_err());
        assert!(frames(&[0.; 3], 2, 44100).is_err());
        assert!(frames(&[f32::NAN], 1, 44100).is_err());
    }
    #[test]
    fn send_contract() {
        fn send<T: Send>() {}
        send::<Context>();
        send::<Library>();
    }
}
