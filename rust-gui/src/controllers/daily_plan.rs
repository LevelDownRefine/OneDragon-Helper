use super::super::*;
use super::*;

impl App {
    pub(in crate::main_window) fn receive_plan(&mut self, method: &str, result: Value) {
        if method == "plans.list" {
            match serde_json::from_value::<DailyView>(result) {
                Ok(data) if self.settings_dialog.is_some() => {
                    self.settings_dialog.as_mut().unwrap().set_daily(data);
                    self.write_confirmed = false;
                    self.status = "已同步".into();
                }
                _ => self.fail(Failure::transport("每日计划数据无效")),
            }
        } else if (method == "plans.save" && result.is_string())
            || (method == "plans.delete" && result.is_null())
        {
            self.write_confirmed = true;
            self.ui.toast("每日计划已保存");
            self.request("plans.list", json!({}));
        } else {
            self.fail(Failure::transport("写操作响应无效"));
        }
    }
}
