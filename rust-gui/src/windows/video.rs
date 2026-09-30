//! All COM interfaces stay on the decoder thread. Locked buffers are validated before copying.
use std::{path::Path, time::Duration};
use windows::{
    Win32::{
        Media::MediaFoundation::*,
        System::{
            Com::StructuredStorage::PROPVARIANT,
            Com::{COINIT_MULTITHREADED, CoInitializeEx, CoUninitialize},
            Variant::VT_I8,
        },
    },
    core::{GUID, Interface, PCWSTR},
};

pub(super) struct Runtime;
impl Runtime {
    pub fn new() -> Result<Self, String> {
        // This newly spawned worker has no prior apartment or UI objects.
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED)
                .ok()
                .map_err(|e| e.to_string())?;
            if let Err(error) = MFStartup(MF_VERSION, MFSTARTUP_FULL) {
                CoUninitialize();
                return Err(error.to_string());
            }
        }
        Ok(Self)
    }
}
impl Drop for Runtime {
    fn drop(&mut self) {
        unsafe {
            if let Err(error) = MFShutdown() {
                log::warn!("关闭视频平台失败：{error}");
            }
            CoUninitialize();
        }
    }
}

pub(super) struct Decoder {
    reader: IMFSourceReader,
    width: u32,
    height: u32,
    stride: i32,
    frame_duration: Duration,
}

const STREAM: u32 = MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32;

impl Decoder {
    pub fn open(path: &Path) -> Result<Self, String> {
        if !path.is_absolute() || !path.is_file() {
            return Err("视频文件不存在或路径不是绝对路径".into());
        }
        use std::os::windows::ffi::OsStrExt;
        let path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        unsafe { Self::open_inner(PCWSTR(path.as_ptr())) }.map_err(|e| e.to_string())
    }

    unsafe fn open_inner(path: PCWSTR) -> windows::core::Result<Self> {
        // Source Reader selects only video. The advanced processor performs RGB conversion/resize.
        unsafe {
            let mut attributes = None;
            MFCreateAttributes(&mut attributes, 2)?;
            let attributes = attributes.expect("created attributes");
            attributes.SetUINT32(&MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, 1)?;
            let reader = MFCreateSourceReaderFromURL(path, &attributes)?;
            reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false)?;
            reader.SetStreamSelection(STREAM, true)?;
            let native = reader.GetNativeMediaType(STREAM, 0)?;
            let size = native.GetUINT64(&MF_MT_FRAME_SIZE)?;
            let width = (size >> 32) as u32;
            let height = size as u32;
            check_size(width, height).map_err(|_| {
                windows::core::Error::from_hresult(windows::Win32::Foundation::E_INVALIDARG)
            })?;
            let aspect = native
                .GetUINT64(&MF_MT_PIXEL_ASPECT_RATIO)
                .unwrap_or((1_u64 << 32) | 1);
            let numerator = (aspect >> 32) as u32;
            let denominator = aspect as u32;
            let aspect_width = if numerator > 0 && denominator > 0 {
                width as f64 * numerator as f64 / denominator as f64
            } else {
                width as f64
            };
            let scale = (1920.0 / aspect_width.max(height as f64)).min(1.0);
            let rotation = native.GetUINT32(&MF_MT_VIDEO_ROTATION).unwrap_or(0);
            let output_width = (aspect_width * scale).round().max(1.0) as u32;
            let output_height = (height as f64 * scale).round().max(1.0) as u32;
            // XVP applies the source rotation; request the oriented dimensions to avoid letterboxing.
            let (output_width, output_height) = if matches!(rotation, 90 | 270) {
                (output_height, output_width)
            } else {
                (output_width, output_height)
            };
            let media = MFCreateMediaType()?;
            media.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            media.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_RGB32)?;
            media.SetUINT32(&MF_MT_VIDEO_ROTATION, 0)?;
            media.SetUINT64(
                &MF_MT_FRAME_SIZE,
                (output_width as u64) << 32 | output_height as u64,
            )?;
            media.SetUINT64(&MF_MT_PIXEL_ASPECT_RATIO, (1_u64 << 32) | 1)?;
            reader.SetCurrentMediaType(STREAM, None, &media)?;
            let mut decoder = Self {
                reader,
                width: 0,
                height: 0,
                stride: 0,
                frame_duration: Duration::from_millis(33),
            };
            decoder.update_format()?;
            Ok(decoder)
        }
    }

    unsafe fn update_format(&mut self) -> windows::core::Result<()> {
        unsafe {
            let media = self.reader.GetCurrentMediaType(STREAM)?;
            if media.GetGUID(&MF_MT_SUBTYPE)? != MFVideoFormat_RGB32 {
                return Err(windows::core::Error::from_hresult(
                    windows::Win32::Foundation::E_INVALIDARG,
                ));
            }
            let size = media.GetUINT64(&MF_MT_FRAME_SIZE)?;
            self.width = (size >> 32) as u32;
            self.height = size as u32;
            check_size(self.width, self.height).map_err(|_| {
                windows::core::Error::from_hresult(windows::Win32::Foundation::E_INVALIDARG)
            })?;
            if self.width.max(self.height) > 1920 {
                return Err(windows::core::Error::from_hresult(
                    windows::Win32::Foundation::E_INVALIDARG,
                ));
            }
            self.stride = match media.GetUINT32(&MF_MT_DEFAULT_STRIDE) {
                Ok(value) => value as i32,
                Err(_) => MFGetStrideForBitmapInfoHeader(MFVideoFormat_RGB32.data1, self.width)?,
            };
            if let Ok(rate) = media.GetUINT64(&MF_MT_FRAME_RATE) {
                let numerator = rate >> 32;
                let denominator = rate as u32;
                if numerator > 0 && denominator > 0 {
                    self.frame_duration = Duration::from_secs_f64(
                        (denominator as f64 / numerator as f64).clamp(0.001, 10.0),
                    );
                }
            }
            Ok(())
        }
    }

    pub fn next(&mut self) -> Result<Option<(i64, image::RgbImage)>, String> {
        // A source may emit format/tick notifications without a sample; keep this loop bounded.
        for _ in 0..256 {
            let mut flags = 0;
            let mut timestamp = 0;
            let mut sample = None;
            unsafe {
                self.reader.ReadSample(
                    STREAM,
                    0,
                    None,
                    Some(&mut flags),
                    Some(&mut timestamp),
                    Some(&mut sample),
                )
            }
            .map_err(|e| e.to_string())?;
            if flags & MF_SOURCE_READERF_ERROR.0 as u32 != 0 {
                return Err("视频解码器报告错误".into());
            }
            if flags & MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED.0 as u32 != 0 {
                unsafe { self.update_format() }.map_err(|e| e.to_string())?;
            }
            if let Some(sample) = sample {
                let buffer =
                    unsafe { sample.ConvertToContiguousBuffer() }.map_err(|e| e.to_string())?;
                let image = unsafe { self.copy_buffer(&buffer) }?;
                return Ok(Some((timestamp, image)));
            }
            if flags & MF_SOURCE_READERF_ENDOFSTREAM.0 as u32 != 0 {
                return Ok(None);
            }
        }
        Err("视频连续返回空帧".into())
    }

    unsafe fn copy_buffer(&self, buffer: &IMFMediaBuffer) -> Result<image::RgbImage, String> {
        unsafe {
            let image = if let Ok(buffer2d) = buffer.cast::<IMF2DBuffer2>() {
                let (mut scan, mut base) = (std::ptr::null_mut(), std::ptr::null_mut());
                let (mut pitch, mut length) = (0, 0);
                buffer2d
                    .Lock2DSize(
                        MF2DBuffer_LockFlags_Read,
                        &mut scan,
                        &mut pitch,
                        &mut base,
                        &mut length,
                    )
                    .map_err(|e| e.to_string())?;
                let result = copy_locked(base, length, scan, pitch, self.width, self.height);
                let unlock = buffer2d.Unlock2D().map_err(|e| e.to_string());
                let image = result?;
                unlock?;
                image
            } else {
                let mut base = std::ptr::null_mut();
                let mut length = 0;
                buffer
                    .Lock(&mut base, None, Some(&mut length))
                    .map_err(|e| e.to_string())?;
                let offset = if self.stride < 0 {
                    (self.height as usize - 1) * self.stride.unsigned_abs() as usize
                } else {
                    0
                };
                // Pointer arithmetic is checked in copy_locked, before constructing any slice.
                let scan = (base as usize)
                    .checked_add(offset)
                    .map_or(std::ptr::null_mut(), |p| p as *mut u8);
                let result = copy_locked(base, length, scan, self.stride, self.width, self.height);
                let unlock = buffer.Unlock().map_err(|e| e.to_string());
                let image = result?;
                unlock?;
                image
            };
            Ok(image)
        }
    }

    pub fn rewind(&mut self) -> Result<(), String> {
        let mut zero = PROPVARIANT::default();
        unsafe {
            (*zero.Anonymous.Anonymous).vt = VT_I8;
            (*zero.Anonymous.Anonymous).Anonymous.hVal = 0;
            self.reader
                .SetCurrentPosition(&GUID::zeroed(), &zero)
                .map_err(|e| e.to_string())
        }
    }

    pub fn frame_duration(&self) -> Duration {
        self.frame_duration
    }
}

