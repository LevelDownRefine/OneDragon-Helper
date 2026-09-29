//! Both windows use the same renderer, including systems without a GPU driver.
pub fn options(viewport: eframe::egui::ViewportBuilder) -> eframe::NativeOptions {
    #[cfg(windows)]
    {
        use eframe::egui_wgpu::{WgpuConfiguration, WgpuSetupCreateNew};
        let mut setup = WgpuSetupCreateNew::without_display_handle();
        setup.instance_descriptor.backends = wgpu::Backends::DX12;
        // FXC is provided by Windows; do not depend on an external dxcompiler.dll.
        setup.instance_descriptor.backend_options.dx12 = wgpu::Dx12BackendOptions {
            shader_compiler: wgpu::Dx12Compiler::Fxc,
            // DirectComposition preserves the borderless window's rounded alpha corners.
            presentation_system: wgpu::Dx12SwapchainKind::DxgiFromVisual,
            ..Default::default()
        };
        if std::env::var_os("ODH_FORCE_SOFTWARE_RENDERING").as_deref()
            == Some(std::ffi::OsStr::new("1"))
        {
            setup.native_adapter_selector = Some(std::sync::Arc::new(|adapters, surface| {
                let adapter = adapters
                    .iter()
                    .find(|adapter| {
                        adapter.get_info().device_type == wgpu::DeviceType::Cpu
                            && surface.is_none_or(|surface| adapter.is_surface_supported(surface))
                    })
                    .ok_or("Windows 软件渲染器不可用")?;
                log::info!("使用 Windows 软件渲染器：{}", adapter.get_info().name);
                Ok(adapter.clone())
            }));
        }
        eframe::NativeOptions {
            viewport,
            renderer: eframe::Renderer::Wgpu,
            wgpu_options: WgpuConfiguration {
                wgpu_setup: setup.into(),
                ..Default::default()
            },
            persist_window: false,
            ..Default::default()
        }
    }
    #[cfg(not(windows))]
    eframe::NativeOptions {
        viewport,
        renderer: eframe::Renderer::Glow,
        persist_window: false,
        ..Default::default()
    }
}
