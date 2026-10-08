fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "hermes_host_request",
            "hermes_control_request",
            "hermes_binding_fixture",
        ]),
    ))
    .expect("Tauri build configuration failed");
}