fn check_size(width: u32, height: u32) -> Result<(), String> {
    if width == 0
        || height == 0
        || width.max(height) > 16384
        || width as u64 * height as u64 * 4 > 256 * 1024 * 1024
    {
        return Err("视频画面尺寸过大或无效".into());
    }
    Ok(())
}

unsafe fn copy_locked(
    base: *mut u8,
    length: u32,
    scan: *mut u8,
    stride: i32,
    width: u32,
    height: u32,
) -> Result<image::RgbImage, String> {
    if base.is_null() || length == 0 || length > 256 * 1024 * 1024 {
        return Err("视频缓冲区无效".into());
    }
    let offset = (scan as usize)
        .checked_sub(base as usize)
        .ok_or("视频扫描线越界")?;
    // Lock/Lock2DSize guarantees this allocation remains valid until the corresponding unlock.
    let bytes = unsafe { std::slice::from_raw_parts(base, length as usize) };
    copy_bgra(bytes, offset, stride, width, height)
}

fn copy_bgra(
    bytes: &[u8],
    offset: usize,
    stride: i32,
    width: u32,
    height: u32,
) -> Result<image::RgbImage, String> {
    check_size(width, height)?;
    let row_size = width as usize * 4;
    if (stride.unsigned_abs() as usize) < row_size {
        return Err("视频行距过小".into());
    }
    let mut rgb = Vec::with_capacity(width as usize * height as usize * 3);
    for row in 0..height as usize {
        let start = offset
            .checked_add_signed(row as isize * stride as isize)
            .ok_or("视频扫描线越界")?;
        let end = start.checked_add(row_size).ok_or("视频行越界")?;
        let pixels = bytes.get(start..end).ok_or("视频缓冲区过小")?;
        for bgra in pixels.chunks_exact(4) {
            rgb.extend_from_slice(&[bgra[2], bgra[1], bgra[0]]);
        }
    }
    Ok(image::RgbImage::from_raw(width, height, rgb).expect("checked RGB dimensions"))
}

#[cfg(test)]
#[path = "../../tests/windows/video.rs"]
mod tests;
