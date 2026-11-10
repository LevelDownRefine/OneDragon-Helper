//! Dialog forms and shared controls; controllers own requests and responses.
pub(crate) mod backup_dialog;
pub(crate) mod common;
pub(crate) mod config_dialog;
pub(crate) mod daily_plan_dialog;
pub(crate) mod drop_dialog;
pub(crate) mod file_picker;
pub(crate) mod list_dialog;
pub(crate) mod run_confirm_dialog;
pub(crate) mod run_options_editor;
pub(crate) mod script_config_dialog;
pub(crate) mod shutdown_dialog;
pub(crate) mod startup_dialog;
pub(crate) mod update_dialog;
pub(crate) mod wallpaper_dialog;

#[cfg(test)]
#[path = "../../tests/dialogs/helpers.rs"]
mod test_support;
