use libloading::Library;
use std::ffi::{c_char, c_void};

pub(crate) type Handle = *mut c_void;
#[repr(C)]
#[derive(Clone, Copy)]
pub(crate) struct Options {
    pub struct_size: u32,
    pub abi_version: u32,
    pub strength: f64,
    pub sync_threshold: f64,
    pub chunk_minutes: f64,
    pub speed: f64,
    pub speed_mode: u32,
    pub n_best: u32,
    pub workers: u32,
    pub reserved: u32,
}
#[repr(C)]
#[derive(Default)]
pub(crate) struct Detection {
    pub payload: [u8; 16],
    pub key_index: u32,
    pub block_type: u32,
    pub time_seconds: f64,
    pub quality: f64,
    pub decode_error: f64,
    pub ranking: f64,
    pub speed: f64,
}
macro_rules! api {
    ($($name:ident: ($($arg:ty),*) -> $ret:ty;)+) => {
        pub(crate) struct Api {
            $(pub $name: unsafe extern "C" fn($($arg),*) -> $ret,)+
            // Last field: the module must outlive every copied function pointer.
            pub _library: Library,
        }
        impl Api {
            pub unsafe fn load(library: Library) -> Result<Self, libloading::Error> {
                Ok(Self {
                    $($name: *library.get::<unsafe extern "C" fn($($arg),*) -> $ret>(
                        concat!("audiowmark_", stringify!($name), "\0").as_bytes())?,)+
                    _library: library,
                })
            }
        }
    }
}
api! {
    abi_version: () -> u32;
    version: () -> *const c_char;
    options_init: (*mut Options) -> ();
    context_create: (*const Options, *mut Handle, *mut Handle) -> i32;
    context_free: (Handle) -> ();
    context_set_keys: (Handle, *const Handle, u32, *mut Handle) -> i32;
    key_generate: (*const c_char, *mut Handle, *mut Handle) -> i32;
    key_import: (*const c_char, *mut Handle, *mut Handle) -> i32;
    key_load: (*const c_char, *mut Handle, *mut Handle) -> i32;
    key_save: (Handle, *const c_char, *mut Handle) -> i32;
    key_export: (Handle) -> *const c_char;
    key_name: (Handle) -> *const c_char;
    key_free: (Handle) -> ();
    add_file: (Handle, *const c_char, *const c_char, *const u8, *mut Handle) -> i32;
    detect_file: (Handle, *const c_char, *mut Handle, *mut Handle) -> i32;
    add_pcm: (Handle, *const f32, u64, u32, u32, *const u8, *mut f32, u64, *mut Handle) -> i32;
    detect_pcm: (Handle, *const f32, u64, u32, u32, *mut Handle, *mut Handle) -> i32;
    result_count: (Handle) -> u64;
    result_get: (Handle, u64, *mut Detection, *mut Handle) -> i32;
    result_key_name: (Handle, u64) -> *const c_char;
    result_free: (Handle) -> ();
    error_code: (Handle) -> i32;
    error_message: (Handle) -> *const c_char;
    error_free: (Handle) -> ();
}
